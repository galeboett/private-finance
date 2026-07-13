from __future__ import annotations

from sqlalchemy import and_, func, or_, select

from ..models import Account, Category, ExpenseAllocation, Institution, Transaction, TransactionSplit
from ..schemas import TransactionFilter


UNCATEGORIZED_FILTER = "__uncategorized__"


def transaction_filter_conditions(filters: TransactionFilter):
    """Build the canonical transaction predicate used by lists and aggregations."""
    conditions = []
    if filters.view == "trash":
        conditions.append(Transaction.deleted_at.is_not(None))
    else:
        conditions.extend((Transaction.deleted_at.is_(None), Transaction.status == "active"))

    if filters.accounts:
        conditions.append(Transaction.account_id.in_(filters.accounts))
    if filters.categories:
        category_ids = [int(value) for value in filters.categories if value.isdigit()]
        allocation_exists = select(ExpenseAllocation.id).where(ExpenseAllocation.transaction_id == Transaction.id).exists()
        split_exists = select(TransactionSplit.id).where(TransactionSplit.transaction_id == Transaction.id).exists()
        allocation_matches = select(ExpenseAllocation.id).where(ExpenseAllocation.transaction_id == Transaction.id, ExpenseAllocation.category_id.in_(category_ids)).exists() if category_ids else False
        split_matches = select(TransactionSplit.id).where(TransactionSplit.transaction_id == Transaction.id, TransactionSplit.category_id.in_(category_ids)).exists() if category_ids else False
        raw_conditions = []
        if category_ids:
            raw_conditions.append(Transaction.category_id.in_(category_ids))
        if UNCATEGORIZED_FILTER in filters.categories:
            raw_conditions.append(Transaction.category_id.is_(None))
        raw_matches = or_(*raw_conditions) if raw_conditions else False
        conditions.append(or_(
            and_(allocation_exists, allocation_matches),
            and_(~allocation_exists, split_exists, split_matches),
            and_(~allocation_exists, ~split_exists, raw_matches),
        ))
    if filters.months:
        conditions.append(func.strftime("%m", Transaction.transaction_date).in_(filters.months))
    if filters.years:
        conditions.append(func.strftime("%Y", Transaction.transaction_date).in_(filters.years))
    if filters.date_from or filters.date_to:
        transaction_dates = []
        allocation_dates = []
        if filters.date_from:
            transaction_dates.append(Transaction.transaction_date >= filters.date_from)
            allocation_dates.append(ExpenseAllocation.allocation_date >= filters.date_from)
        if filters.date_to:
            transaction_dates.append(Transaction.transaction_date <= filters.date_to)
            allocation_dates.append(ExpenseAllocation.allocation_date <= filters.date_to)
        if filters.date_basis == "reporting":
            allocation_exists = select(ExpenseAllocation.id).where(ExpenseAllocation.transaction_id == Transaction.id).exists()
            allocation_date_matches = select(ExpenseAllocation.id).where(ExpenseAllocation.transaction_id == Transaction.id, *allocation_dates).exists()
            conditions.append(or_(and_(allocation_exists, allocation_date_matches), and_(~allocation_exists, *transaction_dates)))
        else:
            conditions.extend(transaction_dates)
    if filters.amount_min is not None:
        conditions.append(func.abs(Transaction.amount_cents) >= filters.amount_min)
    if filters.amount_max is not None:
        conditions.append(func.abs(Transaction.amount_cents) <= filters.amount_max)
    if filters.direction == "inflow":
        conditions.append(Transaction.amount_cents > 0)
    elif filters.direction == "outflow":
        conditions.append(Transaction.amount_cents < 0)
    if filters.transaction_types:
        conditions.append(Transaction.transaction_type.in_([value.value for value in filters.transaction_types]))
    if filters.review_status:
        conditions.append(Transaction.review_status == filters.review_status.value)
    if filters.search and filters.search.strip():
        needle = filters.search.strip().casefold()
        matching_account_ids = select(Account.id).outerjoin(Institution, Institution.id == Account.institution_id).where(
            or_(func.lower(Account.display_name).contains(needle), func.lower(Institution.name).contains(needle))
        )
        matching_category_ids = select(Category.id).where(func.lower(Category.label).contains(needle))
        conditions.append(
            or_(
                func.lower(Transaction.raw_description).contains(needle),
                func.lower(func.coalesce(Transaction.user_note, "")).contains(needle),
                func.lower(Transaction.transaction_type).contains(needle),
                Transaction.account_id.in_(matching_account_ids),
                Transaction.category_id.in_(matching_category_ids),
            )
        )
    return tuple(conditions)


def parse_csv_values(value: str | None) -> list[str]:
    if not value:
        return []
    return list(dict.fromkeys(part.strip() for part in value.split(",") if part.strip()))


def parse_csv_ints(value: str | None) -> list[int]:
    return [int(part) for part in parse_csv_values(value) if part.isdigit()]
