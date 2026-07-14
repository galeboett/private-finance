from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Category, ImportBatch, Institution, Operation, Transaction, TransactionSplit
from app.services.duplicates import pending_duplicate_pairs, resolve_all_exact_duplicates, resolve_duplicate
from app.services.operation_history import undo_operation


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _pair(db: Session, *, exact: bool = False, suffix: str = "") -> tuple[Transaction, Transaction, Category]:
    institution = Institution(name=f"Example Bank{suffix}")
    account = Account(institution=institution, display_name=f"Rewards Card{suffix}", account_type="credit_card", last_four="1234")
    category = Category(key=f"groceries{suffix}", label="Groceries")
    db.add_all([account, category])
    db.flush()
    batch = ImportBatch(account_id=account.id, filename="statement.csv", file_hash=f"batch{suffix}", status="committed")
    db.add(batch)
    db.flush()
    original = Transaction(
        account_id=account.id,
        import_batch_id=batch.id,
        transaction_date=date(2026, 7, 1),
        posted_date=date(2026, 7, 2),
        amount_cents=-1200,
        raw_description="Market purchase",
        normalized_payee="Market purchase",
        user_note="Weekly groceries",
        labels="shared,food",
        transaction_type="expense",
        category_id=category.id,
        review_status="confirmed",
        source_hash=f"original{suffix}",
        source_reference="REF-1",
    )
    db.add(original)
    db.flush()
    candidate = Transaction(
        account_id=account.id,
        import_batch_id=batch.id,
        transaction_date=original.transaction_date if exact else date(2026, 7, 3),
        posted_date=original.posted_date if exact else date(2026, 7, 4),
        amount_cents=original.amount_cents if exact else -1250,
        raw_description=original.raw_description if exact else "MARKET PURCHASE UPDATED",
        normalized_payee=original.normalized_payee if exact else "MARKET PURCHASE UPDATED",
        user_note=original.user_note if exact else None,
        labels=original.labels if exact else None,
        transaction_type="expense",
        category_id=original.category_id if exact else None,
        review_status="possible_duplicate",
        source_hash=f"candidate{suffix}",
        source_reference=original.source_reference if exact else "REF-2",
        duplicate_of_transaction_id=original.id,
    )
    db.add(candidate)
    db.flush()
    return candidate, original, category


def test_pending_duplicates_return_side_by_side_context_and_diff_fields():
    with _session() as db:
        candidate, original, _ = _pair(db)
        pair = pending_duplicate_pairs(db)[0]
        assert pair["candidate"]["id"] == candidate.id
        assert pair["original"]["id"] == original.id
        assert pair["candidate"]["account"] == "Rewards Card"
        assert pair["candidate"]["institution"] == "Example Bank"
        assert pair["original"]["category"] == "Groceries"
        assert {"reference", "date", "amount", "description", "category", "notes", "labels"}.issubset(pair["diff_fields"])
        assert pair["exact_match"] is False


def test_remove_new_is_one_undoable_operation():
    with _session() as db:
        candidate, _, _ = _pair(db)
        result = resolve_duplicate(db, transaction_id=candidate.id, action="remove_new", actor="user:7")
        db.commit()
        assert candidate.deleted_at is not None
        assert db.get(Operation, result["operation_id"]).kind == "resolve_duplicate"

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert db.get(Transaction, candidate.id).deleted_at is None


def test_keep_both_clears_duplicate_relationship_but_leaves_category_review_open():
    with _session() as db:
        candidate, _, _ = _pair(db)
        resolve_duplicate(db, transaction_id=candidate.id, action="keep_both", actor="user:7")
        db.commit()
        assert candidate.duplicate_of_transaction_id is None
        assert candidate.review_status == "needs_review"
        assert candidate.deleted_at is None


def test_replace_old_copies_bank_fields_and_preserves_user_authored_fields_and_splits():
    with _session() as db:
        candidate, original, category = _pair(db)
        split = TransactionSplit(transaction_id=original.id, category_id=category.id, amount_cents=-1200, note="Keep me")
        db.add(split)
        db.commit()
        old_description = original.raw_description

        result = resolve_duplicate(db, transaction_id=candidate.id, action="replace_old", actor="user:7")
        db.commit()
        assert original.transaction_date == candidate.transaction_date
        assert original.amount_cents == candidate.amount_cents
        assert original.raw_description == candidate.raw_description
        assert original.source_reference == candidate.source_reference
        assert original.user_note == "Weekly groceries"
        assert original.labels == "shared,food"
        assert original.category_id == category.id
        assert db.get(TransactionSplit, split.id).note == "Keep me"
        assert candidate.deleted_at is not None

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert original.raw_description == old_description
        assert candidate.deleted_at is None


def test_resolve_all_exact_matches_uses_one_operation_and_one_undo():
    with _session() as db:
        first, _, _ = _pair(db, exact=True, suffix="-1")
        second, second_original, _ = _pair(db, exact=True, suffix="-2")
        assert pending_duplicate_pairs(db)[0]["exact_match"] is True
        result = resolve_all_exact_duplicates(db, actor="user:7")
        db.commit()
        assert result["resolved"] == 2
        assert first.deleted_at is not None and second.deleted_at is not None
        assert db.get(Operation, result["operation_id"]).kind == "resolve_duplicates"

        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert first.deleted_at is None and second.deleted_at is None
        assert second_original.deleted_at is None
