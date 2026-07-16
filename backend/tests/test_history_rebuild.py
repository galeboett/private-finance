from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import (
    Account,
    AuditEvent,
    Category,
    DuplicatePairDecision,
    ExpenseAllocation,
    HoldingLot,
    ImportBatch,
    Institution,
    PaymentVerificationDismissal,
    RefundLink,
    StagingRow,
    Transaction,
    TransactionSplit,
    TransferLink,
)
from app.services.history_rebuild import HISTORICAL_WORKBOOK_FILENAME, preview_history_import_purge, purge_history_import_lineage


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _transaction(account_id: int, batch_id: int, source_hash: str, amount_cents: int, *, duplicate_of: int | None = None) -> Transaction:
    return Transaction(
        account_id=account_id,
        import_batch_id=batch_id,
        transaction_date=date(2026, 7, 1),
        posted_date=date(2026, 7, 1),
        amount_cents=amount_cents,
        raw_description=source_hash,
        normalized_payee=source_hash,
        transaction_type="expense" if amount_cents < 0 else "refund",
        review_status="possible_duplicate" if duplicate_of else "confirmed",
        source_hash=source_hash,
        source_reference=f"ref-{source_hash}",
        duplicate_of_transaction_id=duplicate_of,
    )


def test_history_lineage_preview_and_purge_are_exact_scoped_and_release_source_hashes():
    with _session() as db:
        institution = Institution(name="Example Bank")
        account = Account(institution=institution, display_name="Example Card", account_type="credit_card")
        category = Category(key="food", label="Food")
        db.add_all([account, category])
        db.flush()
        history_batch = ImportBatch(account_id=account.id, filename=HISTORICAL_WORKBOOK_FILENAME, file_hash="history", status="committed")
        other_batch = ImportBatch(account_id=account.id, filename="bank.csv", file_hash="bank", status="committed")
        db.add_all([history_batch, other_batch])
        db.flush()

        history = _transaction(account.id, history_batch.id, "history-row", -1200)
        trashed_history = _transaction(account.id, history_batch.id, "history-trash", 300)
        other = _transaction(account.id, other_batch.id, "bank-row", 1200)
        db.add_all([history, trashed_history, other])
        db.flush()
        trashed_history.deleted_at = history.created_at
        other.duplicate_of_transaction_id = history.id
        other.review_status = "possible_duplicate"
        other.linked_transaction_id = history.id
        db.add_all([
            StagingRow(import_batch_id=history_batch.id, account_id=account.id, row_index=1, row_kind="transaction", raw_json="{}", normalized_json="{}"),
            TransactionSplit(transaction_id=history.id, category_id=category.id, amount_cents=-1200),
            ExpenseAllocation(transaction_id=history.id, category_id=category.id, allocation_date=date(2026, 7, 1), amount_cents=-1200),
            TransferLink(from_transaction_id=history.id, to_transaction_id=other.id, match_confidence=100, confirmed=True),
            RefundLink(expense_transaction_id=history.id, refund_transaction_id=other.id, match_confidence=100, confirmed=False),
            PaymentVerificationDismissal(transaction_id=history.id, reason="other"),
            DuplicatePairDecision(transaction_a_id=history.id, transaction_b_id=other.id, decision="keep_both"),
            HoldingLot(account_id=account.id, symbol="CASH", acquisition_date=date(2026, 7, 1), quantity_basis_points=10000, cost_basis_cents=100, source="import", import_batch_id=history_batch.id),
        ])
        db.commit()

        preview = preview_history_import_purge(db)
        assert preview["batches"] == 1
        assert preview["transactions"] == 2
        assert preview["live_transactions"] == 1
        assert preview["trashed_transactions"] == 1
        assert preview["signed_total_cents"] == -1200
        assert preview["dependencies"] == {
            "staging_rows": 1,
            "splits": 1,
            "allocations": 1,
            "transfer_links": 1,
            "refund_links": 1,
            "refund_pair_decisions": 0,
            "refund_review_resolutions": 0,
            "payment_dismissals": 1,
            "duplicate_decisions": 1,
            "holding_lots": 1,
            "outside_linked_references": 1,
            "outside_duplicate_references": 1,
        }

        result = purge_history_import_lineage(db, preview_token=preview["preview_token"], confirm_text="PURGE HISTORY", actor="user:7")
        db.commit()
        assert result["purged"] is True
        assert db.get(Transaction, history.id) is None
        assert db.get(Transaction, trashed_history.id) is None
        survivor = db.get(Transaction, other.id)
        assert survivor is not None
        assert survivor.import_batch_id == other_batch.id
        assert survivor.duplicate_of_transaction_id is None
        assert survivor.linked_transaction_id is None
        assert survivor.review_status == "needs_review"
        assert db.get(ImportBatch, history_batch.id) is None
        assert db.get(ImportBatch, other_batch.id) is not None
        assert db.get(Account, account.id) is not None
        assert db.get(Category, category.id) is not None
        assert db.scalars(select(AuditEvent).where(AuditEvent.event_type == "categorized_history_lineage_purge")).one()

        replacement = _transaction(account.id, other_batch.id, "history-row", -1200)
        db.add(replacement)
        db.commit()
        assert replacement.id is not None


def test_history_lineage_purge_requires_confirmation_and_a_current_preview():
    with _session() as db:
        institution = Institution(name="Example Bank")
        account = Account(institution=institution, display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        batch = ImportBatch(account_id=account.id, filename=HISTORICAL_WORKBOOK_FILENAME, file_hash="history", status="committed")
        db.add(batch)
        db.flush()
        transaction = _transaction(account.id, batch.id, "history-row", -100)
        db.add(transaction)
        db.commit()
        preview = preview_history_import_purge(db)

        with pytest.raises(ValueError, match="PURGE HISTORY"):
            purge_history_import_lineage(db, preview_token=preview["preview_token"], confirm_text="PURGE", actor="user:7")

        transaction.source_hash = "changed-after-preview"
        db.commit()
        with pytest.raises(ValueError, match="changed after preview"):
            purge_history_import_lineage(db, preview_token=preview["preview_token"], confirm_text="PURGE HISTORY", actor="user:7")
