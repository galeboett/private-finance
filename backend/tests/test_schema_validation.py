import pytest
from pydantic import ValidationError

from app.schemas import AccountCreate, RuleCreate, TransactionReviewUpdate


def test_account_type_rejects_unknown_values():
    with pytest.raises(ValidationError):
        AccountCreate(display_name="Card", account_type="creditcard")


def test_transaction_update_rejects_unknown_type_and_review_status():
    with pytest.raises(ValidationError):
        TransactionReviewUpdate(transaction_type="purchase")
    with pytest.raises(ValidationError):
        TransactionReviewUpdate(review_status="done")


def test_rule_rejects_unknown_suggested_transaction_type():
    with pytest.raises(ValidationError):
        RuleCreate(category_id=1, field_name="raw_description", match_text="coffee", suggested_transaction_type="purchase")
