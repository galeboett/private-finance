from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, HoldingSnapshot, NetWorthSnapshot, Transaction
from app.services.snapshots import backfill_net_worth_snapshots, net_worth_contributors, net_worth_series, net_worth_stats, upsert_net_worth_snapshot
from app.main import save_manual_net_worth_snapshot
from app.models import SessionToken
from app.schemas import NetWorthSnapshotUpsert
from app.services.operation_history import undo_operation
from starlette.requests import Request


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_backfill_uses_investment_totals_and_latest_daily_running_balance():
    with Session(_engine()) as db:
        checking = Account(display_name="Checking", account_type="checking")
        brokerage = Account(display_name="Brokerage", account_type="brokerage")
        db.add_all([checking, brokerage])
        db.flush()
        db.add_all([
            Transaction(account_id=checking.id, transaction_date=date(2026, 7, 1), amount_cents=100, running_balance_cents=10000, raw_description="First", transaction_type="income", review_status="confirmed", source_hash="running-1"),
            Transaction(account_id=checking.id, transaction_date=date(2026, 7, 1), amount_cents=200, running_balance_cents=10200, raw_description="Second", transaction_type="income", review_status="confirmed", source_hash="running-2"),
            HoldingSnapshot(account_id=brokerage.id, snapshot_date=date(2026, 7, 1), symbol="A", market_value_cents=40000),
            HoldingSnapshot(account_id=brokerage.id, snapshot_date=date(2026, 7, 1), symbol="B", market_value_cents=60000),
        ])
        db.commit()

        assert backfill_net_worth_snapshots(db) == 2
        db.commit()
        rows = db.scalars(select(NetWorthSnapshot).order_by(NetWorthSnapshot.account_id)).all()
        assert [(row.account_id, row.balance_cents) for row in rows] == [(checking.id, 10200), (brokerage.id, 100000)]
        assert backfill_net_worth_snapshots(db) == 0


def test_series_forward_fills_snapshots_and_rolls_bank_transactions_forward():
    with Session(_engine()) as db:
        checking = Account(display_name="Checking", account_type="checking")
        brokerage = Account(display_name="Brokerage", account_type="brokerage")
        db.add_all([checking, brokerage])
        db.flush()
        upsert_net_worth_snapshot(db, account_id=checking.id, snapshot_date=date(2026, 7, 1), balance_cents=10000, source="manual")
        upsert_net_worth_snapshot(db, account_id=brokerage.id, snapshot_date=date(2026, 7, 1), balance_cents=50000, source="import")
        upsert_net_worth_snapshot(db, account_id=brokerage.id, snapshot_date=date(2026, 7, 3), balance_cents=55000, source="import")
        db.add_all([
            Transaction(account_id=checking.id, transaction_date=date(2026, 7, 2), amount_cents=500, raw_description="Deposit", transaction_type="income", review_status="confirmed", source_hash="series-1"),
            Transaction(account_id=checking.id, transaction_date=date(2026, 7, 3), amount_cents=-200, raw_description="Spend", transaction_type="expense", review_status="confirmed", source_hash="series-2"),
        ])
        db.commit()

        result = net_worth_series(db, from_date=date(2026, 7, 1), to_date=date(2026, 7, 3), bucket="day")
        assert [row["total_cents"] for row in result["series"]] == [60000, 60500, 65300]
        assert result["series"][1]["by_account"] == {str(checking.id): 10500, str(brokerage.id): 50000}


def test_series_rolls_backward_from_the_first_known_bank_balance():
    with Session(_engine()) as db:
        checking = Account(display_name="Checking", account_type="checking")
        db.add(checking)
        db.flush()
        upsert_net_worth_snapshot(db, account_id=checking.id, snapshot_date=date(2026, 7, 3), balance_cents=10300, source="import")
        db.add_all([
            Transaction(account_id=checking.id, transaction_date=date(2026, 7, 2), amount_cents=500, raw_description="Deposit", transaction_type="income", review_status="confirmed", source_hash="backward-1"),
            Transaction(account_id=checking.id, transaction_date=date(2026, 7, 3), amount_cents=-200, raw_description="Spend", transaction_type="expense", review_status="confirmed", source_hash="backward-2"),
        ])
        db.commit()

        result = net_worth_series(db, from_date=date(2026, 7, 1), to_date=date(2026, 7, 3), bucket="day")
        assert [row["total_cents"] for row in result["series"]] == [10000, 10500, 10300]


def test_month_bucket_edges_and_range_statistics():
    with Session(_engine()) as db:
        account = Account(display_name="Checking", account_type="checking")
        db.add(account)
        db.flush()
        upsert_net_worth_snapshot(db, account_id=account.id, snapshot_date=date(2026, 1, 1), balance_cents=10000, source="manual")
        db.add_all([
            Transaction(account_id=account.id, transaction_date=date(2026, 1, 15), amount_cents=1000, raw_description="Gain", transaction_type="income", review_status="confirmed", source_hash="stats-1"),
            Transaction(account_id=account.id, transaction_date=date(2026, 2, 1), amount_cents=-300, raw_description="Loss", transaction_type="expense", review_status="confirmed", source_hash="stats-2"),
        ])
        db.commit()

        monthly = net_worth_series(db, from_date=date(2026, 1, 15), to_date=date(2026, 3, 10), bucket="month")
        assert [row["date"] for row in monthly["series"]] == ["2026-01-31", "2026-02-28", "2026-03-10"]
        stats = net_worth_stats(db, from_date=date(2026, 1, 14), to_date=date(2026, 2, 2))
        assert stats["start_cents"] == 10000
        assert stats["end_cents"] == 10700
        assert stats["change_cents"] == 700
        assert stats["best_day"] == {"date": "2026-01-15", "delta_cents": 1000}
        assert stats["worst_day"] == {"date": "2026-02-01", "delta_cents": -300}


def test_manual_snapshot_is_journaled_and_undoable():
    with Session(_engine()) as db:
        account = Account(display_name="House", account_type="asset")
        db.add(account)
        db.commit()
        request = Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})
        session = SessionToken(user_id=7, csrf_token="csrf")

        result = save_manual_net_worth_snapshot(NetWorthSnapshotUpsert(account_id=account.id, snapshot_date=date(2026, 7, 12), balance_cents=45000000), request, session, db)

        snapshot = db.query(NetWorthSnapshot).one()
        assert snapshot.source == "manual"
        assert snapshot.balance_cents == 45000000
        undo_operation(db, operation_id=result["operation_id"], actor="user:7")
        db.commit()
        assert db.query(NetWorthSnapshot).count() == 0


def test_net_worth_contributors_rank_accounts_by_asset_change():
    with Session(_engine()) as db:
        checking = Account(display_name="Checking", account_type="checking", last_four="1234")
        brokerage = Account(display_name="Brokerage", account_type="brokerage", last_four="9876")
        db.add_all([checking, brokerage])
        db.flush()
        db.add_all([
            NetWorthSnapshot(account_id=checking.id, snapshot_date=date(2026, 7, 1), balance_cents=10000, source="manual"),
            NetWorthSnapshot(account_id=checking.id, snapshot_date=date(2026, 7, 3), balance_cents=13000, source="manual"),
            NetWorthSnapshot(account_id=brokerage.id, snapshot_date=date(2026, 7, 1), balance_cents=50000, source="manual"),
            NetWorthSnapshot(account_id=brokerage.id, snapshot_date=date(2026, 7, 3), balance_cents=58000, source="manual"),
        ])
        db.commit()

        result = net_worth_contributors(db, from_date=date(2026, 7, 1), to_date=date(2026, 7, 3))

        assert result["change_cents"] == 11000
        assert [(row["account"], row["change_cents"], row["last_four"]) for row in result["accounts"]] == [
            ("Brokerage", 8000, "9876"),
            ("Checking", 3000, "1234"),
        ]
