from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Account, Category, ExpenseAllocation, Transaction, TransactionSplit
from ..schemas import TransactionFilter
from .transaction_filters import transaction_filter_conditions


def aggregate_by_category(db: Session, filters: TransactionFilter) -> list[dict]:
    if filters.date_basis == "reporting":
        return _aggregate_reporting_categories(db, filters)
    rows = _filtered_transactions(db, filters)
    categories = {row.id: row.label for row in db.scalars(select(Category)).all()}
    totals: dict[int | None, dict[str, int]] = defaultdict(lambda: {"total_cents": 0, "count": 0})
    for row in rows:
        totals[row.category_id]["total_cents"] += row.amount_cents
        totals[row.category_id]["count"] += 1
    return [
        {
            "category_id": category_id,
            "category": categories.get(category_id, "Uncategorized") if category_id is not None else "Uncategorized",
            **values,
        }
        for category_id, values in sorted(totals.items(), key=lambda item: (categories.get(item[0], "Uncategorized").casefold(), item[0] or 0))
    ]


def aggregate_by_account(db: Session, filters: TransactionFilter) -> list[dict]:
    rows = _filtered_transactions(db, filters)
    accounts = {row.id: row for row in db.scalars(select(Account)).all()}
    totals: dict[int, dict[str, int]] = defaultdict(lambda: {"total_cents": 0, "count": 0})
    for row in rows:
        totals[row.account_id]["total_cents"] += row.amount_cents
        totals[row.account_id]["count"] += 1
    return [
        {
            "account_id": account_id,
            "account": accounts[account_id].display_name if account_id in accounts else "Unknown account",
            "last_four": accounts[account_id].last_four if account_id in accounts else None,
            **values,
        }
        for account_id, values in sorted(totals.items(), key=lambda item: ((accounts[item[0]].display_name if item[0] in accounts else "").casefold(), item[0]))
    ]


def aggregate_timeseries(db: Session, filters: TransactionFilter, bucket: Literal["day", "week", "month"]) -> list[dict]:
    totals: dict[date, dict[str, int]] = defaultdict(lambda: {"total_cents": 0, "count": 0})
    for row in _filtered_transactions(db, filters):
        bucket_date = _bucket_date(row.transaction_date, bucket)
        totals[bucket_date]["total_cents"] += row.amount_cents
        totals[bucket_date]["count"] += 1
    return [{"date": bucket_date.isoformat(), **values} for bucket_date, values in sorted(totals.items())]


def aggregate_summary(db: Session, filters: TransactionFilter) -> dict:
    rows = _filtered_transactions(db, filters)
    inflow_cents = sum(row.amount_cents for row in rows if row.amount_cents > 0)
    outflow_cents = abs(sum(row.amount_cents for row in rows if row.amount_cents < 0))
    spend_months = {row.transaction_date.strftime("%Y-%m") for row in rows if row.amount_cents < 0}
    return {
        "inflow_cents": inflow_cents,
        "outflow_cents": outflow_cents,
        "net_cents": inflow_cents - outflow_cents,
        "transaction_count": len(rows),
        "spend_month_count": len(spend_months),
        "average_monthly_spend_cents": round(outflow_cents / len(spend_months)) if spend_months else 0,
    }


def _filtered_transactions(db: Session, filters: TransactionFilter) -> list[Transaction]:
    return list(db.scalars(
        select(Transaction)
        .join(Account, Account.id == Transaction.account_id)
        .where(Account.account_type != "external", *transaction_filter_conditions(filters))
    ).all())


def _aggregate_reporting_categories(db: Session, filters: TransactionFilter) -> list[dict]:
    base_filters = filters.model_copy(update={"categories": [], "date_from": None, "date_to": None, "date_basis": "transaction"})
    transactions = _filtered_transactions(db, base_filters)
    transaction_ids = [row.id for row in transactions]
    allocations_by_transaction: dict[int, list[ExpenseAllocation]] = defaultdict(list)
    splits_by_transaction: dict[int, list[TransactionSplit]] = defaultdict(list)
    if transaction_ids:
        for row in db.scalars(select(ExpenseAllocation).where(ExpenseAllocation.transaction_id.in_(transaction_ids))).all():
            allocations_by_transaction[row.transaction_id].append(row)
        for row in db.scalars(select(TransactionSplit).where(TransactionSplit.transaction_id.in_(transaction_ids))).all():
            splits_by_transaction[row.transaction_id].append(row)

    requested_categories = set(filters.categories)
    totals: dict[int | None, int] = defaultdict(int)
    transaction_ids_by_category: dict[int | None, set[int]] = defaultdict(set)
    for transaction in transactions:
        allocations = allocations_by_transaction.get(transaction.id, [])
        splits = splits_by_transaction.get(transaction.id, [])
        if allocations:
            lines = [(row.category_id, row.amount_cents, row.allocation_date) for row in allocations]
        elif splits:
            lines = [(row.category_id, row.amount_cents, transaction.transaction_date) for row in splits]
        else:
            lines = [(transaction.category_id, transaction.amount_cents, transaction.transaction_date)]
        for category_id, amount_cents, reporting_date in lines:
            category_key = str(category_id) if category_id is not None else "__uncategorized__"
            if requested_categories and category_key not in requested_categories:
                continue
            if filters.date_from and reporting_date < filters.date_from:
                continue
            if filters.date_to and reporting_date > filters.date_to:
                continue
            totals[category_id] += amount_cents
            transaction_ids_by_category[category_id].add(transaction.id)

    categories = {row.id: row.label for row in db.scalars(select(Category)).all()}
    return [
        {
            "category_id": category_id,
            "category": categories.get(category_id, "Uncategorized") if category_id is not None else "Uncategorized",
            "total_cents": total_cents,
            "count": len(transaction_ids_by_category[category_id]),
        }
        for category_id, total_cents in sorted(totals.items(), key=lambda item: (categories.get(item[0], "Uncategorized").casefold(), item[0] or 0))
    ]


def _bucket_date(value: date, bucket: Literal["day", "week", "month"]) -> date:
    if bucket == "week":
        return value - timedelta(days=value.weekday())
    if bucket == "month":
        return value.replace(day=1)
    return value
