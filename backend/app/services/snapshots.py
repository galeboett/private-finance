from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from datetime import date, timedelta
from typing import Iterable, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, HoldingSnapshot, NetWorthSnapshot, Transaction
from .transaction_queries import live_transaction_filters


SnapshotBucket = Literal["day", "week", "month"]


def upsert_net_worth_snapshot(db: Session, *, account_id: int, snapshot_date: date, balance_cents: int, source: str) -> NetWorthSnapshot:
    snapshot = db.scalar(select(NetWorthSnapshot).where(NetWorthSnapshot.account_id == account_id, NetWorthSnapshot.snapshot_date == snapshot_date))
    if snapshot:
        snapshot.balance_cents = balance_cents
        snapshot.source = source
        return snapshot
    snapshot = NetWorthSnapshot(account_id=account_id, snapshot_date=snapshot_date, balance_cents=balance_cents, source=source)
    db.add(snapshot)
    return snapshot


def record_imported_snapshots(db: Session, transactions: Iterable[Transaction], holding_scopes: Iterable[tuple[int, date]]) -> None:
    db.flush()
    latest_running_balances: dict[tuple[int, date], Transaction] = {}
    for transaction in transactions:
        if transaction.running_balance_cents is None:
            continue
        key = (transaction.account_id, transaction.transaction_date)
        current = latest_running_balances.get(key)
        if current is None or transaction.id > current.id:
            latest_running_balances[key] = transaction
    for (account_id, snapshot_date), transaction in latest_running_balances.items():
        upsert_net_worth_snapshot(db, account_id=account_id, snapshot_date=snapshot_date, balance_cents=transaction.running_balance_cents, source="import")

    for account_id, snapshot_date in set(holding_scopes):
        total = db.scalar(
            select(func.coalesce(func.sum(HoldingSnapshot.market_value_cents), 0)).where(
                HoldingSnapshot.account_id == account_id,
                HoldingSnapshot.snapshot_date == snapshot_date,
            )
        ) or 0
        upsert_net_worth_snapshot(db, account_id=account_id, snapshot_date=snapshot_date, balance_cents=total, source="import")


def backfill_net_worth_snapshots(db: Session) -> int:
    before_count = db.scalar(select(func.count(NetWorthSnapshot.id))) or 0
    holding_totals = db.execute(
        select(HoldingSnapshot.account_id, HoldingSnapshot.snapshot_date, func.sum(HoldingSnapshot.market_value_cents))
        .group_by(HoldingSnapshot.account_id, HoldingSnapshot.snapshot_date)
    ).all()
    for account_id, snapshot_date, total in holding_totals:
        upsert_net_worth_snapshot(db, account_id=account_id, snapshot_date=snapshot_date, balance_cents=total or 0, source="import")

    running_rows = db.scalars(
        select(Transaction)
        .where(Transaction.running_balance_cents.is_not(None), Transaction.deleted_at.is_(None))
        .order_by(Transaction.account_id, Transaction.transaction_date, Transaction.id)
    ).all()
    latest: dict[tuple[int, date], Transaction] = {}
    for row in running_rows:
        latest[(row.account_id, row.transaction_date)] = row
    for (account_id, snapshot_date), row in latest.items():
        upsert_net_worth_snapshot(db, account_id=account_id, snapshot_date=snapshot_date, balance_cents=row.running_balance_cents or 0, source="import")
    db.flush()
    return (db.scalar(select(func.count(NetWorthSnapshot.id))) or 0) - before_count


def net_worth_series(db: Session, *, from_date: date | None = None, to_date: date | None = None, bucket: SnapshotBucket = "day") -> dict:
    to_date = to_date or date.today()
    earliest_snapshot = db.scalar(select(func.min(NetWorthSnapshot.snapshot_date)))
    earliest_transaction = db.scalar(select(func.min(Transaction.transaction_date)).where(*live_transaction_filters()))
    earliest = min((value for value in (earliest_snapshot, earliest_transaction) if value is not None), default=to_date)
    from_date = from_date or earliest
    if from_date > to_date:
        raise ValueError("from date must be on or before to date")

    points = _bucket_dates(from_date, to_date, bucket)
    accounts = db.scalars(select(Account).where(Account.status == "active").order_by(Account.display_name, Account.id)).all()
    snapshots_by_account: dict[int, list[NetWorthSnapshot]] = defaultdict(list)
    for snapshot in db.scalars(select(NetWorthSnapshot).where(NetWorthSnapshot.snapshot_date <= to_date).order_by(NetWorthSnapshot.account_id, NetWorthSnapshot.snapshot_date)).all():
        snapshots_by_account[snapshot.account_id].append(snapshot)
    transactions_by_account: dict[int, list[Transaction]] = defaultdict(list)
    for transaction in db.scalars(select(Transaction).where(*live_transaction_filters(Transaction.transaction_date <= to_date)).order_by(Transaction.account_id, Transaction.transaction_date, Transaction.id)).all():
        transactions_by_account[transaction.account_id].append(transaction)

    series = []
    for point_date in points:
        by_account: dict[str, int] = {}
        for account in accounts:
            value = _account_value_at(account, point_date, snapshots_by_account.get(account.id, []), transactions_by_account.get(account.id, []))
            by_account[str(account.id)] = value
        series.append({"date": point_date.isoformat(), "total_cents": sum(by_account.values()), "by_account": by_account})
    return {"from": from_date.isoformat(), "to": to_date.isoformat(), "bucket": bucket, "series": series}


def net_worth_stats(db: Session, *, from_date: date, to_date: date) -> dict:
    result = net_worth_series(db, from_date=from_date, to_date=to_date, bucket="day")
    rows = result["series"]
    if not rows:
        return _empty_stats(from_date, to_date)
    start = rows[0]["total_cents"]
    end = rows[-1]["total_cents"]
    change = end - start
    minimum = min(rows, key=lambda row: row["total_cents"])
    maximum = max(rows, key=lambda row: row["total_cents"])
    deltas = [
        {"date": rows[index]["date"], "delta_cents": rows[index]["total_cents"] - rows[index - 1]["total_cents"]}
        for index in range(1, len(rows))
    ]
    best = max(deltas, key=lambda row: row["delta_cents"], default={"date": rows[0]["date"], "delta_cents": 0})
    worst = min(deltas, key=lambda row: row["delta_cents"], default={"date": rows[0]["date"], "delta_cents": 0})
    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "start_cents": start,
        "end_cents": end,
        "change_cents": change,
        "change_pct": round((change / abs(start)) * 100, 2) if start else None,
        "min_cents": minimum["total_cents"],
        "min_date": minimum["date"],
        "max_cents": maximum["total_cents"],
        "max_date": maximum["date"],
        "best_day": best,
        "worst_day": worst,
    }


def _account_value_at(account: Account, point_date: date, snapshots: list[NetWorthSnapshot], transactions: list[Transaction]) -> int:
    snapshot_dates = [snapshot.snapshot_date for snapshot in snapshots]
    snapshot_index = bisect_right(snapshot_dates, point_date) - 1
    snapshot = snapshots[snapshot_index] if snapshot_index >= 0 else None
    if account.account_type in {"brokerage", "retirement"}:
        return snapshot.balance_cents if snapshot else 0
    if snapshot is None and snapshots:
        next_snapshot = snapshots[0]
        later_movement = sum(
            transaction.amount_cents
            for transaction in transactions
            if point_date < transaction.transaction_date <= next_snapshot.snapshot_date
        )
        return next_snapshot.balance_cents - later_movement
    base = snapshot.balance_cents if snapshot else 0
    after_date = snapshot.snapshot_date if snapshot else None
    movement = sum(
        transaction.amount_cents
        for transaction in transactions
        if transaction.transaction_date <= point_date and (after_date is None or transaction.transaction_date > after_date)
    )
    return base + movement


def _bucket_dates(from_date: date, to_date: date, bucket: SnapshotBucket) -> list[date]:
    if bucket == "day":
        return [from_date + timedelta(days=offset) for offset in range((to_date - from_date).days + 1)]
    if bucket == "week":
        points = []
        cursor = from_date
        while cursor <= to_date:
            points.append(cursor)
            cursor += timedelta(days=7)
        if points[-1] != to_date:
            points.append(to_date)
        return points
    points = []
    cursor = from_date
    while cursor <= to_date:
        next_month = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)
        points.append(min(next_month - timedelta(days=1), to_date))
        cursor = next_month
    return list(dict.fromkeys(points))


def _empty_stats(from_date: date, to_date: date) -> dict:
    return {"from": from_date.isoformat(), "to": to_date.isoformat(), "start_cents": 0, "end_cents": 0, "change_cents": 0, "change_pct": None, "min_cents": 0, "min_date": from_date.isoformat(), "max_cents": 0, "max_date": to_date.isoformat(), "best_day": {"date": from_date.isoformat(), "delta_cents": 0}, "worst_day": {"date": from_date.isoformat(), "delta_cents": 0}}
