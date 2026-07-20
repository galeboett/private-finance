from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import Base
from app.api.categories import cleanup_duplicate_categories, delete_category
from app.models import Account, Category, CategoryRule, ExpenseAllocation, SessionToken, Transaction, TransactionSplit
from app.services.operation_history import undo_operation


def test_category_merge_reassigns_every_financial_reference():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Checking", account_type="checking")
        old = Category(key="old", label="Old")
        replacement = Category(key="replacement", label="Replacement")
        db.add_all([account, old, replacement])
        db.flush()
        transaction = Transaction(account_id=account.id, transaction_date=date(2026, 7, 1), amount_cents=-1200, raw_description="Expense", transaction_type="expense", review_status="confirmed", category_id=old.id, source_hash="category-merge")
        db.add(transaction)
        db.flush()
        db.add_all([
            TransactionSplit(transaction_id=transaction.id, category_id=old.id, amount_cents=-1200),
            ExpenseAllocation(transaction_id=transaction.id, category_id=old.id, allocation_date=date(2026, 7, 1), amount_cents=-1200),
            CategoryRule(category_id=old.id, priority=100, field_name="raw_description", match_text="Expense", suggested_transaction_type="expense"),
        ])
        db.commit()
        old_id = old.id

        request = Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})
        session = SessionToken(csrf_token="csrf")
        result = delete_category(old.id, request, replacement.id, session, db)

        assert result["reassigned"] == 4
        assert db.get(Category, old_id) is None
        assert db.get(Transaction, transaction.id).category_id == replacement.id
        assert db.scalar(select(TransactionSplit.category_id)) == replacement.id
        assert db.scalar(select(ExpenseAllocation.category_id)) == replacement.id
        assert db.scalar(select(CategoryRule.category_id)) == replacement.id

        undo_operation(db, operation_id=result["operation_id"], actor="user:1")
        db.commit()
        assert db.get(Category, old_id).label == "Old"
        assert db.get(Transaction, transaction.id).category_id == old_id
        assert db.scalar(select(TransactionSplit.category_id)) == old_id
        assert db.scalar(select(ExpenseAllocation.category_id)) == old_id
        assert db.scalar(select(CategoryRule.category_id)) == old_id


def test_cleanup_duplicate_categories_merges_spacing_and_case_variants():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Checking", account_type="checking")
        canonical = Category(key="gift_card", label="Gift Card")
        duplicate = Category(key="giftcard", label="Giftcard")
        db.add_all([account, canonical, duplicate])
        db.flush()
        transaction = Transaction(account_id=account.id, transaction_date=date(2026, 7, 1), amount_cents=-1200, raw_description="Gift", transaction_type="expense", review_status="confirmed", category_id=duplicate.id, source_hash="gift-card")
        db.add(transaction)
        db.commit()

        result = cleanup_duplicate_categories(db)

        assert result["merged"] == 1
        assert result["reassigned"] == 1
        assert result["operation_id"]
        assert db.scalar(select(Category).where(Category.label == "Giftcard")) is None
        assert db.get(Transaction, transaction.id).category_id == canonical.id
