from __future__ import annotations

from sqlalchemy import func, or_, select

from ..models import Account, Category, Institution, Transaction
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
        category_conditions = []
        if category_ids:
            category_conditions.append(Transaction.category_id.in_(category_ids))
        if UNCATEGORIZED_FILTER in filters.categories:
            category_conditions.append(Transaction.category_id.is_(None))
        conditions.append(or_(*category_conditions) if category_conditions else False)
    if filters.months:
        conditions.append(func.strftime("%m", Transaction.transaction_date).in_(filters.months))
    if filters.years:
        conditions.append(func.strftime("%Y", Transaction.transaction_date).in_(filters.years))
    if filters.date_from:
        conditions.append(Transaction.transaction_date >= filters.date_from)
    if filters.date_to:
        conditions.append(Transaction.transaction_date <= filters.date_to)
    if filters.amount_min is not None:
        conditions.append(func.abs(Transaction.amount_cents) >= filters.amount_min)
    if filters.amount_max is not None:
        conditions.append(func.abs(Transaction.amount_cents) <= filters.amount_max)
    if filters.direction == "inflow":
        conditions.append(Transaction.amount_cents > 0)
    elif filters.direction == "outflow":
        conditions.append(Transaction.amount_cents < 0)
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
