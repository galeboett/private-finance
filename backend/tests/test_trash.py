from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Category, Transaction, TransactionSplit
from app.services.trash import purge_expired_trash


def test_trash_retention_purges_only_expired_rows_and_dependencies():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Checking", account_type="checking")
        category = Category(key="misc", label="Misc")
        db.add_all([account, category])
        db.flush()
        old = Transaction(account_id=account.id, transaction_date=date(2026, 1, 1), amount_cents=-100, raw_description="Old", transaction_type="expense", review_status="confirmed", source_hash="old-trash", deleted_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=91))
        recent = Transaction(account_id=account.id, transaction_date=date(2026, 7, 1), amount_cents=-200, raw_description="Recent", transaction_type="expense", review_status="confirmed", source_hash="recent-trash", deleted_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=10))
        db.add_all([old, recent])
        db.flush()
        db.add(TransactionSplit(transaction_id=old.id, category_id=category.id, amount_cents=-100, note=None))
        db.commit()

        assert purge_expired_trash(db, retention_days=90) == 1
        db.commit()
        assert db.get(Transaction, old.id) is None
        assert db.get(Transaction, recent.id) is not None
        assert db.query(TransactionSplit).count() == 0
