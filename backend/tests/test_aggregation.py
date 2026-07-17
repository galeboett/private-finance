from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Category, ExpenseAllocation, Transaction, TransactionSplit
from app.schemas import TransactionFilter, TransactionType
from app.services.aggregation import aggregate_by_account, aggregate_by_category, aggregate_summary, aggregate_timeseries
from app.services.transaction_filters import transaction_filter_conditions


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed(db: Session):
    checking = Account(display_name="Checking", account_type="checking", last_four="1234")
    card = Account(display_name="Card", account_type="credit_card", last_four="9876")
    groceries = Category(key="groceries", label="Groceries")
    travel = Category(key="travel", label="Travel")
    db.add_all([checking, card, groceries, travel])
    db.flush()
    rows = [
        Transaction(account_id=checking.id, transaction_date=date(2026, 6, 29), amount_cents=-4000, raw_description="Market", transaction_type="expense", category_id=groceries.id, review_status="confirmed", source_hash="agg-1"),
        Transaction(account_id=checking.id, transaction_date=date(2026, 7, 1), amount_cents=250000, raw_description="Payroll", transaction_type="income", review_status="confirmed", source_hash="agg-2"),
        Transaction(account_id=card.id, transaction_date=date(2026, 7, 5), amount_cents=-12000, raw_description="Airline", transaction_type="expense", category_id=travel.id, review_status="confirmed", source_hash="agg-3"),
        Transaction(account_id=card.id, transaction_date=date(2026, 7, 7), amount_cents=2000, raw_description="Airline refund", transaction_type="refund", category_id=travel.id, review_status="confirmed", source_hash="agg-4"),
    ]
    db.add_all(rows)
    db.commit()
    return checking, card, groceries, travel, rows


def test_each_aggregate_uses_the_same_rows_and_sum_as_the_canonical_filter():
    with _session() as db:
        checking, _, groceries, _, _ = _seed(db)
        filters_to_check = [
            TransactionFilter(),
            TransactionFilter(accounts=[checking.id]),
            TransactionFilter(categories=[str(groceries.id)]),
            TransactionFilter(date_from=date(2026, 7, 1), direction="outflow"),
            TransactionFilter(transaction_types=[TransactionType.EXPENSE, TransactionType.REFUND]),
        ]
        for filters in filters_to_check:
            expected = list(db.scalars(select(Transaction).where(*transaction_filter_conditions(filters))).all())
            expected_sum = sum(row.amount_cents for row in expected)
            expected_count = len(expected)
            for aggregate in (
                aggregate_by_category(db, filters),
                aggregate_by_account(db, filters),
                aggregate_timeseries(db, filters, "month"),
            ):
                assert sum(row["total_cents"] for row in aggregate) == expected_sum
                assert sum(row["count"] for row in aggregate) == expected_count


def test_timeseries_bucket_dates_are_stable_at_day_week_and_month_edges():
    with _session() as db:
        _seed(db)
        assert [row["date"] for row in aggregate_timeseries(db, TransactionFilter(), "day")] == ["2026-06-29", "2026-07-01", "2026-07-05", "2026-07-07"]
        assert [row["date"] for row in aggregate_timeseries(db, TransactionFilter(), "week")] == ["2026-06-29", "2026-07-06"]
        assert [row["date"] for row in aggregate_timeseries(db, TransactionFilter(), "month")] == ["2026-06-01", "2026-07-01"]


def test_filter_summary_reports_in_out_net_count_and_average_monthly_spend():
    with _session() as db:
        _seed(db)
        assert aggregate_summary(db, TransactionFilter()) == {
            "inflow_cents": 252000,
            "outflow_cents": 16000,
            "net_cents": 236000,
            "transaction_count": 4,
            "spend_month_count": 2,
            "average_monthly_spend_cents": 8000,
        }


def test_category_and_account_metadata_supports_precise_drill_down_labels():
    with _session() as db:
        _, card, _, travel, _ = _seed(db)
        category = next(row for row in aggregate_by_category(db, TransactionFilter()) if row["category_id"] == travel.id)
        account = next(row for row in aggregate_by_account(db, TransactionFilter()) if row["account_id"] == card.id)
        assert category["category"] == "Travel"
        assert category["count"] == 2
        assert account["account"] == "Card"
        assert account["last_four"] == "9876"


def test_categorized_refund_nets_category_total_and_drilldown_contains_both_rows():
    with _session() as db:
        _, _, _, travel, rows = _seed(db)
        filters = TransactionFilter(categories=[str(travel.id)], transaction_types=[TransactionType.EXPENSE, TransactionType.REFUND])

        aggregate = aggregate_by_category(db, filters)
        drilldown_ids = list(db.scalars(select(Transaction.id).where(*transaction_filter_conditions(filters)).order_by(Transaction.id)))

        assert aggregate == [{"category_id": travel.id, "category": "Travel", "total_cents": -10000, "count": 2}]
        assert drilldown_ids == [rows[2].id, rows[3].id]


def test_reporting_date_category_aggregate_preserves_splits_and_monthly_allocations():
    with _session() as db:
        account = Account(display_name="Checking", account_type="checking")
        insurance = Category(key="insurance", label="Insurance")
        travel = Category(key="travel-split", label="Travel")
        db.add_all([account, insurance, travel])
        db.flush()
        annual = Transaction(account_id=account.id, transaction_date=date(2026, 1, 15), amount_cents=-1200, raw_description="Annual policy", transaction_type="expense", review_status="confirmed", source_hash="agg-allocation")
        split = Transaction(account_id=account.id, transaction_date=date(2026, 2, 10), amount_cents=-900, raw_description="Mixed purchase", transaction_type="expense", review_status="confirmed", source_hash="agg-split")
        db.add_all([annual, split])
        db.flush()
        db.add_all([
            ExpenseAllocation(transaction_id=annual.id, category_id=insurance.id, allocation_date=date(2026, 2, 1), amount_cents=-600),
            ExpenseAllocation(transaction_id=annual.id, category_id=insurance.id, allocation_date=date(2026, 3, 1), amount_cents=-600),
            TransactionSplit(transaction_id=split.id, category_id=insurance.id, amount_cents=-400),
            TransactionSplit(transaction_id=split.id, category_id=travel.id, amount_cents=-500),
        ])
        db.commit()

        february_insurance = TransactionFilter(categories=[str(insurance.id)], date_from=date(2026, 2, 1), date_to=date(2026, 2, 28), date_basis="reporting", transaction_types=[TransactionType.EXPENSE])
        aggregate = aggregate_by_category(db, february_insurance)
        matched_ids = list(db.scalars(select(Transaction.id).where(*transaction_filter_conditions(february_insurance)).order_by(Transaction.id)).all())

        assert aggregate == [{"category_id": insurance.id, "category": "Insurance", "total_cents": -1000, "count": 2}]
        assert matched_ids == [annual.id, split.id]


def test_external_account_rows_are_excluded_from_financial_aggregates():
    with _session() as db:
        external = Account(display_name="Old Checking", account_type="external", net_worth_inclusion="never")
        db.add(external)
        db.flush()
        db.add(Transaction(account_id=external.id, transaction_date=date(2026, 7, 1), amount_cents=-50000, raw_description="External mirror", transaction_type="expense", review_status="confirmed", source_hash="external-aggregate"))
        db.commit()

        assert aggregate_by_category(db, TransactionFilter()) == []
        assert aggregate_by_account(db, TransactionFilter()) == []
        assert aggregate_timeseries(db, TransactionFilter(), "month") == []
