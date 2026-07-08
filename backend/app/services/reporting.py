from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, Category, HoldingSnapshot, Transaction, TransactionSplit


def dashboard_summary(db: Session) -> dict:
    today = date.today()
    month_start = today.replace(day=1)
    review_counts = dict(
        db.execute(
            select(Transaction.review_status, func.count(Transaction.id))
            .where(Transaction.status == "active")
            .group_by(Transaction.review_status)
        ).all()
    )
    mtd_spend = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.transaction_date >= month_start,
            Transaction.transaction_type == "expense",
            Transaction.status == "active",
        )
    )
    cash_flow = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.transaction_date >= month_start,
            Transaction.status == "active",
            Transaction.transaction_type.in_(["expense", "income", "refund"]),
        )
    )
    net_worth = db.scalar(select(func.coalesce(func.sum(HoldingSnapshot.market_value_cents), 0)))
    return {
        "review_counts": review_counts,
        "month_to_date_expense_cents": abs(mtd_spend or 0),
        "cash_flow_cents": cash_flow or 0,
        "net_worth_snapshot_cents": net_worth or 0,
    }


def category_totals(db: Session) -> list[dict]:
    split_rows = db.execute(
        select(Category.label, func.sum(TransactionSplit.amount_cents))
        .join(Category, Category.id == TransactionSplit.category_id)
        .group_by(Category.label)
    ).all()
    unsplit_rows = db.execute(
        select(Category.label, func.sum(Transaction.amount_cents))
        .join(Category, Category.id == Transaction.category_id)
        .where(~Transaction.id.in_(select(TransactionSplit.transaction_id)), Transaction.transaction_type == "expense", Transaction.status == "active")
        .group_by(Category.label)
    ).all()
    totals = defaultdict(int)
    for label, value in list(split_rows) + list(unsplit_rows):
        totals[label] += abs(value or 0)
    return [{"category": label, "amount_cents": amount} for label, amount in sorted(totals.items())]


def cash_flow_summary(db: Session) -> list[dict]:
    rows = db.execute(
        select(Account.display_name, func.coalesce(func.sum(Transaction.amount_cents), 0))
        .join(Transaction, Transaction.account_id == Account.id)
        .where(Transaction.status == "active", Account.account_type.in_(["checking", "savings"]))
        .group_by(Account.display_name)
    ).all()
    return [{"account": name, "net_cents": total} for name, total in rows]

