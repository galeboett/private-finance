from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..models import Account, Category, ImportBatch, Transaction
from .mutation_log import MutationChange, changed_values, journal_mutation


COMPARED_FIELDS = ("account", "reference", "date", "amount", "description", "category", "notes", "labels", "import_source")
BANK_FIELDS = ("transaction_date", "posted_date", "amount_cents", "currency", "raw_description", "normalized_payee", "source_reference", "running_balance_cents")


def pending_duplicate_pairs(db: Session) -> list[dict[str, Any]]:
    candidates = db.scalars(
        select(Transaction).where(
            Transaction.deleted_at.is_(None),
            Transaction.status == "active",
            Transaction.review_status == "possible_duplicate",
            Transaction.duplicate_of_transaction_id.is_not(None),
        ).order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
    ).all()
    if not candidates:
        return []
    original_ids = {candidate.duplicate_of_transaction_id for candidate in candidates if candidate.duplicate_of_transaction_id is not None}
    originals = {
        transaction.id: transaction
        for transaction in db.scalars(
            select(Transaction).where(
                Transaction.id.in_(original_ids),
                Transaction.deleted_at.is_(None),
                Transaction.status == "active",
            )
        ).all()
    }
    account_ids = {candidate.account_id for candidate in candidates} | {row.account_id for row in originals.values()}
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()}
    category_ids = {row.category_id for row in [*candidates, *originals.values()] if row.category_id is not None}
    categories = {category.id: category for category in db.scalars(select(Category).where(Category.id.in_(category_ids))).all()} if category_ids else {}
    batch_ids = {row.import_batch_id for row in [*candidates, *originals.values()] if row.import_batch_id is not None}
    batches = {batch.id: batch for batch in db.scalars(select(ImportBatch).where(ImportBatch.id.in_(batch_ids))).all()} if batch_ids else {}
    results: list[dict[str, Any]] = []
    for candidate in candidates:
        original = originals.get(candidate.duplicate_of_transaction_id)
        if original is None:
            continue
        candidate_payload = _transaction_payload(candidate, accounts, categories, batches)
        original_payload = _transaction_payload(original, accounts, categories, batches)
        diff_fields = [field for field in COMPARED_FIELDS if candidate_payload[field] != original_payload[field]]
        results.append({"candidate": candidate_payload, "original": original_payload, "diff_fields": diff_fields, "exact_match": not diff_fields})
    return results


def resolve_duplicate(db: Session, *, transaction_id: int, action: str, actor: str) -> dict[str, Any]:
    candidate, original = _duplicate_pair(db, transaction_id)
    changes: list[MutationChange] = []
    if action == "remove_new":
        before = changed_values(candidate, ["deleted_at"])
        candidate.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        changes.append(MutationChange(candidate.id, before, changed_values(candidate, ["deleted_at"])))
        description = f'Removed duplicate "{candidate.raw_description}"'
    elif action == "keep_both":
        fields = ["duplicate_of_transaction_id", "review_status"]
        before = changed_values(candidate, fields)
        candidate.duplicate_of_transaction_id = None
        candidate.review_status = "needs_review"
        changes.append(MutationChange(candidate.id, before, changed_values(candidate, fields)))
        description = f'Kept both copies of "{candidate.raw_description}"'
    elif action == "replace_old":
        original_before = changed_values(original, BANK_FIELDS)
        for field in BANK_FIELDS:
            setattr(original, field, getattr(candidate, field))
        changes.append(MutationChange(original.id, original_before, changed_values(original, BANK_FIELDS)))
        candidate_before = changed_values(candidate, ["deleted_at"])
        candidate.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        changes.append(MutationChange(candidate.id, candidate_before, changed_values(candidate, ["deleted_at"])))
        description = f'Replaced bank fields on "{original.raw_description}" with the newer import'
    else:
        raise ValueError("Choose remove_new, keep_both, or replace_old")
    operation_id = journal_mutation(db, kind="resolve_duplicate", entity_type="transaction", actor=actor, description=description, changes=changes)
    record_audit_event(db, "duplicate_resolve", actor, "transaction", str(candidate.id), {"action": action, "original_transaction_id": original.id, "operation_id": operation_id})
    return {"ok": True, "action": action, "transaction_id": candidate.id, "original_transaction_id": original.id, "operation_id": operation_id}


def resolve_all_exact_duplicates(db: Session, *, actor: str) -> dict[str, Any]:
    exact_ids = [pair["candidate"]["id"] for pair in pending_duplicate_pairs(db) if pair["exact_match"]]
    if not exact_ids:
        return {"ok": True, "resolved": 0, "operation_id": None}
    deleted_at = datetime.now(UTC).replace(tzinfo=None)
    changes: list[MutationChange] = []
    for transaction_id in exact_ids:
        candidate, _ = _duplicate_pair(db, transaction_id)
        before = changed_values(candidate, ["deleted_at"])
        candidate.deleted_at = deleted_at
        changes.append(MutationChange(candidate.id, before, changed_values(candidate, ["deleted_at"])))
    operation_id = journal_mutation(
        db,
        kind="resolve_duplicates",
        entity_type="transaction",
        actor=actor,
        description=f"Removed {len(changes)} exact duplicate imports",
        changes=changes,
    )
    record_audit_event(db, "duplicates_resolve_exact", actor, "transactions", f"bulk:{len(changes)}", {"transaction_ids": exact_ids, "operation_id": operation_id})
    return {"ok": True, "resolved": len(changes), "operation_id": operation_id}


def _duplicate_pair(db: Session, transaction_id: int) -> tuple[Transaction, Transaction]:
    candidate = db.get(Transaction, transaction_id)
    if not candidate or candidate.deleted_at is not None or candidate.status != "active":
        raise LookupError("Duplicate candidate not found")
    if candidate.review_status != "possible_duplicate" or candidate.duplicate_of_transaction_id is None:
        raise ValueError("This transaction is not waiting for duplicate review")
    original = db.get(Transaction, candidate.duplicate_of_transaction_id)
    if not original or original.deleted_at is not None or original.status != "active":
        raise ValueError("The matched original transaction is no longer available")
    return candidate, original


def _transaction_payload(
    transaction: Transaction,
    accounts: dict[int, Account],
    categories: dict[int, Category],
    batches: dict[int, ImportBatch],
) -> dict[str, Any]:
    account = accounts.get(transaction.account_id)
    category = categories.get(transaction.category_id) if transaction.category_id is not None else None
    batch = batches.get(transaction.import_batch_id) if transaction.import_batch_id is not None else None
    account_label = account.display_name if account else "Unknown account"
    institution = account.institution.name if account and account.institution else None
    return {
        "id": transaction.id,
        "account_id": transaction.account_id,
        "account": account_label,
        "institution": institution,
        "account_last_four": account.last_four if account else None,
        "reference": transaction.source_reference,
        "date": transaction.transaction_date.isoformat(),
        "posted_date": transaction.posted_date.isoformat() if transaction.posted_date else None,
        "amount": transaction.amount_cents,
        "amount_cents": transaction.amount_cents,
        "description": transaction.raw_description,
        "category_id": transaction.category_id,
        "category": category.label if category else None,
        "notes": transaction.user_note,
        "labels": transaction.labels,
        "import_source": batch.filename if batch else "Manual entry",
    }
