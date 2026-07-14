from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, Transaction, TransferLink
from .mutation_log import MutationChange, changed_values, full_values, journal_mutation
from .transaction_queries import get_live_transaction, live_transaction_select


TRANSFER_MATCH_STATUSES = {"needs_review", "suggested", "possible_duplicate", "confirmed"}
LONG_WINDOW_ACCOUNT_TYPES = {"brokerage", "retirement"}


@dataclass(frozen=True)
class TransferCandidate:
    from_transaction: Transaction
    to_transaction: Transaction
    match_confidence: int
    suggested_type: str


def score_transfer_match(left: Transaction, right: Transaction, accounts: dict[int, Account], window_days: int = 5) -> tuple[int, str] | None:
    if (left.id is not None and left.id == right.id) or left.account_id == right.account_id:
        return None
    if left.amount_cents == 0 or left.amount_cents + right.amount_cents != 0:
        return None
    account_types = {accounts.get(left.account_id).account_type if accounts.get(left.account_id) else "", accounts.get(right.account_id).account_type if accounts.get(right.account_id) else ""}
    effective_window = max(window_days, 7) if account_types & LONG_WINDOW_ACCOUNT_TYPES else window_days
    day_gap = abs((left.transaction_date - right.transaction_date).days)
    if day_gap > effective_window:
        return None
    suggested_type = "credit_card_payment" if "credit_card" in account_types else "transfer"
    descriptions = f"{left.raw_description} {right.raw_description}".upper()
    confidence = max(50, 95 - (day_gap * 8))
    if suggested_type == "credit_card_payment" and any(term in descriptions for term in ("PAYMENT", "AUTOPAY", "CARD")):
        confidence += 8
    if suggested_type == "transfer" and any(term in descriptions for term in ("TRANSFER", "XFER", "ACH")):
        confidence += 8
    return min(confidence, 100), suggested_type


def detect_transfer_candidates(db: Session, window_days: int = 5) -> list[TransferCandidate]:
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.status == "active")).all()}
    linked_transaction_ids = _linked_transaction_ids(db)
    rows = db.scalars(
        live_transaction_select(
            Transaction.review_status.in_(list(TRANSFER_MATCH_STATUSES)),
        )
        .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
    ).all()
    candidates: list[TransferCandidate] = []
    used_transaction_ids: set[int] = set()
    negatives = [row for row in rows if row.amount_cents < 0 and row.id not in linked_transaction_ids]
    positives = [row for row in rows if row.amount_cents > 0 and row.id not in linked_transaction_ids]

    for negative in negatives:
        if negative.id in used_transaction_ids:
            continue
        best: TransferCandidate | None = None
        for positive in positives:
            if positive.id in used_transaction_ids:
                continue
            scored = score_transfer_match(negative, positive, accounts, window_days)
            if not scored:
                continue
            confidence, suggested_type = scored
            candidate = TransferCandidate(negative, positive, confidence, suggested_type)
            if best is None or candidate.match_confidence > best.match_confidence:
                best = candidate
        if best:
            candidates.append(best)
            used_transaction_ids.update({best.from_transaction.id, best.to_transaction.id})
    return candidates


def create_transfer_suggestions(db: Session, window_days: int = 5, actor: str = "local-user") -> dict:
    created = 0
    suggestions = []
    changes: list[MutationChange] = []
    for candidate in detect_transfer_candidates(db, window_days):
        from_before = changed_values(candidate.from_transaction, ["review_status"])
        to_before = changed_values(candidate.to_transaction, ["review_status"])
        link = TransferLink(
            from_transaction_id=candidate.from_transaction.id,
            to_transaction_id=candidate.to_transaction.id,
            match_confidence=candidate.match_confidence,
            confirmed=False,
        )
        db.add(link)
        if candidate.from_transaction.review_status != "confirmed":
            candidate.from_transaction.review_status = "suggested"
        if candidate.to_transaction.review_status != "confirmed":
            candidate.to_transaction.review_status = "suggested"
        db.flush()
        changes.extend([
            MutationChange(link.id, None, full_values(link), entity_type="transfer_link"),
            MutationChange(candidate.from_transaction.id, from_before, changed_values(candidate.from_transaction, ["review_status"]), entity_type="transaction"),
            MutationChange(candidate.to_transaction.id, to_before, changed_values(candidate.to_transaction, ["review_status"]), entity_type="transaction"),
        ])
        record_audit_event(
            db,
            "transfer_suggest",
            actor,
            "transfer_link",
            str(link.id),
            {
                "from_transaction_id": candidate.from_transaction.id,
                "to_transaction_id": candidate.to_transaction.id,
                "match_confidence": candidate.match_confidence,
                "suggested_type": candidate.suggested_type,
            },
        )
        suggestions.append(_transfer_link_payload(link, candidate.from_transaction, candidate.to_transaction, candidate.suggested_type))
        created += 1
    operation_id = journal_mutation(db, kind="create", entity_type="mixed", actor=actor, description=f"Created {created} transfer suggestions", changes=changes) if changes else None
    db.commit()
    return {"created": created, "suggestions": suggestions, "operation_id": operation_id}


def list_unconfirmed_transfers(db: Session) -> list[dict]:
    links = db.scalars(select(TransferLink).where(TransferLink.confirmed.is_(False)).order_by(TransferLink.match_confidence.desc(), TransferLink.id.desc())).all()
    transaction_ids = {link.from_transaction_id for link in links} | {link.to_transaction_id for link in links}
    transactions = {row.id: row for row in db.scalars(live_transaction_select(Transaction.id.in_(transaction_ids))).all()} if transaction_ids else {}
    results = []
    for link in links:
        from_transaction = transactions.get(link.from_transaction_id)
        to_transaction = transactions.get(link.to_transaction_id)
        if not from_transaction or not to_transaction or from_transaction.status != "active" or to_transaction.status != "active":
            continue
        results.append(_transfer_link_payload(link, from_transaction, to_transaction, _suggested_type(from_transaction, to_transaction, db)))
    return results


def list_payment_verification(db: Session, as_of: date | None = None) -> list[dict]:
    as_of = as_of or date.today()
    cards = db.scalars(select(Account).where(Account.status == "active", Account.account_type == "credit_card").order_by(Account.display_name, Account.id)).all()
    confirmed_links = db.scalars(select(TransferLink).where(TransferLink.confirmed.is_(True))).all()
    linked_ids = {link.from_transaction_id for link in confirmed_links} | {link.to_transaction_id for link in confirmed_links}
    linked_transactions = {
        transaction.id: transaction
        for transaction in db.scalars(live_transaction_select(Transaction.id.in_(linked_ids))).all()
    } if linked_ids else {}
    account_ids = {transaction.account_id for transaction in linked_transactions.values()}
    account_types = {account.id: account.account_type for account in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()} if account_ids else {}
    results: list[dict] = []
    stale_before = as_of - timedelta(days=5)
    for card in cards:
        matched_dates: list[date] = []
        matched_count = 0
        for link in confirmed_links:
            left = linked_transactions.get(link.from_transaction_id)
            right = linked_transactions.get(link.to_transaction_id)
            if not left or not right:
                continue
            card_transaction = left if left.account_id == card.id else right if right.account_id == card.id else None
            other_transaction = right if card_transaction is left else left if card_transaction is right else None
            if card_transaction and other_transaction and card_transaction.amount_cents > 0 and other_transaction.amount_cents < 0 and account_types.get(other_transaction.account_id) in {"checking", "savings", "cash"}:
                matched_count += 1
                matched_dates.append(max(card_transaction.transaction_date, other_transaction.transaction_date))
        possible_payments = db.scalars(
            live_transaction_select(
                Transaction.account_id == card.id,
                Transaction.amount_cents > 0,
                Transaction.transaction_date <= stale_before,
            ).order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
        ).all()
        warnings = [
            {
                "transaction_id": transaction.id,
                "transaction_date": transaction.transaction_date.isoformat(),
                "amount_cents": transaction.amount_cents,
                "description": transaction.raw_description,
                "age_days": (as_of - transaction.transaction_date).days,
            }
            for transaction in possible_payments
            if transaction.id not in linked_ids and _looks_like_card_payment(transaction)
        ]
        results.append({
            "account_id": card.id,
            "account_name": card.display_name,
            "matched_payments": matched_count,
            "latest_matched_date": max(matched_dates).isoformat() if matched_dates else None,
            "warnings": warnings,
        })
    return results


def confirm_transfer_link(db: Session, link: TransferLink, actor: str = "local-user") -> dict:
    from_transaction = get_live_transaction(db, link.from_transaction_id)
    to_transaction = get_live_transaction(db, link.to_transaction_id)
    if not from_transaction or not to_transaction:
        raise ValueError("Transfer link points to a missing transaction")
    suggested_type = _suggested_type(from_transaction, to_transaction, db)
    link_before = changed_values(link, ["confirmed"])
    from_before = changed_values(from_transaction, ["transaction_type", "review_status", "category_id"])
    to_before = changed_values(to_transaction, ["transaction_type", "review_status", "category_id"])
    link.confirmed = True
    from_transaction.transaction_type = suggested_type
    to_transaction.transaction_type = suggested_type
    from_transaction.review_status = "confirmed"
    to_transaction.review_status = "confirmed"
    from_transaction.category_id = None
    to_transaction.category_id = None
    operation_id = journal_mutation(db, kind="update", entity_type="mixed", actor=actor, description="Confirmed transfer pair", changes=[
        MutationChange(link.id, link_before, changed_values(link, ["confirmed"]), entity_type="transfer_link"),
        MutationChange(from_transaction.id, from_before, changed_values(from_transaction, ["transaction_type", "review_status", "category_id"]), entity_type="transaction"),
        MutationChange(to_transaction.id, to_before, changed_values(to_transaction, ["transaction_type", "review_status", "category_id"]), entity_type="transaction"),
    ])
    record_audit_event(
        db,
        "transfer_confirm",
        actor,
        "transfer_link",
        str(link.id),
        {"from_transaction_id": from_transaction.id, "to_transaction_id": to_transaction.id, "suggested_type": suggested_type},
    )
    db.commit()
    return {**_transfer_link_payload(link, from_transaction, to_transaction, suggested_type), "operation_id": operation_id}


def reject_transfer_link(db: Session, link: TransferLink, actor: str = "local-user") -> dict:
    link_id = link.id
    from_transaction = get_live_transaction(db, link.from_transaction_id)
    to_transaction = get_live_transaction(db, link.to_transaction_id)
    changes = [MutationChange(link.id, full_values(link), None, entity_type="transfer_link")]
    for transaction in (from_transaction, to_transaction):
        if transaction and transaction.review_status == "suggested":
            before = changed_values(transaction, ["review_status"])
            transaction.review_status = "needs_review"
            changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["review_status"]), entity_type="transaction"))
    operation_id = journal_mutation(db, kind="delete", entity_type="mixed", actor=actor, description="Rejected transfer suggestion", changes=changes)
    record_audit_event(db, "transfer_reject", actor, "transfer_link", str(link_id), {"from_transaction_id": link.from_transaction_id, "to_transaction_id": link.to_transaction_id})
    db.delete(link)
    db.commit()
    return {"id": link_id, "rejected": True, "operation_id": operation_id}


def _linked_transaction_ids(db: Session) -> set[int]:
    ids: set[int] = set()
    for link in db.scalars(select(TransferLink)).all():
        ids.add(link.from_transaction_id)
        ids.add(link.to_transaction_id)
    return ids


def _suggested_type(from_transaction: Transaction, to_transaction: Transaction, db: Session) -> str:
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.id.in_([from_transaction.account_id, to_transaction.account_id]))).all()}
    scored = score_transfer_match(from_transaction, to_transaction, accounts, window_days=3650)
    if scored:
        return scored[1]
    return "transfer"


def _transfer_link_payload(link: TransferLink, from_transaction: Transaction, to_transaction: Transaction, suggested_type: str) -> dict:
    return {
        "id": link.id,
        "from_transaction": _transaction_payload(from_transaction),
        "to_transaction": _transaction_payload(to_transaction),
        "match_confidence": link.match_confidence,
        "confirmed": link.confirmed,
        "suggested_type": suggested_type,
    }


def _transaction_payload(transaction: Transaction) -> dict:
    return {
        "id": transaction.id,
        "account_id": transaction.account_id,
        "transaction_date": transaction.transaction_date.isoformat() if isinstance(transaction.transaction_date, date) else transaction.transaction_date,
        "amount_cents": transaction.amount_cents,
        "raw_description": transaction.raw_description,
        "transaction_type": transaction.transaction_type,
        "review_status": transaction.review_status,
    }


def _looks_like_card_payment(transaction: Transaction) -> bool:
    description = transaction.raw_description.upper()
    return transaction.transaction_type == "credit_card_payment" or "PAYMENT" in description or "AUTOPAY" in description
