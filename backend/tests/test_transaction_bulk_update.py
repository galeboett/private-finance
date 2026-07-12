from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base
from app.main import bulk_update_transactions
from app.models import Account, Category, Operation, OperationChange, SessionToken, Transaction
from app.schemas import BulkTransactionUpdateRequest


def test_bulk_update_supports_every_editable_transaction_field():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source_account = Account(display_name="Old account", account_type="checking")
        target_account = Account(display_name="New account", account_type="checking")
        category = Category(key="travel", label="Travel")
        db.add_all([source_account, target_account, category])
        db.flush()
        rows = [
            Transaction(account_id=source_account.id, transaction_date=date(2026, 7, index), amount_cents=-1000 * index, raw_description=f"Original {index}", transaction_type="expense", review_status="confirmed", source_hash=f"bulk-{index}")
            for index in (1, 2)
        ]
        db.add_all(rows)
        db.commit()
        ids = [row.id for row in rows]
        request = Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})
        session = SessionToken(user_id=42, csrf_token="csrf")

        for field, value in [
            ("description", "Updated merchant"),
            ("details", "Business trip"),
            ("type", "refund"),
            ("category", category.id),
            ("account", target_account.id),
            ("institution", "New Bank"),
        ]:
            result = bulk_update_transactions(BulkTransactionUpdateRequest(ids=ids, field=field, value=value), request, session, db)
            assert result["updated"] == 2

        for row in rows:
            db.refresh(row)
            assert row.raw_description == "Updated merchant"
            assert row.user_note == "Business trip"
            assert row.transaction_type == "refund"
            assert row.category_id == category.id
            assert row.account_id == target_account.id
        db.refresh(target_account)
        assert target_account.institution.name == "New Bank"
        operations = db.query(Operation).order_by(Operation.created_at).all()
        assert len(operations) == 6
        assert all(operation.kind == "bulk_update" for operation in operations)
        assert all(operation.actor == "user:42" for operation in operations)
        assert db.query(OperationChange).count() == 11
