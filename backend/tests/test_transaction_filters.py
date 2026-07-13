from datetime import date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Category, Institution, Transaction
from app.schemas import TransactionFilter, TransactionType
from app.services.transaction_filters import parse_csv_ints, parse_csv_values, transaction_filter_conditions


def _filtered_ids(db: Session, filters: TransactionFilter) -> list[int]:
    return list(db.scalars(select(Transaction.id).where(*transaction_filter_conditions(filters)).order_by(Transaction.id)).all())


def test_canonical_filters_compose_accounts_categories_dates_amount_direction_and_search():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        chase = Institution(name="Chase")
        boa = Institution(name="Bank of America")
        groceries = Category(key="groceries", label="Groceries")
        travel = Category(key="travel", label="Travel")
        db.add_all([chase, boa, groceries, travel])
        db.flush()
        checking = Account(institution_id=chase.id, display_name="Checking 1234", account_type="checking")
        card = Account(institution_id=boa.id, display_name="Travel Card", account_type="credit_card")
        db.add_all([checking, card])
        db.flush()
        rows = [
            Transaction(account_id=checking.id, transaction_date=date(2026, 7, 5), amount_cents=-4500, raw_description="Neighborhood Market", transaction_type="expense", category_id=groceries.id, review_status="confirmed", source_hash="filter-1"),
            Transaction(account_id=card.id, transaction_date=date(2026, 6, 15), amount_cents=-12500, raw_description="Airline", user_note="Summer trip", transaction_type="expense", category_id=travel.id, review_status="confirmed", source_hash="filter-2"),
            Transaction(account_id=checking.id, transaction_date=date(2026, 7, 10), amount_cents=250000, raw_description="Payroll", transaction_type="income", review_status="confirmed", source_hash="filter-3"),
        ]
        db.add_all(rows)
        db.commit()

        assert _filtered_ids(db, TransactionFilter(accounts=[checking.id], categories=[str(groceries.id)], months=["07"], years=["2026"], date_from=date(2026, 7, 1), date_to=date(2026, 7, 31), amount_min=4000, amount_max=5000, direction="outflow")) == [rows[0].id]
        assert _filtered_ids(db, TransactionFilter(search="summer")) == [rows[1].id]
        assert _filtered_ids(db, TransactionFilter(search="bank of america")) == [rows[1].id]
        assert _filtered_ids(db, TransactionFilter(categories=["__uncategorized__"], direction="inflow")) == [rows[2].id]
        assert _filtered_ids(db, TransactionFilter(transaction_types=[TransactionType.EXPENSE])) == [rows[0].id, rows[1].id]


def test_parent_categories_include_children_and_labels_are_filterable():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Card", account_type="credit_card")
        travel = Category(key="travel", label="Travel")
        db.add_all([account, travel])
        db.flush()
        airfare = Category(key="airfare", label="Airfare", parent_id=travel.id)
        db.add(airfare)
        db.flush()
        row = Transaction(account_id=account.id, transaction_date=date(2026, 7, 1), amount_cents=-50000, raw_description="Airline", labels="|vacation|reimbursable|", transaction_type="expense", category_id=airfare.id, review_status="confirmed", source_hash="child-filter")
        db.add(row)
        db.commit()

        assert _filtered_ids(db, TransactionFilter(categories=[str(travel.id)])) == [row.id]
        assert _filtered_ids(db, TransactionFilter(tags=["Vacation", "reimbursable"])) == [row.id]
        assert _filtered_ids(db, TransactionFilter(search="vacation")) == [row.id]


def test_live_and_trash_views_are_mutually_exclusive():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        live = Transaction(account_id=account.id, transaction_date=date(2026, 7, 1), amount_cents=-100, raw_description="Live", transaction_type="expense", review_status="confirmed", source_hash="live")
        deleted = Transaction(account_id=account.id, transaction_date=date(2026, 7, 2), amount_cents=-200, raw_description="Deleted", transaction_type="expense", review_status="confirmed", source_hash="deleted", deleted_at=datetime(2026, 7, 12))
        db.add_all([live, deleted])
        db.commit()

        assert _filtered_ids(db, TransactionFilter()) == [live.id]
        assert _filtered_ids(db, TransactionFilter(view="trash")) == [deleted.id]


def test_csv_query_values_are_deduplicated_and_invalid_account_ids_are_ignored():
    assert parse_csv_values("7,8,7,__uncategorized__") == ["7", "8", "__uncategorized__"]
    assert parse_csv_ints("4,nope,5,4") == [4, 5]
