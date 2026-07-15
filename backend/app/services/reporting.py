from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, Category, ExpenseAllocation, HoldingSnapshot, NetWorthSnapshot, Transaction, TransactionSplit
from .transaction_queries import live_transaction_filters, live_transaction_select
from .snapshots import net_worth_series


def dashboard_summary(db: Session) -> dict:
    today = date.today()
    month_start = today.replace(day=1)
    review_counts = dict(
        db.execute(
            select(Transaction.review_status, func.count(Transaction.id))
            .where(*live_transaction_filters())
            .group_by(Transaction.review_status)
        ).all()
    )
    mtd_spend = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).join(Account, Account.id == Transaction.account_id).where(Account.account_type != "external", *live_transaction_filters(
            Transaction.transaction_date >= month_start,
            Transaction.transaction_type == "expense",
        ))
    )
    cash_flow = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).join(Account, Account.id == Transaction.account_id).where(Account.account_type != "external", *live_transaction_filters(
            Transaction.transaction_date >= month_start,
            Transaction.transaction_type.in_(["expense", "income", "refund"]),
        ))
    )
    net_worth = net_worth_series(db, from_date=today, to_date=today)["series"][0]["total_cents"]
    return {
        "review_counts": review_counts,
        "month_to_date_expense_cents": abs(mtd_spend or 0),
        "cash_flow_cents": cash_flow or 0,
        "net_worth_snapshot_cents": net_worth or 0,
    }


def category_totals(db: Session, start_date: date | None = None, end_date: date | None = None) -> list[dict]:
    """Return active expense totals, respecting splits and an optional date range."""
    filters = list(live_transaction_filters(Transaction.transaction_type == "expense", Transaction.account_id.not_in(select(Account.id).where(Account.account_type == "external"))))
    if start_date:
        filters.append(Transaction.transaction_date >= start_date)
    if end_date:
        filters.append(Transaction.transaction_date <= end_date)
    allocation_exists = select(ExpenseAllocation.id).where(ExpenseAllocation.transaction_id == Transaction.id).exists()

    split_rows = db.execute(
        select(Category.label, func.sum(TransactionSplit.amount_cents))
        .join(Category, Category.id == TransactionSplit.category_id)
        .join(Transaction, Transaction.id == TransactionSplit.transaction_id)
        .where(*filters, ~allocation_exists)
        .group_by(Category.label)
    ).all()
    unsplit_rows = db.execute(
        select(Category.label, func.sum(Transaction.amount_cents))
        .join(Category, Category.id == Transaction.category_id)
        .where(~Transaction.id.in_(select(TransactionSplit.transaction_id)), ~allocation_exists, *filters)
        .group_by(Category.label)
    ).all()
    allocation_filters = list(live_transaction_filters(Transaction.transaction_type == "expense", Transaction.account_id.not_in(select(Account.id).where(Account.account_type == "external"))))
    if start_date:
        allocation_filters.append(ExpenseAllocation.allocation_date >= start_date)
    if end_date:
        allocation_filters.append(ExpenseAllocation.allocation_date <= end_date)
    allocation_rows = db.execute(
        select(Category.label, func.sum(ExpenseAllocation.amount_cents))
        .join(Category, Category.id == ExpenseAllocation.category_id)
        .join(Transaction, Transaction.id == ExpenseAllocation.transaction_id)
        .where(*allocation_filters)
        .group_by(Category.label)
    ).all()
    totals = defaultdict(int)
    for label, value in list(split_rows) + list(unsplit_rows) + list(allocation_rows):
        totals[label] += abs(value or 0)
    return [{"category": label, "amount_cents": amount} for label, amount in sorted(totals.items())]


def cash_flow_summary(db: Session) -> list[dict]:
    rows = db.scalars(
        live_transaction_select(
            Transaction.transaction_type.in_(["expense", "income", "refund"]),
            Transaction.account_id.not_in(select(Account.id).where(Account.account_type == "external")),
        )
        .order_by(Transaction.transaction_date.asc())
    ).all()
    monthly: dict[str, dict[str, int]] = defaultdict(lambda: {"income_cents": 0, "expense_cents": 0, "net_cents": 0})
    for row in rows:
        key = row.transaction_date.strftime("%Y-%m")
        if row.transaction_type == "income":
            monthly[key]["income_cents"] += row.amount_cents
        elif row.transaction_type == "expense":
            monthly[key]["expense_cents"] += abs(row.amount_cents)
        elif row.transaction_type == "refund":
            monthly[key]["expense_cents"] -= abs(row.amount_cents)
        monthly[key]["net_cents"] += row.amount_cents
    return [{"month": month, **values} for month, values in sorted(monthly.items())]


def latest_net_worth_by_account(db: Session) -> list[dict]:
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.account_type != "external", Account.net_worth_inclusion != "never")).all()}
    rows = db.scalars(select(NetWorthSnapshot).order_by(NetWorthSnapshot.snapshot_date.asc(), NetWorthSnapshot.id.asc())).all()
    latest_dates: dict[int, date] = {}
    for row in rows:
        latest_dates[row.account_id] = max(latest_dates.get(row.account_id, row.snapshot_date), row.snapshot_date)

    totals: dict[int, int] = {}
    for row in rows:
        if latest_dates.get(row.account_id) == row.snapshot_date:
            totals[row.account_id] = row.balance_cents

    result = []
    for account_id, total in sorted(totals.items(), key=lambda item: accounts.get(item[0]).display_name if accounts.get(item[0]) else ""):
        account = accounts.get(account_id)
        if not account:
            continue
        result.append(
            {
                "account_id": account.id,
                "account": account.display_name,
                "account_type": account.account_type,
                "latest_date": latest_dates[account.id].isoformat(),
                "market_value_cents": total,
            }
        )
    return result


def latest_investment_allocation(db: Session) -> list[dict]:
    latest_dates = {row["account_id"]: row["latest_date"] for row in latest_net_worth_by_account(db)}
    rows = db.scalars(select(HoldingSnapshot)).all()
    grouped: dict[str, int] = defaultdict(int)
    for row in rows:
        latest_date = latest_dates.get(row.account_id)
        if not latest_date or row.snapshot_date.isoformat() != latest_date:
            continue
        grouped[row.asset_class or "Unclassified"] += row.market_value_cents
    return [{"asset_class": label, "market_value_cents": amount} for label, amount in sorted(grouped.items())]
