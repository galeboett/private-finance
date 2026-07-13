from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Category, ExpenseAllocation, NetWorthSnapshot, Transaction, TransactionSplit
from app.services.reporting import category_totals, latest_net_worth_by_account


def test_category_totals_only_count_active_expense_splits_in_date_range():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(display_name="Checking", account_type="checking")
        groceries = Category(key="groceries", label="Groceries")
        dining = Category(key="dining", label="Dining")
        session.add_all([account, groceries, dining])
        session.flush()

        split_expense = Transaction(account_id=account.id, transaction_date=date(2026, 7, 5), amount_cents=-1000, raw_description="Market", transaction_type="expense", review_status="confirmed", source_hash="split-expense")
        session.add(split_expense)
        session.flush()
        session.add_all([
            TransactionSplit(transaction_id=split_expense.id, category_id=groceries.id, amount_cents=-700),
            TransactionSplit(transaction_id=split_expense.id, category_id=dining.id, amount_cents=-300),
            Transaction(account_id=account.id, transaction_date=date(2026, 7, 6), amount_cents=-400, raw_description="Cafe", transaction_type="expense", category_id=dining.id, review_status="confirmed", source_hash="unsplit-expense"),
            Transaction(account_id=account.id, transaction_date=date(2026, 7, 7), amount_cents=1000, raw_description="Paycheck", transaction_type="income", review_status="confirmed", source_hash="income"),
            Transaction(account_id=account.id, transaction_date=date(2026, 7, 8), amount_cents=-200, raw_description="Voided", transaction_type="expense", category_id=groceries.id, review_status="confirmed", source_hash="voided", status="voided"),
            Transaction(account_id=account.id, transaction_date=date(2026, 6, 30), amount_cents=-900, raw_description="Old", transaction_type="expense", category_id=groceries.id, review_status="confirmed", source_hash="old"),
        ])
        session.commit()

        assert category_totals(session, start_date=date(2026, 7, 1), end_date=date(2026, 7, 31)) == [
            {"category": "Dining", "amount_cents": 700},
            {"category": "Groceries", "amount_cents": 700},
        ]


def test_category_totals_use_monthly_allocations_instead_of_the_charge_date():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account = Account(display_name="Checking", account_type="checking")
        insurance = Category(key="insurance", label="Insurance")
        session.add_all([account, insurance])
        session.flush()
        transaction = Transaction(
            account_id=account.id,
            transaction_date=date(2026, 1, 15),
            amount_cents=-1001,
            raw_description="Six-month car insurance",
            transaction_type="expense",
            category_id=insurance.id,
            review_status="confirmed",
            source_hash="insurance-charge",
        )
        session.add(transaction)
        session.flush()
        session.add_all([
            ExpenseAllocation(transaction_id=transaction.id, category_id=insurance.id, allocation_date=date(2026, 1, 1), amount_cents=-334),
            ExpenseAllocation(transaction_id=transaction.id, category_id=insurance.id, allocation_date=date(2026, 2, 1), amount_cents=-334),
            ExpenseAllocation(transaction_id=transaction.id, category_id=insurance.id, allocation_date=date(2026, 3, 1), amount_cents=-333),
        ])
        session.commit()

        assert category_totals(session, start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)) == [{"category": "Insurance", "amount_cents": 334}]
        assert category_totals(session, start_date=date(2026, 2, 1), end_date=date(2026, 2, 28)) == [{"category": "Insurance", "amount_cents": 334}]


def test_latest_net_worth_accounts_include_manual_non_investment_balances():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        house = Account(display_name="House", account_type="asset")
        session.add(house)
        session.flush()
        session.add_all([
            NetWorthSnapshot(account_id=house.id, snapshot_date=date(2026, 6, 1), balance_cents=44000000, source="manual"),
            NetWorthSnapshot(account_id=house.id, snapshot_date=date(2026, 7, 1), balance_cents=45000000, source="manual"),
        ])
        session.commit()

        assert latest_net_worth_by_account(session) == [{
            "account_id": house.id,
            "account": "House",
            "account_type": "asset",
            "latest_date": "2026-07-01",
            "market_value_cents": 45000000,
        }]
