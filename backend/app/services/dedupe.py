from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import ImportBatch, Transaction


RELIABLE_REFERENCE_PRESETS = {"card_reference", "venmo_activity"}
HISTORY_REFERENCE_PREFIX = "categorized-history-row-"


def is_categorized_history_reference(reference: str | None) -> bool:
    return bool(reference and reference.startswith(HISTORY_REFERENCE_PREFIX))


def is_reliable_import_reference(preset_type: str | None, reference: str | None) -> bool:
    return bool(reference and reference.strip() and preset_type in RELIABLE_REFERENCE_PRESETS)


def is_intrinsically_reliable_reference(reference: str | None) -> bool:
    """Recognize issuer-generated numeric IDs after their import batch is gone."""
    cleaned = (reference or "").strip()
    return len(cleaned) >= 8 and cleaned.isdigit()


def normalize_transaction_description(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def canonical_source_hash(
    transaction_date: date,
    amount_cents: int,
    description: str,
    source_reference: str | None,
    ordinal: int,
) -> str:
    """Build an account-independent fingerprint from normalized persisted values.

    Account identity already participates in the database uniqueness constraint, so
    embedding a mutable internal account ID inside the hash makes account merges
    unsafe. The version marker allows future fingerprint formats to coexist.
    """
    payload = "|".join(
        [
            "transaction-v2",
            transaction_date.isoformat(),
            str(amount_cents),
            normalize_transaction_description(description),
            (source_reference or "").strip(),
            str(ordinal),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_reference_matches(
    db: Session,
    *,
    account_id: int,
    reference: str,
    transaction_date: date,
    amount_cents: int,
) -> tuple[Transaction | None, Transaction | None]:
    rows = db.scalars(
        select(Transaction)
        .where(
            Transaction.account_id == account_id,
            Transaction.source_reference == reference,
        )
        .order_by(Transaction.deleted_at.is_(None).desc(), Transaction.id.asc())
    ).all()
    exact = next(
        (
            row
            for row in rows
            if row.transaction_date == transaction_date and row.amount_cents == amount_cents
        ),
        None,
    )
    conflict = next((row for row in rows if row is not exact), None)
    return exact, conflict


def natural_import_match_count(
    db: Session,
    *,
    account_id: int,
    transaction_date: date,
    amount_cents: int,
    description: str,
) -> int:
    rows = db.scalars(
        select(Transaction).where(
            Transaction.account_id == account_id,
            Transaction.transaction_date == transaction_date,
            Transaction.amount_cents == amount_cents,
            or_(Transaction.import_batch_id.is_not(None), Transaction.source_reference.is_not(None)),
            or_(Transaction.source_reference.is_(None), ~Transaction.source_reference.like(f"{HISTORY_REFERENCE_PREFIX}%")),
        )
    ).all()
    normalized = normalize_transaction_description(description)
    return sum(normalize_transaction_description(row.raw_description) == normalized for row in rows)


def find_merge_match(
    db: Session,
    *,
    target_account_id: int,
    source: Transaction,
    excluded_target_ids: set[int],
) -> tuple[Transaction | None, Transaction | None]:
    exact_hash = db.scalar(
        select(Transaction).where(
            Transaction.account_id == target_account_id,
            Transaction.source_hash == source.source_hash,
            Transaction.id.not_in(excluded_target_ids),
        )
    )
    if exact_hash:
        return exact_hash, None
    if is_categorized_history_reference(source.source_reference):
        return None, None

    batch = db.get(ImportBatch, source.import_batch_id) if source.import_batch_id else None
    reliable_reference = is_reliable_import_reference(batch.detected_preset if batch else None, source.source_reference) or is_intrinsically_reliable_reference(source.source_reference)
    if reliable_reference and source.source_reference:
        reference_rows = db.scalars(
            select(Transaction)
            .where(
                Transaction.account_id == target_account_id,
                Transaction.source_reference == source.source_reference,
                Transaction.id.not_in(excluded_target_ids),
            )
            .order_by(Transaction.deleted_at.is_(None).desc(), Transaction.id.asc())
        ).all()
        exact = next(
            (
                row
                for row in reference_rows
                if row.transaction_date == source.transaction_date and row.amount_cents == source.amount_cents
            ),
            None,
        )
        if exact:
            return exact, None
        if reference_rows:
            return None, reference_rows[0]

    candidates = db.scalars(
        select(Transaction).where(
            Transaction.account_id == target_account_id,
            Transaction.transaction_date == source.transaction_date,
            Transaction.amount_cents == source.amount_cents,
            Transaction.id.not_in(excluded_target_ids),
            or_(Transaction.import_batch_id.is_not(None), Transaction.source_reference.is_not(None)),
            or_(Transaction.source_reference.is_(None), ~Transaction.source_reference.like(f"{HISTORY_REFERENCE_PREFIX}%")),
        )
    ).all()
    normalized = normalize_transaction_description(source.raw_description)
    natural = next(
        (row for row in candidates if normalize_transaction_description(row.raw_description) == normalized),
        None,
    )
    return natural, None
