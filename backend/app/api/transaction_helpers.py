from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Category, Transaction
from ..schemas import ReviewStatus, TransactionType
from ..services.mutation_log import MutationChange, full_values
from ..services.transfers import auto_dismiss_reclassified_payment


CATEGORYLESS_TRANSACTION_TYPES = {TransactionType.TRANSFER.value, TransactionType.CREDIT_CARD_PAYMENT.value}
CATEGORY_REQUIRED_FOR_CONFIRMATION = {TransactionType.EXPENSE.value, TransactionType.REFUND.value}


def normalize_transaction_updates(updates: dict) -> dict:
    if updates.get("transaction_type") in CATEGORYLESS_TRANSACTION_TYPES:
        updates["category_id"] = None
    return updates


def validate_transaction_confirmation(transaction: Transaction, updates: dict) -> None:
    next_status = updates.get("review_status", transaction.review_status)
    next_type = updates.get("transaction_type", transaction.transaction_type)
    next_category_id = updates.get("category_id", transaction.category_id)
    if next_status == ReviewStatus.CONFIRMED.value and next_type in CATEGORY_REQUIRED_FOR_CONFIRMATION and next_category_id is None:
        noun = "refund" if next_type == TransactionType.REFUND.value else "expense"
        raise HTTPException(status_code=400, detail=f"Choose a category before confirming this {noun}")


def append_payment_reclassification_dismissal(db: Session, transaction: Transaction, updates: dict, changes: list[MutationChange]) -> None:
    if "transaction_type" not in updates or transaction.transaction_type == TransactionType.CREDIT_CARD_PAYMENT.value:
        return
    dismissal = auto_dismiss_reclassified_payment(db, transaction)
    if dismissal:
        changes.append(MutationChange(dismissal.id, None, full_values(dismissal), entity_type="payment_verification_dismissal"))


def normalized_rule_category(db: Session, category_id: int | None, transaction_type: TransactionType | str) -> int | None:
    type_value = transaction_type.value if isinstance(transaction_type, TransactionType) else transaction_type
    if type_value in CATEGORYLESS_TRANSACTION_TYPES:
        return None
    if category_id is None:
        raise HTTPException(status_code=400, detail="Choose a category for this rule")
    if not db.get(Category, category_id):
        raise HTTPException(status_code=400, detail="Category not found")
    return category_id
