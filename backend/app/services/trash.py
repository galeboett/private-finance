from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..models import DuplicatePairDecision, ExpenseAllocation, PaymentVerificationDismissal, RefundLink, RefundPairDecision, RefundReviewResolution, Transaction, TransactionSplit, TransferLink


def purge_expired_trash(db: Session, *, retention_days: int) -> int:
    """Permanently remove transactions that have remained in Trash past the configured window."""
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=retention_days)
    rows = db.scalars(select(Transaction).where(Transaction.deleted_at.is_not(None), Transaction.deleted_at < cutoff)).all()
    if not rows:
        return 0
    ids = [row.id for row in rows]
    db.execute(update(Transaction).where(Transaction.linked_transaction_id.in_(ids)).values(linked_transaction_id=None))
    db.execute(update(Transaction).where(Transaction.duplicate_of_transaction_id.in_(ids)).values(duplicate_of_transaction_id=None))
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id.in_(ids)))
    db.execute(delete(ExpenseAllocation).where(ExpenseAllocation.transaction_id.in_(ids)))
    db.execute(delete(TransferLink).where((TransferLink.from_transaction_id.in_(ids)) | (TransferLink.to_transaction_id.in_(ids))))
    db.execute(delete(RefundLink).where((RefundLink.expense_transaction_id.in_(ids)) | (RefundLink.refund_transaction_id.in_(ids))))
    db.execute(delete(RefundPairDecision).where((RefundPairDecision.expense_transaction_id.in_(ids)) | (RefundPairDecision.refund_transaction_id.in_(ids))))
    db.execute(delete(RefundReviewResolution).where(RefundReviewResolution.refund_transaction_id.in_(ids)))
    db.execute(delete(PaymentVerificationDismissal).where(PaymentVerificationDismissal.transaction_id.in_(ids)))
    db.execute(delete(DuplicatePairDecision).where((DuplicatePairDecision.transaction_a_id.in_(ids)) | (DuplicatePairDecision.transaction_b_id.in_(ids))))
    db.execute(delete(Transaction).where(Transaction.id.in_(ids)))
    return len(ids)
