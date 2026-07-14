from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, inspect, select, update
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, Category, RefundLink, Transaction, TransferLink
from .mutation_log import MutationChange, changed_values, full_values, journal_mutation
from .transaction_queries import get_live_transaction, live_transaction_select


REFUND_WINDOW_DAYS = 90
MAX_AUTOMATIC_SUGGESTIONS = 25
MAX_MANUAL_CANDIDATES = 50
SPEND_ACCOUNT_TYPES = {"checking", "savings", "credit_card", "cash", "other"}
MATCH_STATUSES = {"needs_review", "suggested", "possible_duplicate", "confirmed"}
REFUND_TERMS = ("REFUND", "RETURN", "RETURNED", "REVERSAL", "REVERSED", "MERCH CREDIT", "PURCHASE CREDIT")
PAYMENT_TERMS = (
    "AUTOPAY", "AUTO PAY", "AUTO-PMT", "AUTO PMT", "PAYMENT", "CARD PAY", "PMT", "PYMT",
    "THANK YOU", "TRANSFER", "XFER", "ACH", "DIRECT DEPOSIT",
    "DIRECT DEP", "PAYROLL", "SALARY", "INTEREST PAID", "DIVIDEND", "CASH ADVANCE",
)
NON_REFUND_TYPES = {"transfer", "credit_card_payment", "investment_flow"}
TOKEN_STOPWORDS = {
    "and", "card", "credit", "debit", "from", "online", "payment", "pending",
    "marketplace", "merchant", "mobile", "purchase", "refund", "return", "store",
    "the", "transaction", "venmo", "with",
}


@dataclass(frozen=True)
class RefundCandidate:
    expense_transaction: Transaction
    refund_transaction: Transaction
    match_confidence: int


class OverRefundError(ValueError):
    def __init__(self, *, expense_cents: int, linked_refund_cents: int):
        self.expense_cents = expense_cents
        self.linked_refund_cents = linked_refund_cents
        super().__init__(
            f"Linked refunds total ${linked_refund_cents / 100:,.2f}, which exceeds the ${expense_cents / 100:,.2f} expense. Confirm again to link it anyway."
        )


def score_refund_match(expense: Transaction, refund: Transaction, accounts: dict[int, Account], *, allow_over_amount: bool = False) -> int | None:
    if expense.id is not None and expense.id == refund.id:
        return None
    if expense.amount_cents >= 0 or refund.amount_cents <= 0:
        return None
    if refund.transaction_date < expense.transaction_date:
        return None
    day_gap = (refund.transaction_date - expense.transaction_date).days
    if day_gap > REFUND_WINDOW_DAYS or (refund.amount_cents > abs(expense.amount_cents) and not allow_over_amount):
        return None
    expense_account = accounts.get(expense.account_id)
    refund_account = accounts.get(refund.account_id)
    if not expense_account or not refund_account or expense_account.account_type not in SPEND_ACCOUNT_TYPES or refund_account.account_type not in SPEND_ACCOUNT_TYPES:
        return None

    if _is_payment_like(refund):
        return None
    expense_tokens = _description_tokens(expense)
    refund_tokens = _description_tokens(refund)
    overlap = len(expense_tokens & refund_tokens)
    has_refund_signal = _has_refund_signal(refund)
    same_account = expense.account_id == refund.account_id
    if not has_refund_signal and overlap == 0:
        return None
    if not same_account and (not has_refund_signal or overlap == 0):
        return None

    confidence = 10
    if same_account:
        confidence += 35
    if has_refund_signal:
        confidence += 20
    if overlap:
        confidence += min(30, overlap * 12)
    if refund.amount_cents == abs(expense.amount_cents):
        confidence += 25
    confidence += max(0, 10 - day_gap // 10)
    if _is_venmo(expense_account, expense) and _is_venmo(refund_account, refund) and overlap:
        confidence += 10
    return min(100, confidence) if confidence >= 65 else None


def detect_refund_candidates(db: Session, *, limit: int = MAX_AUTOMATIC_SUGGESTIONS) -> list[RefundCandidate]:
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.status == "active")).all()}
    linked_refund_ids = {link.refund_transaction_id for link in db.scalars(select(RefundLink)).all()}
    transfer_ids = _all_transfer_transaction_ids(db)
    rows = db.scalars(
        live_transaction_select(Transaction.review_status.in_(list(MATCH_STATUSES)))
        .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
    ).all()
    expenses = [row for row in rows if row.amount_cents < 0 and row.id not in transfer_ids]
    refunds = [
        row for row in rows
        if row.amount_cents > 0
        and row.id not in linked_refund_ids
        and row.id not in transfer_ids
        and accounts.get(row.account_id)
        and accounts[row.account_id].account_type in SPEND_ACCOUNT_TYPES
        and not _is_payment_like(row)
    ]
    expenses_by_id = {row.id: row for row in expenses}
    expenses_by_account_amount: dict[tuple[int, int], list[Transaction]] = {}
    expenses_by_token_account: dict[tuple[str, int], list[Transaction]] = {}
    expenses_by_token: dict[str, list[Transaction]] = {}
    for expense in expenses:
        expenses_by_account_amount.setdefault((expense.account_id, abs(expense.amount_cents)), []).append(expense)
        for token in _description_tokens(expense):
            expenses_by_token_account.setdefault((token, expense.account_id), []).append(expense)
            expenses_by_token.setdefault(token, []).append(expense)
    for rows_by_key in (*expenses_by_account_amount.values(), *expenses_by_token_account.values(), *expenses_by_token.values()):
        rows_by_key.sort(key=lambda row: (row.transaction_date, row.id))
    token_account_dates = {key: [row.transaction_date for row in value] for key, value in expenses_by_token_account.items()}
    token_dates = {key: [row.transaction_date for row in value] for key, value in expenses_by_token.items()}

    candidates: list[RefundCandidate] = []
    for refund in refunds:
        best: RefundCandidate | None = None
        possible_expense_ids = {
            row.id for row in expenses_by_account_amount.get((refund.account_id, refund.amount_cents), [])
            if refund.transaction_date - timedelta(days=REFUND_WINDOW_DAYS) <= row.transaction_date <= refund.transaction_date
        }
        refund_has_signal = _has_refund_signal(refund)
        for token in _description_tokens(refund):
            account_key = (token, refund.account_id)
            possible_expense_ids.update(_recent_expense_ids(expenses_by_token_account.get(account_key, []), token_account_dates.get(account_key, []), refund.transaction_date, limit=50))
            if refund_has_signal:
                possible_expense_ids.update(_recent_expense_ids(expenses_by_token.get(token, []), token_dates.get(token, []), refund.transaction_date, limit=20))
        for expense_id in possible_expense_ids:
            expense = expenses_by_id[expense_id]
            confidence = score_refund_match(expense, refund, accounts)
            if confidence is None:
                continue
            candidate = RefundCandidate(expense, refund, confidence)
            if best is None or candidate.match_confidence > best.match_confidence:
                best = candidate
        if best:
            candidates.append(best)
    return sorted(candidates, key=lambda candidate: (-candidate.match_confidence, candidate.refund_transaction.id))[:limit]


def create_refund_suggestions(db: Session, actor: str = "local-user") -> dict:
    removed = _clear_open_refund_suggestions(db, actor)
    suggestions: list[dict] = []
    changes: list[MutationChange] = []
    for candidate in detect_refund_candidates(db):
        refund_before = changed_values(candidate.refund_transaction, ["review_status"])
        link = RefundLink(
            expense_transaction_id=candidate.expense_transaction.id,
            refund_transaction_id=candidate.refund_transaction.id,
            match_confidence=candidate.match_confidence,
            confirmed=False,
        )
        db.add(link)
        if candidate.refund_transaction.review_status != "confirmed":
            candidate.refund_transaction.review_status = "suggested"
        db.flush()
        changes.extend([
            MutationChange(link.id, None, full_values(link), entity_type="refund_link"),
            MutationChange(candidate.refund_transaction.id, refund_before, changed_values(candidate.refund_transaction, ["review_status"]), entity_type="transaction"),
        ])
        record_audit_event(db, "refund_suggest", actor, "refund_link", str(link.id), {
            "expense_transaction_id": link.expense_transaction_id,
            "refund_transaction_id": link.refund_transaction_id,
            "match_confidence": link.match_confidence,
        })
        suggestions.append(refund_link_payload(db, link, candidate.expense_transaction, candidate.refund_transaction))
    operation_id = journal_mutation(
        db,
        kind="create",
        entity_type="mixed",
        actor=actor,
        description=f"Created {len(suggestions)} refund suggestions",
        changes=changes,
    ) if changes else None
    db.commit()
    return {"created": len(suggestions), "removed": removed, "suggestions": suggestions, "operation_id": operation_id, "limit": MAX_AUTOMATIC_SUGGESTIONS, "limited": len(suggestions) == MAX_AUTOMATIC_SUGGESTIONS}


def list_refund_links(db: Session, *, confirmed: bool | None = None, expense_transaction_id: int | None = None) -> list[dict]:
    query = select(RefundLink)
    if confirmed is not None:
        query = query.where(RefundLink.confirmed.is_(confirmed))
    if expense_transaction_id is not None:
        query = query.where(RefundLink.expense_transaction_id == expense_transaction_id)
    links = db.scalars(query.order_by(RefundLink.match_confidence.desc(), RefundLink.id.desc())).all()
    transaction_ids = {link.expense_transaction_id for link in links} | {link.refund_transaction_id for link in links}
    transactions = {row.id: row for row in db.scalars(live_transaction_select(Transaction.id.in_(transaction_ids))).all()} if transaction_ids else {}
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    results = []
    for link in links:
        expense = transactions.get(link.expense_transaction_id)
        refund = transactions.get(link.refund_transaction_id)
        if not expense or not refund:
            continue
        if confirmed is False and score_refund_match(expense, refund, accounts) is None:
            continue
        results.append(refund_link_payload(db, link, expense, refund))
        if confirmed is False and len(results) >= MAX_AUTOMATIC_SUGGESTIONS:
            break
    return results


def list_manual_refund_candidates(db: Session, *, expense_transaction_id: int, search: str | None = None) -> list[dict]:
    expense = get_live_transaction(db, expense_transaction_id)
    if not expense or expense.amount_cents >= 0:
        raise ValueError("Choose an active money-out transaction")
    linked_refund_ids = {link.refund_transaction_id for link in db.scalars(select(RefundLink).where(RefundLink.confirmed.is_(True))).all()}
    transfer_ids = _all_transfer_transaction_ids(db)
    query = live_transaction_select(
        Transaction.amount_cents > 0,
        Transaction.transaction_date >= expense.transaction_date,
        Transaction.transaction_date <= expense.transaction_date + timedelta(days=REFUND_WINDOW_DAYS),
    )
    needle = (search or "").strip().casefold()
    rows = db.scalars(query.order_by(Transaction.transaction_date.desc(), Transaction.id.desc())).all()
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    ranked_results: list[tuple[int, Transaction]] = []
    for row in rows:
        if row.id in linked_refund_ids or row.id in transfer_ids:
            continue
        if accounts.get(row.account_id) and accounts[row.account_id].account_type not in SPEND_ACCOUNT_TYPES:
            continue
        if needle and needle not in f"{row.raw_description} {row.user_note or ''}".casefold():
            continue
        confidence = score_refund_match(expense, row, accounts, allow_over_amount=True)
        if confidence is None:
            continue
        ranked_results.append((confidence, row))
    ranked_results.sort(key=lambda item: (-item[0], -item[1].transaction_date.toordinal(), -item[1].id))
    return [_transaction_payload(db, row, accounts) for _, row in ranked_results[:MAX_MANUAL_CANDIDATES]]


def create_manual_refund_link(
    db: Session,
    *,
    expense_transaction_id: int,
    refund_transaction_id: int,
    match_confidence: int = 100,
    confirmed: bool = True,
    allow_over_refund: bool = False,
    actor: str = "local-user",
) -> dict:
    existing_link = db.scalar(select(RefundLink).where(RefundLink.refund_transaction_id == refund_transaction_id))
    if existing_link and existing_link.confirmed:
        raise ValueError("That refund is already linked to an expense")
    existing_before = full_values(existing_link) if existing_link else None
    link = existing_link or RefundLink(refund_transaction_id=refund_transaction_id, confirmed=False)
    link.expense_transaction_id = expense_transaction_id
    link.match_confidence = match_confidence
    if not existing_link:
        db.add(link)
        db.flush()
    if confirmed:
        return confirm_refund_link(db, link, allow_over_refund=allow_over_refund, actor=actor, description="Linked refund to expense", link_was_created=not existing_link, link_before_override=existing_before)
    operation_id = journal_mutation(db, kind="create" if not existing_link else "update", entity_type="refund_link", actor=actor, description="Created refund link", changes=[
        MutationChange(link.id, existing_before, full_values(link), entity_type="refund_link"),
    ])
    db.commit()
    return {**refund_link_payload(db, link), "operation_id": operation_id}


def confirm_refund_link(
    db: Session,
    link: RefundLink,
    *,
    allow_over_refund: bool = False,
    actor: str = "local-user",
    description: str = "Confirmed refund match",
    link_was_created: bool = False,
    link_before_override: dict | None = None,
) -> dict:
    expense = get_live_transaction(db, link.expense_transaction_id)
    refund = get_live_transaction(db, link.refund_transaction_id)
    if not expense or not refund:
        raise ValueError("Refund link points to a missing transaction")
    if expense.amount_cents >= 0 or refund.amount_cents <= 0:
        raise ValueError("Refund links require a money-out expense and a money-in refund")
    confirmed_transfer_ids = _confirmed_transfer_transaction_ids(db)
    if expense.id in confirmed_transfer_ids or refund.id in confirmed_transfer_ids:
        raise ValueError("A confirmed transfer/payment already uses one of these transactions")
    linked_total = sum(
        existing.refund_transaction.amount_cents
        for existing in _confirmed_links_with_refunds(db, expense.id, exclude_link_id=link.id)
    ) + refund.amount_cents
    if linked_total > abs(expense.amount_cents) and not allow_over_refund:
        raise OverRefundError(expense_cents=abs(expense.amount_cents), linked_refund_cents=linked_total)

    link_before = link_before_override if link_before_override is not None else None if link_was_created else changed_values(link, ["confirmed"])
    refund_before = changed_values(refund, ["transaction_type", "review_status", "category_id"])
    link.confirmed = True
    refund.transaction_type = "refund"
    refund.review_status = "confirmed"
    refund.category_id = expense.category_id
    changes = [
        MutationChange(link.id, link_before, full_values(link) if link_was_created or link_before_override is not None else changed_values(link, ["confirmed"]), entity_type="refund_link"),
        MutationChange(refund.id, refund_before, changed_values(refund, ["transaction_type", "review_status", "category_id"]), entity_type="transaction"),
    ]
    operation_id = journal_mutation(db, kind="update", entity_type="mixed", actor=actor, description=description, changes=changes)
    record_audit_event(db, "refund_confirm", actor, "refund_link", str(link.id), {
        "expense_transaction_id": expense.id,
        "refund_transaction_id": refund.id,
        "linked_refund_cents": linked_total,
        "over_refund_confirmed": linked_total > abs(expense.amount_cents),
    })
    db.commit()
    return {**refund_link_payload(db, link, expense, refund), "operation_id": operation_id}


def reject_refund_link(db: Session, link: RefundLink, actor: str = "local-user") -> dict:
    link_id = link.id
    refund = get_live_transaction(db, link.refund_transaction_id)
    changes = [MutationChange(link.id, full_values(link), None, entity_type="refund_link")]
    if refund and refund.review_status == "suggested":
        before = changed_values(refund, ["review_status"])
        refund.review_status = "needs_review"
        changes.append(MutationChange(refund.id, before, changed_values(refund, ["review_status"]), entity_type="transaction"))
    operation_id = journal_mutation(db, kind="delete", entity_type="mixed", actor=actor, description="Dismissed refund suggestion", changes=changes)
    record_audit_event(db, "refund_reject", actor, "refund_link", str(link_id), {
        "expense_transaction_id": link.expense_transaction_id,
        "refund_transaction_id": link.refund_transaction_id,
    })
    db.delete(link)
    db.commit()
    return {"id": link_id, "rejected": True, "operation_id": operation_id}


def delete_refund_link(db: Session, link: RefundLink, actor: str = "local-user") -> dict:
    link_id = link.id
    operation_id = journal_mutation(db, kind="delete", entity_type="refund_link", actor=actor, description="Unlinked refund from expense", changes=[
        MutationChange(link.id, full_values(link), None, entity_type="refund_link"),
    ])
    record_audit_event(db, "refund_unlink", actor, "refund_link", str(link_id), {
        "expense_transaction_id": link.expense_transaction_id,
        "refund_transaction_id": link.refund_transaction_id,
    })
    db.delete(link)
    db.commit()
    return {"id": link_id, "deleted": True, "operation_id": operation_id}


def confirmed_refund_transaction_ids(db: Session) -> set[int]:
    ids: set[int] = set()
    for link in db.scalars(select(RefundLink).where(RefundLink.confirmed.is_(True))).all():
        ids.update((link.expense_transaction_id, link.refund_transaction_id))
    return ids


def refund_link_payload(db: Session, link: RefundLink, expense: Transaction | None = None, refund: Transaction | None = None) -> dict:
    expense = expense or get_live_transaction(db, link.expense_transaction_id)
    refund = refund or get_live_transaction(db, link.refund_transaction_id)
    if not expense or not refund:
        return {"id": link.id, "confirmed": link.confirmed, "match_confidence": link.match_confidence}
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.id.in_([expense.account_id, refund.account_id]))).all()}
    confirmed_total = sum(item.refund_transaction.amount_cents for item in _confirmed_links_with_refunds(db, expense.id))
    if not link.confirmed:
        confirmed_total += refund.amount_cents
    return {
        "id": link.id,
        "expense_transaction": _transaction_payload(db, expense, accounts),
        "refund_transaction": _transaction_payload(db, refund, accounts),
        "match_confidence": link.match_confidence,
        "confirmed": link.confirmed,
        "expense_amount_cents": abs(expense.amount_cents),
        "linked_refund_cents": confirmed_total,
        "would_exceed_expense": confirmed_total > abs(expense.amount_cents),
    }


@dataclass(frozen=True)
class _LinkWithRefund:
    link: RefundLink
    refund_transaction: Transaction


def _confirmed_links_with_refunds(db: Session, expense_id: int, exclude_link_id: int | None = None) -> list[_LinkWithRefund]:
    links = db.scalars(select(RefundLink).where(RefundLink.expense_transaction_id == expense_id, RefundLink.confirmed.is_(True))).all()
    if exclude_link_id is not None:
        links = [link for link in links if link.id != exclude_link_id]
    refunds = {row.id: row for row in db.scalars(select(Transaction).where(Transaction.id.in_([link.refund_transaction_id for link in links]))).all()} if links else {}
    return [_LinkWithRefund(link, refunds[link.refund_transaction_id]) for link in links if link.refund_transaction_id in refunds]


def _confirmed_transfer_transaction_ids(db: Session) -> set[int]:
    ids: set[int] = set()
    for link in db.scalars(select(TransferLink).where(TransferLink.confirmed.is_(True))).all():
        ids.update((link.from_transaction_id, link.to_transaction_id))
    return ids


def _all_transfer_transaction_ids(db: Session) -> set[int]:
    ids: set[int] = set()
    for link in db.scalars(select(TransferLink)).all():
        ids.update((link.from_transaction_id, link.to_transaction_id))
    return ids


def _clear_open_refund_suggestions(db: Session, actor: str) -> int:
    open_links = db.execute(
        select(RefundLink.id, RefundLink.refund_transaction_id).where(RefundLink.confirmed.is_(False))
    ).all()
    open_link_ids = {link_id for link_id, _ in open_links}
    refund_ids = {refund_transaction_id for _, refund_transaction_id in open_links}
    if not refund_ids:
        return 0
    transfer_suggestion_ids: set[int] = set()
    for link in db.scalars(select(TransferLink).where(TransferLink.confirmed.is_(False))).all():
        transfer_suggestion_ids.update((link.from_transaction_id, link.to_transaction_id))
    reset_ids = refund_ids - transfer_suggestion_ids
    db.execute(delete(RefundLink).where(RefundLink.confirmed.is_(False)))
    # SQLite may immediately reuse deleted integer primary keys. Detach any
    # previously loaded suggestions so replacements cannot collide with stale
    # objects in this session's identity map.
    for loaded in list(db.identity_map.values()):
        identity = inspect(loaded).identity
        if isinstance(loaded, RefundLink) and identity and identity[0] in open_link_ids:
            db.expunge(loaded)
    if reset_ids:
        db.execute(update(Transaction).where(Transaction.id.in_(reset_ids), Transaction.review_status == "suggested").values(review_status="needs_review"))
    record_audit_event(db, "refund_suggestions_refresh", actor, "refund_link", "open", {"removed": len(refund_ids)})
    db.flush()
    return len(refund_ids)


def _description_tokens(transaction: Transaction) -> set[str]:
    text = f"{transaction.raw_description} {transaction.normalized_payee or ''} {transaction.user_note or ''}".casefold()
    return {token for token in re.findall(r"[a-z0-9]+", text) if len(token) >= 3 and token not in TOKEN_STOPWORDS and not token.isdigit()}


def _recent_expense_ids(expenses: list[Transaction], dates: list[date], refund_date: date, *, limit: int) -> set[int]:
    if not expenses:
        return set()
    start = bisect_left(dates, refund_date - timedelta(days=REFUND_WINDOW_DAYS))
    end = bisect_right(dates, refund_date)
    return {row.id for row in expenses[max(start, end - limit):end]}


def _has_refund_signal(transaction: Transaction) -> bool:
    description = f"{transaction.raw_description} {transaction.user_note or ''}".upper()
    return transaction.transaction_type == "refund" or _contains_term(description, REFUND_TERMS)


def _is_payment_like(transaction: Transaction) -> bool:
    if transaction.transaction_type in NON_REFUND_TYPES:
        return True
    if _has_refund_signal(transaction):
        return False
    description = f"{transaction.raw_description} {transaction.user_note or ''}".upper()
    return _contains_term(description, PAYMENT_TERMS)


def _contains_term(description: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![A-Z0-9]){re.escape(term)}(?![A-Z0-9])", description) for term in terms)


def _is_venmo(account: Account, transaction: Transaction) -> bool:
    return "venmo" in f"{account.display_name} {transaction.raw_description}".casefold()


def _transaction_payload(db: Session, transaction: Transaction, accounts: dict[int, Account] | None = None) -> dict:
    accounts = accounts or {transaction.account_id: db.get(Account, transaction.account_id)}
    account = accounts.get(transaction.account_id)
    category = db.get(Category, transaction.category_id) if transaction.category_id else None
    institution = account.institution if account else None
    return {
        "id": transaction.id,
        "account_id": transaction.account_id,
        "account": account.display_name if account else "Unknown account",
        "institution": institution.name if institution else None,
        "account_last_four": account.last_four if account else None,
        "reference": transaction.source_reference,
        "date": transaction.transaction_date.isoformat(),
        "posted_date": transaction.posted_date.isoformat() if transaction.posted_date else None,
        "amount": transaction.amount_cents / 100,
        "amount_cents": transaction.amount_cents,
        "description": transaction.raw_description,
        "category_id": transaction.category_id,
        "category": category.label if category else None,
        "notes": transaction.user_note,
        "labels": ", ".join((transaction.labels or "").strip("|").split("|")) or None,
        "import_source": "Bank import" if transaction.import_batch_id else "Manual entry",
        "transaction_type": transaction.transaction_type,
        "review_status": transaction.review_status,
    }
