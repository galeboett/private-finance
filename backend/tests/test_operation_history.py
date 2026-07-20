from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.api.transactions import _restore_transactions, _soft_delete_transactions
from app.models import Account, Category, CategoryRule, HoldingSnapshot, NetWorthSnapshot, Transaction
from app.services.mutation_log import MutationChange, changed_values, full_values, journal_mutation
from app.services.operation_history import OperationConflict, list_operations, operation_detail, undo_operation


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _transaction(account_id: int, source_hash: str) -> Transaction:
    return Transaction(
        account_id=account_id,
        transaction_date=date(2026, 7, 12),
        amount_cents=-2500,
        raw_description="Merchant",
        transaction_type="expense",
        review_status="confirmed",
        source_hash=source_hash,
    )


def test_update_can_be_undone_and_undo_can_be_undone_as_redo():
    with _session() as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        transaction = _transaction(account.id, "undo-redo")
        db.add(transaction)
        db.flush()
        before = changed_values(transaction, ["user_note"])
        transaction.user_note = "Corrected"
        operation_id = journal_mutation(db, kind="update", entity_type="transaction", actor="user:1", description="Corrected note", changes=[MutationChange(transaction.id, before, changed_values(transaction, ["user_note"]))])
        db.commit()

        undo = undo_operation(db, operation_id=operation_id, actor="user:1")
        db.commit()
        assert db.get(Transaction, transaction.id).user_note is None

        redo = undo_operation(db, operation_id=undo["operation_id"], actor="user:1")
        db.commit()
        assert db.get(Transaction, transaction.id).user_note == "Corrected"
        assert operation_detail(db, redo["operation_id"])["undo_of"] == undo["operation_id"]


def test_later_change_blocks_undo_and_partial_undo_skips_conflicted_rows():
    with _session() as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        first = _transaction(account.id, "partial-1")
        second = _transaction(account.id, "partial-2")
        db.add_all([first, second])
        db.flush()
        changes = []
        for row in (first, second):
            before = changed_values(row, ["user_note"])
            row.user_note = "Bulk note"
            changes.append(MutationChange(row.id, before, changed_values(row, ["user_note"])))
        bulk_id = journal_mutation(db, kind="bulk_update", entity_type="transaction", actor="user:1", description="Bulk note", changes=changes)
        db.commit()

        later_before = changed_values(second, ["user_note"])
        second.user_note = "Later correction"
        journal_mutation(db, kind="update", entity_type="transaction", actor="user:1", description="Later correction", changes=[MutationChange(second.id, later_before, changed_values(second, ["user_note"]))])
        db.commit()

        with pytest.raises(OperationConflict) as error:
            undo_operation(db, operation_id=bulk_id, actor="user:1")
        assert error.value.entity_ids == [str(second.id)]

        result = undo_operation(db, operation_id=bulk_id, actor="user:1", unconflicted_only=True)
        db.commit()
        assert result["undone"] == 1
        assert db.get(Transaction, first.id).user_note is None
        assert db.get(Transaction, second.id).user_note == "Later correction"


def test_large_import_undo_does_not_exceed_sqlite_expression_depth():
    with _session() as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        rows = [_transaction(account.id, f"large-import-{index}") for index in range(1_205)]
        db.add_all(rows)
        db.flush()
        import_id = journal_mutation(
            db,
            kind="import",
            entity_type="transaction",
            actor="user:1",
            description="Imported a large history file",
            changes=[MutationChange(row.id, None, changed_values(row, ["deleted_at"])) for row in rows],
        )
        db.commit()

        result = undo_operation(db, operation_id=import_id, actor="user:1")
        db.commit()

        assert result["undone"] == 1_205
        assert all(row.deleted_at is not None for row in db.scalars(select(Transaction)).all())


def test_import_undo_soft_deletes_transaction_and_restores_holding_on_redo():
    with _session() as db:
        account = Account(display_name="Brokerage", account_type="brokerage")
        db.add(account)
        db.flush()
        holding = HoldingSnapshot(account_id=account.id, snapshot_date=date(2026, 7, 12), symbol="VTI", market_value_cents=50000)
        db.add(holding)
        db.flush()
        db.add(NetWorthSnapshot(account_id=account.id, snapshot_date=date(2026, 7, 12), balance_cents=50000, source="import"))
        fields = ["account_id", "snapshot_date", "symbol", "description", "quantity_basis_points", "price_cents", "market_value_cents", "asset_class"]
        import_id = journal_mutation(db, kind="import", entity_type="holding_snapshot", actor="user:1", description="Imported holdings", changes=[MutationChange(holding.id, None, changed_values(holding, fields))])
        db.commit()
        holding_id = holding.id

        undo = undo_operation(db, operation_id=import_id, actor="user:1")
        db.commit()
        assert db.get(HoldingSnapshot, holding_id) is None
        assert db.query(NetWorthSnapshot).count() == 0

        undo_operation(db, operation_id=undo["operation_id"], actor="user:1")
        db.commit()
        assert db.get(HoldingSnapshot, holding_id).market_value_cents == 50000
        assert db.query(NetWorthSnapshot).one().balance_cents == 50000
        assert list_operations(db)[0]["kind"] == "undo"


def test_bulk_trash_and_restore_are_single_undoable_operations():
    with _session() as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        rows = [_transaction(account.id, "trash-1"), _transaction(account.id, "trash-2")]
        db.add_all(rows)
        db.commit()

        delete_id = _soft_delete_transactions(db, rows, "user:1")
        db.commit()
        assert all(db.get(Transaction, row.id).deleted_at is not None for row in rows)
        assert operation_detail(db, delete_id)["change_count"] == 2

        restore_id = _restore_transactions(db, rows, "user:1")
        db.commit()
        assert all(db.get(Transaction, row.id).deleted_at is None for row in rows)

        undo_operation(db, operation_id=restore_id, actor="user:1")
        db.commit()
        assert all(db.get(Transaction, row.id).deleted_at is not None for row in rows)


def test_transaction_import_undo_keeps_balance_snapshot_in_sync():
    with _session() as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        transaction = _transaction(account.id, "snapshot-undo")
        transaction.running_balance_cents = 123400
        db.add(transaction)
        db.flush()
        db.add(NetWorthSnapshot(account_id=account.id, snapshot_date=transaction.transaction_date, balance_cents=123400, source="import"))
        import_id = journal_mutation(db, kind="import", entity_type="transaction", actor="user:1", description="Imported checking", changes=[MutationChange(transaction.id, None, changed_values(transaction, ["deleted_at"]))])
        db.commit()

        undo = undo_operation(db, operation_id=import_id, actor="user:1")
        db.commit()
        assert db.get(Transaction, transaction.id).deleted_at is not None
        assert db.query(NetWorthSnapshot).count() == 0

        undo_operation(db, operation_id=undo["operation_id"], actor="user:1")
        db.commit()
        assert db.get(Transaction, transaction.id).deleted_at is None
        assert db.query(NetWorthSnapshot).one().balance_cents == 123400


def test_mixed_operation_restores_deleted_category_and_reassigned_rows():
    with _session() as db:
        account = Account(display_name="Checking", account_type="checking")
        old_category = Category(key="old", label="Old")
        new_category = Category(key="new", label="New")
        db.add_all([account, old_category, new_category])
        db.flush()
        transaction = _transaction(account.id, "mixed-category")
        transaction.category_id = old_category.id
        rule = CategoryRule(category_id=old_category.id, field_name="raw_description", match_text="MERCHANT", suggested_transaction_type="expense")
        db.add_all([transaction, rule])
        db.flush()
        changes = [
            MutationChange(old_category.id, full_values(old_category), None, entity_type="category"),
            MutationChange(transaction.id, changed_values(transaction, ["category_id"]), {"id": transaction.id, "category_id": new_category.id}, entity_type="transaction"),
            MutationChange(rule.id, changed_values(rule, ["category_id"]), {"id": rule.id, "category_id": new_category.id}, entity_type="category_rule"),
        ]
        transaction.category_id = new_category.id
        rule.category_id = new_category.id
        db.delete(old_category)
        operation_id = journal_mutation(db, kind="delete", entity_type="mixed", actor="user:1", description="Merged category", changes=changes)
        db.commit()

        undo_operation(db, operation_id=operation_id, actor="user:1")
        db.commit()

        assert db.get(Category, old_category.id).label == "Old"
        assert db.get(Transaction, transaction.id).category_id == old_category.id
        assert db.get(CategoryRule, rule.id).category_id == old_category.id
