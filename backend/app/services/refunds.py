from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import delete, inspect, select, update
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..config import settings
from ..models import Account, Category, RefundLink, RefundPairDecision, RefundReviewResolution, Transaction, TransferLink
from .mutation_log import MutationChange, changed_values, full_values, journal_mutation
from .transaction_queries import get_live_transaction, live_transaction_select


REFUND_WINDOW_DAYS = 90
MAX_AUTOMATIC_SUGGESTIONS = 25
MAX_CANDIDATES_PER_REFUND = 5
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
    "and", "approximate", "card", "charge", "charged", "credit", "debit", "for", "from", "online", "paid", "payment", "pending",
    "marketplace", "merchant", "mobile", "purchase", "refund", "return", "store",
    "request", "requested", "the", "transaction", "venmo", "with",
}


@dataclass(frozen=True)
class RefundCandidate:
    expense_transaction: Transaction
    refund_transaction: Transaction
    match_confidence: int


@dataclass(frozen=True)
class RefundCandidateGroup:
    refund_transaction: Transaction
    candidates: tuple[RefundCandidate, ...]
    candidate_count: int


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

    if _is_payment_like(refund, refund_account):
        return None
    expense_tokens = _description_tokens(expense, expense_account)
    refund_tokens = _description_tokens(refund, refund_account)
    overlap = len(expense_tokens & refund_tokens)
    explicit_refund_signal = _has_explicit_refund_signal(refund)
    same_account = expense.account_id == refund.account_id
    exact_amount = refund.amount_cents == abs(expense.amount_cents)
    category_match = expense.category_id is not None and expense.category_id == refund.category_id
    category_conflict = expense.category_id is not None and refund.category_id is not None and expense.category_id != refund.category_id
    venmo_refund = _is_venmo(refund_account, refund)
    venmo_expense = _is_venmo(expense_account, expense)

    if venmo_refund:
        # Venmo money-in usually reimburses spending that happened elsewhere. A
        # Venmo-to-Venmo link is exceptional and needs exact, memo-level evidence.
        if venmo_expense and not (exact_amount and overlap > 0 and day_gap <= 30):
            return None
        if not exact_amount and overlap == 0:
            return None

        confidence = 5
        if expense_account.account_type == "credit_card":
            confidence += 25
        elif expense_account.account_type in {"checking", "savings"}:
            confidence += 8
        elif expense_account.account_type == "cash":
            confidence += 4
        if explicit_refund_signal:
            confidence += 8
    else:
        if not explicit_refund_signal and overlap == 0 and not exact_amount:
            return None
        if not same_account and (not explicit_refund_signal or overlap == 0):
            return None

        confidence = 5
        if same_account:
            confidence += 25
        if explicit_refund_signal:
            confidence += 15
        elif refund.transaction_type == "refund":
            # A stored type is supporting context, not proof of a particular link.
            confidence += 5

    confidence += _amount_match_score(expense, refund)
    confidence += min(30, overlap * 12)
    confidence += _recency_score(day_gap)
    if category_match:
        confidence += 12
    elif category_conflict:
        confidence -= 8

    if confidence < 65:
        return None
    # Reserve 100 for close, exact-amount matches with meaningful description
    # overlap. Other strong suggestions remain visibly less than certain.
    if not (exact_amount and overlap > 0 and day_gap <= 30):
        confidence = min(confidence, 95)
    return min(100, confidence)


def detect_refund_candidates(db: Session, *, limit: int = MAX_AUTOMATIC_SUGGESTIONS) -> list[RefundCandidate]:
    return [group.candidates[0] for group in detect_refund_candidate_groups(db, limit=limit)]


def detect_refund_candidate_groups(
    db: Session,
    *,
    limit: int = MAX_AUTOMATIC_SUGGESTIONS,
    candidates_per_refund: int = MAX_CANDIDATES_PER_REFUND,
    refund_ids: set[int] | None = None,
) -> list[RefundCandidateGroup]:
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.status == "active")).all()}
    linked_refund_ids = {link.refund_transaction_id for link in db.scalars(select(RefundLink).where(RefundLink.confirmed.is_(True))).all()}
    confirmed_refunds_by_expense = _confirmed_refunds_by_expense(db)
    confirmed_total_by_expense = {
        expense_id: sum(item.refund_transaction.amount_cents for item in items)
        for expense_id, items in confirmed_refunds_by_expense.items()
    }
    resolved_refund_ids = {resolution.refund_transaction_id for resolution in db.scalars(select(RefundReviewResolution)).all()}
    rejected_pairs = {
        (decision.refund_transaction_id, decision.expense_transaction_id)
        for decision in db.scalars(select(RefundPairDecision).where(RefundPairDecision.decision == "rejected")).all()
    }
    transfer_ids = _all_transfer_transaction_ids(db)
    rows = db.scalars(
        live_transaction_select(Transaction.review_status.in_(list(MATCH_STATUSES)))
        .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
    ).all()
    expenses = [
        row for row in rows
        if row.amount_cents < 0
        and row.id not in transfer_ids
        # A fully refunded expense cannot accept another ordinary refund. Keep
        # over-refund validation at confirmation time as a final safety check,
        # but do not rank a settled expense as a fresh recommendation.
        and confirmed_total_by_expense.get(row.id, 0) < abs(row.amount_cents)
    ]
    refunds = [
        row for row in rows
        if row.amount_cents > 0
        and (refund_ids is None or row.id in refund_ids)
        and row.id not in linked_refund_ids
        and row.id not in resolved_refund_ids
        and row.id not in transfer_ids
        and accounts.get(row.account_id)
        and accounts[row.account_id].account_type in SPEND_ACCOUNT_TYPES
        and not _is_payment_like(row, accounts.get(row.account_id))
    ]
    expenses_by_id = {row.id: row for row in expenses}
    expenses_by_account_amount: dict[tuple[int, int], list[Transaction]] = {}
    expenses_by_amount: dict[int, list[Transaction]] = {}
    expenses_by_token_account: dict[tuple[str, int], list[Transaction]] = {}
    expenses_by_token: dict[str, list[Transaction]] = {}
    for expense in expenses:
        expenses_by_account_amount.setdefault((expense.account_id, abs(expense.amount_cents)), []).append(expense)
        expenses_by_amount.setdefault(abs(expense.amount_cents), []).append(expense)
        for token in _description_tokens(expense, accounts.get(expense.account_id)):
            expenses_by_token_account.setdefault((token, expense.account_id), []).append(expense)
            expenses_by_token.setdefault(token, []).append(expense)
    for rows_by_key in (*expenses_by_account_amount.values(), *expenses_by_amount.values(), *expenses_by_token_account.values(), *expenses_by_token.values()):
        rows_by_key.sort(key=lambda row: (row.transaction_date, row.id))
    amount_dates = {key: [row.transaction_date for row in value] for key, value in expenses_by_amount.items()}
    token_account_dates = {key: [row.transaction_date for row in value] for key, value in expenses_by_token_account.items()}
    token_dates = {key: [row.transaction_date for row in value] for key, value in expenses_by_token.items()}

    groups: list[RefundCandidateGroup] = []
    for refund in refunds:
        ranked: list[RefundCandidate] = []
        possible_expense_ids = {
            row.id for row in expenses_by_account_amount.get((refund.account_id, refund.amount_cents), [])
            if refund.transaction_date - timedelta(days=REFUND_WINDOW_DAYS) <= row.transaction_date <= refund.transaction_date
        }
        refund_account = accounts.get(refund.account_id)
        refund_is_venmo = bool(refund_account and _is_venmo(refund_account, refund))
        if refund_is_venmo:
            possible_expense_ids.update(_recent_expense_ids(expenses_by_amount.get(refund.amount_cents, []), amount_dates.get(refund.amount_cents, []), refund.transaction_date, limit=50))
        refund_can_cross_accounts = refund_is_venmo or _has_explicit_refund_signal(refund)
        for token in _description_tokens(refund, refund_account):
            account_key = (token, refund.account_id)
            possible_expense_ids.update(_recent_expense_ids(expenses_by_token_account.get(account_key, []), token_account_dates.get(account_key, []), refund.transaction_date, limit=50))
            if refund_can_cross_accounts:
                possible_expense_ids.update(_recent_expense_ids(expenses_by_token.get(token, []), token_dates.get(token, []), refund.transaction_date, limit=20))
        for expense_id in possible_expense_ids:
            if (refund.id, expense_id) in rejected_pairs:
                continue
            expense = expenses_by_id[expense_id]
            confidence = score_refund_match(expense, refund, accounts)
            if confidence is None:
                continue
            remaining_refundable = abs(expense.amount_cents) - confirmed_total_by_expense.get(expense.id, 0)
            if refund.amount_cents > remaining_refundable:
                # A partially refunded expense can still be a legitimate match,
                # but an option that exceeds its remaining balance should never
                # outrank an equally plausible clean fit.
                confidence -= 25
                if confidence < 65:
                    continue
            ranked.append(RefundCandidate(expense, refund, confidence))
        if ranked:
            ranked.sort(key=lambda candidate: (
                -candidate.match_confidence,
                (candidate.refund_transaction.transaction_date - candidate.expense_transaction.transaction_date).days,
                candidate.expense_transaction.id,
            ))
            groups.append(RefundCandidateGroup(refund, tuple(ranked[:candidates_per_refund]), len(ranked)))
    groups.sort(key=lambda group: (-group.candidates[0].match_confidence, group.refund_transaction.id))
    return groups[:limit]


def list_refund_suggestion_groups(db: Session) -> list[dict]:
    open_refund_ids = {
        link.refund_transaction_id
        for link in db.scalars(select(RefundLink).where(RefundLink.confirmed.is_(False))).all()
    }
    if not open_refund_ids:
        return []
    groups = detect_refund_candidate_groups(db, refund_ids=open_refund_ids)
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    confirmed_refunds_by_expense = _confirmed_refunds_by_expense(db)

    results = []
    for group in groups:
        candidate_payloads = []
        for candidate in group.candidates:
            expense = candidate.expense_transaction
            existing_refunds = confirmed_refunds_by_expense.get(expense.id, [])
            existing_total = sum(item.refund_transaction.amount_cents for item in existing_refunds)
            linked_total = existing_total + group.refund_transaction.amount_cents
            candidate_payloads.append({
                "expense_transaction": _transaction_payload(db, expense, accounts),
                "match_confidence": candidate.match_confidence,
                "match_reasons": _match_reasons(expense, group.refund_transaction, accounts),
                "expense_amount_cents": abs(expense.amount_cents),
                "existing_linked_refund_cents": existing_total,
                "remaining_refundable_cents": max(0, abs(expense.amount_cents) - existing_total),
                "linked_refund_cents": linked_total,
                "existing_linked_refunds": [
                    _transaction_payload(db, item.refund_transaction, accounts)
                    for item in existing_refunds
                ],
                "would_exceed_expense": linked_total > abs(expense.amount_cents),
            })
        results.append({
            "refund_transaction": _transaction_payload(db, group.refund_transaction, accounts),
            "candidates": candidate_payloads,
            "candidate_count": group.candidate_count,
            "limited_candidates": group.candidate_count > len(candidate_payloads),
        })
    return results


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
        current_score = score_refund_match(expense, refund, accounts) if confirmed is False else None
        if confirmed is False and current_score is None:
            continue
        payload = refund_link_payload(db, link, expense, refund)
        if current_score is not None:
            payload["match_confidence"] = current_score
        results.append(payload)
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


def confirm_refund_selections(
    db: Session,
    *,
    selections: list[tuple[int, int]],
    allow_over_refund: bool = False,
    actor: str = "local-user",
) -> dict:
    if not selections:
        raise ValueError("Select at least one refund match")
    refund_ids = [refund_id for refund_id, _ in selections]
    if len(set(refund_ids)) != len(refund_ids):
        raise ValueError("Choose only one expense for each refund")

    transaction_ids = set(refund_ids) | {expense_id for _, expense_id in selections}
    transactions = {
        row.id: row for row in db.scalars(live_transaction_select(Transaction.id.in_(transaction_ids))).all()
    }
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    transfer_ids = _confirmed_transfer_transaction_ids(db)
    existing_links = {
        link.refund_transaction_id: link
        for link in db.scalars(select(RefundLink).where(RefundLink.refund_transaction_id.in_(refund_ids))).all()
    }
    selected: list[tuple[Transaction, Transaction, RefundLink | None, int]] = []
    pending_total_by_expense: dict[int, int] = {}
    for refund_id, expense_id in selections:
        refund = transactions.get(refund_id)
        expense = transactions.get(expense_id)
        if not refund or not expense:
            raise ValueError("A selected refund or expense is no longer available")
        if expense.amount_cents >= 0 or refund.amount_cents <= 0:
            raise ValueError("Refund links require a money-out expense and a money-in refund")
        if expense.id in transfer_ids or refund.id in transfer_ids:
            raise ValueError("A confirmed transfer/payment already uses one of these transactions")
        existing_link = existing_links.get(refund.id)
        if existing_link and existing_link.confirmed:
            raise ValueError("One of the selected refunds is already linked")
        score = score_refund_match(expense, refund, accounts, allow_over_amount=True)
        if score is None:
            raise ValueError("One of the selected refund matches is no longer plausible")
        selected.append((refund, expense, existing_link, score))
        pending_total_by_expense[expense.id] = pending_total_by_expense.get(expense.id, 0) + refund.amount_cents

    for expense_id, pending_total in pending_total_by_expense.items():
        existing_total = sum(item.refund_transaction.amount_cents for item in _confirmed_links_with_refunds(db, expense_id))
        expense = transactions[expense_id]
        linked_total = existing_total + pending_total
        if linked_total > abs(expense.amount_cents) and not allow_over_refund:
            raise OverRefundError(expense_cents=abs(expense.amount_cents), linked_refund_cents=linked_total)

    changes: list[MutationChange] = []
    link_ids: list[int] = []
    for refund, expense, existing_link, score in selected:
        link_before = full_values(existing_link) if existing_link else None
        link = existing_link or RefundLink(refund_transaction_id=refund.id, confirmed=False)
        link.expense_transaction_id = expense.id
        link.match_confidence = score
        link.confirmed = True
        if not existing_link:
            db.add(link)
        db.flush()
        link_ids.append(link.id)
        changes.append(MutationChange(link.id, link_before, full_values(link), entity_type="refund_link"))

        refund_before = changed_values(refund, ["transaction_type", "review_status", "category_id"])
        refund.transaction_type = "refund"
        refund.review_status = "confirmed"
        refund.category_id = expense.category_id
        changes.append(MutationChange(refund.id, refund_before, changed_values(refund, ["transaction_type", "review_status", "category_id"]), entity_type="transaction"))

        rejected = db.scalar(select(RefundPairDecision).where(
            RefundPairDecision.refund_transaction_id == refund.id,
            RefundPairDecision.expense_transaction_id == expense.id,
        ))
        if rejected:
            changes.append(MutationChange(rejected.id, full_values(rejected), None, entity_type="refund_pair_decision"))
            db.delete(rejected)
        resolution = db.scalar(select(RefundReviewResolution).where(RefundReviewResolution.refund_transaction_id == refund.id))
        if resolution:
            changes.append(MutationChange(resolution.id, full_values(resolution), None, entity_type="refund_review_resolution"))
            db.delete(resolution)
        record_audit_event(db, "refund_confirm", actor, "refund_link", str(link.id), {
            "expense_transaction_id": expense.id,
            "refund_transaction_id": refund.id,
            "bulk": len(selected) > 1,
        })

    operation_id = journal_mutation(
        db,
        kind="update",
        entity_type="mixed",
        actor=actor,
        description=f"Confirmed {len(selected)} refund match{'es' if len(selected) != 1 else ''}",
        changes=changes,
    )
    db.commit()
    return {"confirmed": len(selected), "link_ids": link_ids, "operation_id": operation_id}


def reject_refund_candidates(db: Session, *, selections: list[tuple[int, int]], actor: str = "local-user") -> dict:
    if not selections:
        raise ValueError("Select at least one refund candidate")
    changes: list[MutationChange] = []
    rejected = 0
    open_links_to_replace: dict[int, RefundLink] = {}
    for refund_id, expense_id in dict.fromkeys(selections):
        refund = get_live_transaction(db, refund_id)
        expense = get_live_transaction(db, expense_id)
        if not refund or not expense:
            raise ValueError("A selected refund or expense is no longer available")
        decision = db.scalar(select(RefundPairDecision).where(
            RefundPairDecision.refund_transaction_id == refund_id,
            RefundPairDecision.expense_transaction_id == expense_id,
        ))
        if not decision:
            decision = RefundPairDecision(refund_transaction_id=refund_id, expense_transaction_id=expense_id, decision="rejected")
            db.add(decision)
            db.flush()
            changes.append(MutationChange(decision.id, None, full_values(decision), entity_type="refund_pair_decision"))
            rejected += 1
        open_link = db.scalar(select(RefundLink).where(
            RefundLink.refund_transaction_id == refund_id,
            RefundLink.expense_transaction_id == expense_id,
            RefundLink.confirmed.is_(False),
        ))
        if open_link:
            open_links_to_replace[refund_id] = open_link
        record_audit_event(db, "refund_candidate_reject", actor, "transaction", str(refund_id), {"expense_transaction_id": expense_id})
    if open_links_to_replace:
        replacement_groups = {
            group.refund_transaction.id: group
            for group in detect_refund_candidate_groups(db, refund_ids=set(open_links_to_replace), limit=len(open_links_to_replace))
        }
        for refund_id, open_link in open_links_to_replace.items():
            link_before = full_values(open_link)
            replacement = replacement_groups.get(refund_id)
            if replacement:
                next_candidate = replacement.candidates[0]
                open_link.expense_transaction_id = next_candidate.expense_transaction.id
                open_link.match_confidence = next_candidate.match_confidence
                changes.append(MutationChange(open_link.id, link_before, full_values(open_link), entity_type="refund_link"))
            else:
                changes.append(MutationChange(open_link.id, link_before, None, entity_type="refund_link"))
                db.delete(open_link)
    operation_id = journal_mutation(
        db,
        kind="update",
        entity_type="mixed",
        actor=actor,
        description=f"Rejected {len(selections)} refund candidate{'s' if len(selections) != 1 else ''}",
        changes=changes,
    ) if changes else None
    db.commit()
    return {"rejected": rejected, "operation_id": operation_id}


def resolve_refunds_without_expense(db: Session, *, refund_ids: list[int], actor: str = "local-user") -> dict:
    unique_ids = list(dict.fromkeys(refund_ids))
    if not unique_ids:
        raise ValueError("Select at least one refund")
    refunds = {row.id: row for row in db.scalars(live_transaction_select(Transaction.id.in_(unique_ids))).all()}
    if len(refunds) != len(unique_ids):
        raise ValueError("One of the selected refunds is no longer available")
    uncategorized = [row.id for row in refunds.values() if row.category_id is None]
    if uncategorized:
        raise ValueError("Choose a category before marking a refund as having no expense in the ledger")

    changes: list[MutationChange] = []
    resolved = 0
    for refund_id in unique_ids:
        refund = refunds[refund_id]
        if refund.amount_cents <= 0:
            raise ValueError("Only money-in transactions can be settled as unlinked refunds")
        existing_resolution = db.scalar(select(RefundReviewResolution).where(RefundReviewResolution.refund_transaction_id == refund_id))
        if not existing_resolution:
            resolution = RefundReviewResolution(refund_transaction_id=refund_id, resolution="no_expense")
            db.add(resolution)
            db.flush()
            changes.append(MutationChange(resolution.id, None, full_values(resolution), entity_type="refund_review_resolution"))
            resolved += 1
        refund_before = changed_values(refund, ["transaction_type", "review_status"])
        refund.transaction_type = "refund"
        refund.review_status = "confirmed"
        changes.append(MutationChange(refund.id, refund_before, changed_values(refund, ["transaction_type", "review_status"]), entity_type="transaction"))
        open_link = db.scalar(select(RefundLink).where(RefundLink.refund_transaction_id == refund_id, RefundLink.confirmed.is_(False)))
        if open_link:
            changes.append(MutationChange(open_link.id, full_values(open_link), None, entity_type="refund_link"))
            db.delete(open_link)
        record_audit_event(db, "refund_no_expense", actor, "transaction", str(refund_id), {})
    operation_id = journal_mutation(
        db,
        kind="update",
        entity_type="mixed",
        actor=actor,
        description=f"Settled {len(unique_ids)} unlinked refund{'s' if len(unique_ids) != 1 else ''}",
        changes=changes,
    ) if changes else None
    db.commit()
    return {"resolved": resolved, "operation_id": operation_id}


def reject_refund_link(db: Session, link: RefundLink, actor: str = "local-user") -> dict:
    link_id = link.id
    result = reject_refund_candidates(
        db,
        selections=[(link.refund_transaction_id, link.expense_transaction_id)],
        actor=actor,
    )
    return {"id": link_id, "rejected": True, **result}


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
    existing_refunds = _confirmed_links_with_refunds(db, expense.id, exclude_link_id=None if not link.confirmed else link.id)
    account_ids = {expense.account_id, refund.account_id} | {item.refund_transaction.account_id for item in existing_refunds}
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()}
    existing_total = sum(item.refund_transaction.amount_cents for item in existing_refunds)
    confirmed_total = existing_total + refund.amount_cents
    return {
        "id": link.id,
        "expense_transaction": _transaction_payload(db, expense, accounts),
        "refund_transaction": _transaction_payload(db, refund, accounts),
        "match_confidence": link.match_confidence,
        "confirmed": link.confirmed,
        "expense_amount_cents": abs(expense.amount_cents),
        "existing_linked_refund_cents": existing_total,
        "remaining_refundable_cents": max(0, abs(expense.amount_cents) - existing_total),
        "linked_refund_cents": confirmed_total,
        "existing_linked_refunds": [
            _transaction_payload(db, item.refund_transaction, accounts)
            for item in existing_refunds
        ],
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
    refunds = {
        row.id: row
        for row in db.scalars(live_transaction_select(Transaction.id.in_([link.refund_transaction_id for link in links]))).all()
    } if links else {}
    return [_LinkWithRefund(link, refunds[link.refund_transaction_id]) for link in links if link.refund_transaction_id in refunds]


def _confirmed_refunds_by_expense(db: Session) -> dict[int, list[_LinkWithRefund]]:
    links = db.scalars(select(RefundLink).where(RefundLink.confirmed.is_(True))).all()
    if not links:
        return {}
    refund_ids = {link.refund_transaction_id for link in links}
    refunds = {
        row.id: row
        for row in db.scalars(live_transaction_select(Transaction.id.in_(refund_ids))).all()
    }
    results: dict[int, list[_LinkWithRefund]] = {}
    for link in links:
        refund = refunds.get(link.refund_transaction_id)
        if refund:
            results.setdefault(link.expense_transaction_id, []).append(_LinkWithRefund(link, refund))
    return results


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


def _description_tokens(transaction: Transaction, account: Account | None = None) -> set[str]:
    if account and _is_venmo(account, transaction):
        text = f"{_venmo_memo_text(transaction.raw_description)} {transaction.user_note or ''}".casefold()
    else:
        text = f"{transaction.raw_description} {transaction.normalized_payee or ''} {transaction.user_note or ''}".casefold()
    return {token for token in re.findall(r"[a-z0-9]+", text) if len(token) >= 3 and token not in TOKEN_STOPWORDS and not token.isdigit()}


def _venmo_memo_text(description: str) -> str:
    # Current Venmo imports store "memo | payer paid recipient". Historical
    # imports used "payer [request/payment] to recipient memo" instead.
    if "|" in description:
        return description.split("|", 1)[0].strip()
    words = list(re.finditer(r"[A-Za-z0-9']+", description))
    lowered = [match.group(0).casefold() for match in words]
    try:
        to_index = lowered.index("to")
    except ValueError:
        return description
    if to_index not in {2, 3}:
        return description

    recipient_length = 2
    self_tokens = re.findall(r"[a-z0-9']+", (settings.venmo_self_name or "").casefold())
    after_to = lowered[to_index + 1:]
    if self_tokens and after_to[:len(self_tokens)] == self_tokens:
        recipient_length = len(self_tokens)
    memo_index = to_index + 1 + recipient_length
    return description[words[memo_index].start():].strip() if memo_index < len(words) else ""


def _amount_match_score(expense: Transaction, refund: Transaction) -> int:
    expense_amount = abs(expense.amount_cents)
    if refund.amount_cents == expense_amount:
        return 30
    ratio = refund.amount_cents / expense_amount
    if ratio >= 0.9:
        return 12
    if ratio >= 0.5:
        return 8
    if ratio >= 0.25:
        return 4
    return 0


def _match_reasons(expense: Transaction, refund: Transaction, accounts: dict[int, Account]) -> list[str]:
    expense_account = accounts.get(expense.account_id)
    refund_account = accounts.get(refund.account_id)
    reasons: list[str] = []
    if refund.amount_cents == abs(expense.amount_cents):
        reasons.append("Exact amount")
    else:
        reasons.append("Possible partial refund")
    day_gap = (refund.transaction_date - expense.transaction_date).days
    reasons.append(f"{day_gap} day{'s' if day_gap != 1 else ''} apart")
    if expense_account and refund_account:
        overlap = len(_description_tokens(expense, expense_account) & _description_tokens(refund, refund_account))
        if overlap:
            reasons.append(f"{overlap} description term{'s' if overlap != 1 else ''} match")
        if expense_account.account_type == "credit_card" and _is_venmo(refund_account, refund):
            reasons.append("Venmo to credit card")
    if expense.category_id is not None and expense.category_id == refund.category_id:
        reasons.append("Category matches")
    elif expense.category_id is not None and refund.category_id is not None:
        reasons.append("Category differs")
    return reasons


def _recency_score(day_gap: int) -> int:
    if day_gap <= 7:
        return 15
    if day_gap <= 14:
        return 12
    if day_gap <= 30:
        return 8
    if day_gap <= 60:
        return 4
    return 1


def _recent_expense_ids(expenses: list[Transaction], dates: list[date], refund_date: date, *, limit: int) -> set[int]:
    if not expenses:
        return set()
    start = bisect_left(dates, refund_date - timedelta(days=REFUND_WINDOW_DAYS))
    end = bisect_right(dates, refund_date)
    return {row.id for row in expenses[max(start, end - limit):end]}


def _has_explicit_refund_signal(transaction: Transaction) -> bool:
    description = f"{transaction.raw_description} {transaction.user_note or ''}".upper()
    return _contains_term(description, REFUND_TERMS)


def _is_payment_like(transaction: Transaction, account: Account | None = None) -> bool:
    if transaction.transaction_type in NON_REFUND_TYPES:
        return True
    if _has_explicit_refund_signal(transaction):
        return False
    if account and _is_venmo(account, transaction):
        return False
    description = f"{transaction.raw_description} {transaction.user_note or ''}".upper()
    return _contains_term(description, PAYMENT_TERMS)


def _contains_term(description: str, terms: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<![A-Z0-9]){re.escape(term)}(?![A-Z0-9])", description) for term in terms)


def _is_venmo(account: Account, _transaction: Transaction) -> bool:
    # Account identity controls Venmo behavior. A card merchant description can
    # itself contain "VENMO" without making that credit-card account a P2P wallet.
    return "venmo" in account.display_name.casefold()


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
