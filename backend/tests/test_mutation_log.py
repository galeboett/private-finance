import json
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.main import _soft_delete_transaction
from app.models import Account, Operation, OperationChange, Transaction
from app.services.mutation_log import MutationChange, changed_values, journal_mutation
from app.services.transaction_queries import get_live_transaction, live_transaction_select


def _transaction(account_id: int) -> Transaction:
    return Transaction(
        account_id=account_id,
        transaction_date=date(2026, 7, 12),
        amount_cents=-2500,
        raw_description="Original merchant",
        transaction_type="expense",
        review_status="confirmed",
        source_hash="journal-test",
    )


def test_journal_records_changed_columns_in_the_same_commit():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        transaction = _transaction(account.id)
        db.add(transaction)
        db.flush()

        before = changed_values(transaction, ["category_id", "user_note"])
        transaction.category_id = 7
        transaction.user_note = "Corrected"
        operation_id = journal_mutation(
            db,
            kind="update",
            entity_type="transaction",
            actor="user:9",
            description="Corrected transaction",
            changes=[MutationChange(transaction.id, before, changed_values(transaction, ["category_id", "user_note"]))],
        )
        db.commit()

        operation = db.get(Operation, operation_id)
        change = db.scalar(select(OperationChange).where(OperationChange.operation_id == operation_id))
        assert operation.kind == "update"
        assert operation.actor == "user:9"
        assert json.loads(change.before_json) == {"category_id": None, "id": transaction.id, "user_note": None}
        assert json.loads(change.after_json) == {"category_id": 7, "id": transaction.id, "user_note": "Corrected"}


def test_mutation_and_journal_roll_back_together():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        transaction = _transaction(account.id)
        db.add(transaction)
        db.commit()
        transaction_id = transaction.id

        before = changed_values(transaction, ["user_note"])
        transaction.user_note = "Will roll back"
        journal_mutation(
            db,
            kind="update",
            entity_type="transaction",
            actor="user:9",
            description="Temporary change",
            changes=[MutationChange(transaction.id, before, changed_values(transaction, ["user_note"]))],
        )
        db.rollback()

        assert db.get(Transaction, transaction_id).user_note is None
        assert db.scalar(select(Operation)) is None
        assert db.scalar(select(OperationChange)) is None


def test_soft_delete_keeps_row_but_removes_it_from_live_queries():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        transaction = _transaction(account.id)
        db.add(transaction)
        db.commit()
        transaction_id = transaction.id

        operation_id = _soft_delete_transaction(db, transaction, "user:9")
        db.commit()

        deleted = db.get(Transaction, transaction_id)
        assert deleted is not None
        assert deleted.deleted_at is not None
        assert get_live_transaction(db, transaction_id) is None
        assert db.scalars(live_transaction_select()).all() == []
        operation = db.get(Operation, operation_id)
        change = db.scalar(select(OperationChange).where(OperationChange.operation_id == operation_id))
        assert operation.kind == "delete"
        assert json.loads(change.before_json) == {"deleted_at": None, "id": transaction_id}
        assert change.after_json is None
