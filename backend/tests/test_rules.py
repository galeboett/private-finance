from datetime import date

from app.main import rule_matches_transaction
from app.models import CategoryRule, Transaction


def test_rule_matches_raw_description_case_insensitively():
    rule = CategoryRule(category_id=1, field_name="raw_description", match_text="coffee shop", suggested_transaction_type="expense")
    transaction = Transaction(
        account_id=1,
        transaction_date=date(2026, 7, 1),
        amount_cents=-525,
        raw_description="COFFEE SHOP 1234",
        transaction_type="expense",
        review_status="needs_review",
        source_hash="hash",
        source_ordinal=1,
    )

    assert rule_matches_transaction(rule, transaction)


def test_rule_rejects_unsupported_fields():
    rule = CategoryRule(category_id=1, field_name="memo", match_text="coffee", suggested_transaction_type="expense")
    transaction = Transaction(
        account_id=1,
        transaction_date=date(2026, 7, 1),
        amount_cents=-525,
        raw_description="coffee",
        transaction_type="expense",
        review_status="needs_review",
        source_hash="hash",
        source_ordinal=1,
    )

    assert not rule_matches_transaction(rule, transaction)
