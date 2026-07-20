from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base
from app.api.accounts import create_statement_checkpoint
from app.models import Account, SessionToken, StatementCheckpoint, Transaction
from app.schemas import StatementCheckpointCreate
from app.services.accounts import merge_account_into
from app.services.operation_history import undo_operation
from app.services.reconciliation import backfill_statement_checkpoints, reconciliation_status, record_imported_checkpoints


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _transaction(account_id: int, day: date, amount: int, source_hash: str, running_balance: int | None = None) -> Transaction:
    return Transaction(
        account_id=account_id,
        transaction_date=day,
        amount_cents=amount,
        running_balance_cents=running_balance,
        raw_description=source_hash,
        transaction_type="expense" if amount < 0 else "income",
        review_status="confirmed",
        source_hash=source_hash,
    )


def test_imported_running_balance_creates_latest_daily_checkpoint():
    with Session(_engine()) as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        rows = [
            _transaction(account.id, date(2026, 7, 1), 1000, "one", 10000),
            _transaction(account.id, date(2026, 7, 1), -250, "two", 9750),
        ]
        db.add_all(rows)
        db.flush()

        changes = record_imported_checkpoints(db, rows)

        checkpoint = db.scalar(select(StatementCheckpoint))
        assert checkpoint.statement_balance_cents == 9750
        assert checkpoint.source == "import"
        assert len(changes) == 1
        assert changes[0].entity_type == "statement_checkpoint"


def test_manual_checkpoint_reports_delta_and_is_undoable():
    with Session(_engine()) as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        db.add(StatementCheckpoint(account_id=account.id, statement_date=date(2026, 7, 1), statement_balance_cents=10000, source="manual"))
        db.add_all([
            _transaction(account.id, date(2026, 7, 2), 500, "deposit"),
            _transaction(account.id, date(2026, 7, 3), -200, "purchase"),
        ])
        db.commit()

        request = Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})
        session = SessionToken(user_id=7, csrf_token="csrf")
        saved = create_statement_checkpoint(account.id, StatementCheckpointCreate(statement_date=date(2026, 7, 3), statement_balance_cents=10250), request, session, db)
        status = reconciliation_status(db, account)
        assert status["latest"]["computed_balance_cents"] == 10300
        assert status["latest"]["delta_cents"] == 50
        assert status["latest"]["investigate_from"] == "2026-07-02"

        undo_operation(db, operation_id=saved["operation_id"], actor="user:7")
        db.commit()
        assert db.scalar(select(StatementCheckpoint).where(StatementCheckpoint.statement_date == date(2026, 7, 3))) is None


def test_backfill_is_idempotent_and_merge_preserves_non_conflicting_checkpoints():
    with Session(_engine()) as db:
        target = Account(display_name="Checking", account_type="checking")
        source = Account(display_name="checking", account_type="checking")
        db.add_all([target, source])
        db.flush()
        db.add_all([
            _transaction(target.id, date(2026, 7, 1), 100, "target", 10000),
            _transaction(source.id, date(2026, 7, 2), 200, "source", 10200),
        ])
        db.commit()

        assert backfill_statement_checkpoints(db) == 2
        db.commit()
        assert backfill_statement_checkpoints(db) == 0
        merge_account_into(db, source, target)
        db.commit()

        checkpoints = db.scalars(select(StatementCheckpoint).order_by(StatementCheckpoint.statement_date)).all()
        assert [(row.account_id, row.statement_date) for row in checkpoints] == [
            (target.id, date(2026, 7, 1)),
            (target.id, date(2026, 7, 2)),
        ]
