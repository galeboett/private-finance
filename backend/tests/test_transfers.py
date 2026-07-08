from datetime import date, timedelta

from app.models import Account, Transaction
from app.services.transfers import score_transfer_match


def _transaction(account_id: int, amount_cents: int, transaction_date: date, description: str = "Transfer") -> Transaction:
    return Transaction(
        account_id=account_id,
        transaction_date=transaction_date,
        amount_cents=amount_cents,
        raw_description=description,
        transaction_type="expense",
        review_status="needs_review",
        source_hash=f"{account_id}-{amount_cents}-{transaction_date.isoformat()}",
        source_ordinal=1,
    )


def test_scores_equal_and_opposite_transfer_within_window():
    accounts = {
        1: Account(id=1, display_name="Checking", account_type="checking"),
        2: Account(id=2, display_name="Savings", account_type="savings"),
    }
    left = _transaction(1, -25000, date(2026, 7, 1), "ACH transfer out")
    right = _transaction(2, 25000, date(2026, 7, 3), "ACH transfer in")

    scored = score_transfer_match(left, right, accounts)

    assert scored is not None
    confidence, suggested_type = scored
    assert confidence >= 80
    assert suggested_type == "transfer"


def test_scores_credit_card_payment_when_one_side_is_card_account():
    accounts = {
        1: Account(id=1, display_name="Checking", account_type="checking"),
        2: Account(id=2, display_name="Card", account_type="credit_card"),
    }
    left = _transaction(1, -10000, date(2026, 7, 1), "Autopay credit card")
    right = _transaction(2, 10000, date(2026, 7, 1), "Payment received")

    scored = score_transfer_match(left, right, accounts)

    assert scored is not None
    assert scored[1] == "credit_card_payment"


def test_rejects_same_account_and_outside_date_window():
    accounts = {
        1: Account(id=1, display_name="Checking", account_type="checking"),
        2: Account(id=2, display_name="Savings", account_type="savings"),
    }
    left = _transaction(1, -25000, date(2026, 7, 1))

    assert score_transfer_match(left, _transaction(1, 25000, date(2026, 7, 1)), accounts) is None
    assert score_transfer_match(left, _transaction(2, 25000, date(2026, 7, 1) + timedelta(days=8)), accounts) is None
