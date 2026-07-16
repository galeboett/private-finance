from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base
from app.main import bulk_update_transactions, operation_bulk_update, update_transaction
from app.models import Account, Category, Operation, OperationChange, SessionToken, Transaction
from app.schemas import BulkTransactionUpdateRequest, OperationBulkUpdateRequest, TransactionReviewUpdate
from app.services.operation_history import undo_operation


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
            ("date", "2026-08-15"),
            ("labels", "Vacation, Reimbursable, vacation"),
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
            assert row.transaction_date == date(2026, 8, 15)
            assert row.labels == "|vacation|reimbursable|"
        db.refresh(target_account)
        assert target_account.institution.name == "New Bank"
        operations = db.query(Operation).order_by(Operation.created_at).all()
        assert len(operations) == 8
        assert all(operation.kind == "bulk_update" for operation in operations)
        assert all(operation.actor == "user:42" for operation in operations)
        assert db.query(OperationChange).count() == 15


def test_generic_bulk_operation_updates_multiple_fields_and_undoes_together():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Checking", account_type="checking")
        category = Category(key="travel", label="Travel")
        db.add_all([account, category])
        db.flush()
        rows = [
            Transaction(
                account_id=account.id,
                transaction_date=date(2026, 7, index),
                amount_cents=-1000 * index,
                raw_description=f"Original {index}",
                transaction_type="expense",
                review_status="suggested",
                source_hash=f"operation-bulk-{index}",
            )
            for index in (1, 2)
        ]
        db.add_all(rows)
        db.commit()
        request = Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})
        session = SessionToken(user_id=42, csrf_token="csrf")

        result = operation_bulk_update(
            OperationBulkUpdateRequest(
                entity_type="transaction",
                ids=[row.id for row in rows],
                patch=TransactionReviewUpdate(category_id=category.id, review_status="confirmed"),
            ),
            request,
            session,
            db,
        )

        assert result["updated"] == 2
        assert all(row.category_id == category.id and row.review_status == "confirmed" for row in rows)
        undo_operation(db, operation_id=result["operation_id"], actor="user:42")
        assert all(row.category_id is None and row.review_status == "suggested" for row in rows)


def test_bulk_card_payment_confirmation_clears_categories():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Card", account_type="credit_card")
        category = Category(key="shopping", label="Shopping")
        db.add_all([account, category])
        db.flush()
        rows = [
            Transaction(account_id=account.id, category_id=category.id, transaction_date=date(2026, 7, index), amount_cents=10000, raw_description=f"Payment {index}", transaction_type="refund", review_status="needs_review", source_hash=f"bulk-payment-{index}")
            for index in (1, 2)
        ]
        db.add_all(rows)
        db.commit()
        request = Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})
        session = SessionToken(user_id=42, csrf_token="csrf")

        operation_bulk_update(
            OperationBulkUpdateRequest(
                entity_type="transaction",
                ids=[row.id for row in rows],
                patch=TransactionReviewUpdate(transaction_type="credit_card_payment", review_status="confirmed"),
            ),
            request,
            session,
            db,
        )

        assert all(row.transaction_type == "credit_card_payment" for row in rows)
        assert all(row.category_id is None for row in rows)
        assert all(row.review_status == "confirmed" for row in rows)


def test_refund_confirmation_requires_category_for_single_and_bulk_updates():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Card", account_type="credit_card")
        category = Category(key="returns", label="Returns")
        db.add_all([account, category])
        db.flush()
        rows = [
            Transaction(account_id=account.id, transaction_date=date(2026, 7, index), amount_cents=1000 * index, raw_description=f"Refund {index}", transaction_type="refund", review_status="needs_review", source_hash=f"refund-confirm-{index}")
            for index in (1, 2)
        ]
        db.add_all(rows)
        db.commit()
        request = Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})
        session = SessionToken(user_id=42, csrf_token="csrf")

        with pytest.raises(HTTPException, match="Choose a category before confirming this refund"):
            update_transaction(rows[0].id, TransactionReviewUpdate(review_status="confirmed"), request, session, db)
        with pytest.raises(HTTPException, match="Choose a category before confirming this refund"):
            operation_bulk_update(OperationBulkUpdateRequest(entity_type="transaction", ids=[row.id for row in rows], patch=TransactionReviewUpdate(transaction_type="refund", review_status="confirmed")), request, session, db)

        result = operation_bulk_update(OperationBulkUpdateRequest(entity_type="transaction", ids=[row.id for row in rows], patch=TransactionReviewUpdate(category_id=category.id, transaction_type="refund", review_status="confirmed")), request, session, db)

        assert result["updated"] == 2
        assert all(row.category_id == category.id and row.review_status == "confirmed" for row in rows)
