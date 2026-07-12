from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Transaction


def live_transaction_filters(*extra_conditions):
    """The canonical predicate for user-visible transactions."""
    return (Transaction.deleted_at.is_(None), Transaction.status == "active", *extra_conditions)


def live_transaction_select(*extra_conditions):
    return select(Transaction).where(*live_transaction_filters(*extra_conditions))


def get_live_transaction(db: Session, transaction_id: int) -> Transaction | None:
    return db.scalar(live_transaction_select(Transaction.id == transaction_id))
