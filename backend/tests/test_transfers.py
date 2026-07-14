from datetime import date, timedelta

from app.models import Account, Category, Transaction, TransferLink
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.services.transfers import confirm_transfer_link, detect_transfer_candidates, list_payment_verification, score_transfer_match


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


def test_brokerage_ach_uses_seven_day_window():
    accounts = {
        1: Account(id=1, display_name="Checking", account_type="checking"),
        2: Account(id=2, display_name="Brokerage", account_type="brokerage"),
    }
    left = _transaction(1, -25000, date(2026, 7, 1), "ACH to brokerage")
    right = _transaction(2, 25000, date(2026, 7, 8), "ACH contribution")
    assert score_transfer_match(left, right, accounts) is not None


def test_detection_includes_confirmed_rows_for_common_account_pairs():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        accounts = [
            Account(display_name="Checking", account_type="checking"),
            Account(display_name="Card", account_type="credit_card"),
            Account(display_name="Savings", account_type="savings"),
            Account(display_name="Brokerage", account_type="brokerage"),
        ]
        db.add_all(accounts)
        db.flush()
        rows = [
            _transaction(accounts[0].id, -10000, date(2026, 7, 1), "Card autopay"),
            _transaction(accounts[1].id, 10000, date(2026, 7, 2), "Payment received"),
            _transaction(accounts[0].id, -20000, date(2026, 7, 3), "Savings transfer"),
            _transaction(accounts[2].id, 20000, date(2026, 7, 3), "Transfer in"),
            _transaction(accounts[0].id, -30000, date(2026, 7, 4), "Brokerage ACH"),
            _transaction(accounts[3].id, 30000, date(2026, 7, 11), "ACH contribution"),
        ]
        for index, row in enumerate(rows):
            row.source_hash = f"confirmed-{index}"
            row.review_status = "confirmed"
        db.add_all(rows)
        db.flush()
        candidates = detect_transfer_candidates(db)
        assert len(candidates) == 3
        assert {candidate.suggested_type for candidate in candidates} == {"credit_card_payment", "transfer"}


def test_payment_verification_reports_confirmed_matches_and_stale_unmatched_payments():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        checking = Account(display_name="Checking", account_type="checking")
        card = Account(display_name="Card", account_type="credit_card")
        db.add_all([checking, card])
        db.flush()
        matched_bank = _transaction(checking.id, -10000, date(2026, 7, 1), "Autopay")
        matched_card = _transaction(card.id, 10000, date(2026, 7, 2), "Payment received")
        stale_card = _transaction(card.id, 5000, date(2026, 7, 3), "Online payment")
        for index, transaction in enumerate((matched_bank, matched_card, stale_card)):
            transaction.source_hash = f"payment-{index}"
            transaction.review_status = "confirmed"
            transaction.transaction_type = "credit_card_payment"
        db.add_all([matched_bank, matched_card, stale_card])
        db.flush()
        db.add(TransferLink(from_transaction_id=matched_bank.id, to_transaction_id=matched_card.id, match_confidence=100, confirmed=True))
        db.commit()

        result = list_payment_verification(db, as_of=date(2026, 7, 13))

        assert result[0]["matched_payments"] == 1
        assert result[0]["latest_matched_date"] == "2026-07-02"
        assert [warning["transaction_id"] for warning in result[0]["warnings"]] == [stale_card.id]


def test_confirming_card_payment_clears_categories_on_both_sides():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        checking = Account(display_name="Checking", account_type="checking")
        card = Account(display_name="Card", account_type="credit_card")
        category = Category(key="shopping", label="Shopping")
        db.add_all([checking, card, category])
        db.flush()
        bank_row = _transaction(checking.id, -10000, date(2026, 7, 1), "Autopay")
        card_row = _transaction(card.id, 10000, date(2026, 7, 2), "Payment received")
        bank_row.source_hash = "confirm-payment-bank"
        card_row.source_hash = "confirm-payment-card"
        bank_row.category_id = category.id
        card_row.category_id = category.id
        db.add_all([bank_row, card_row])
        db.flush()
        link = TransferLink(from_transaction_id=bank_row.id, to_transaction_id=card_row.id, match_confidence=100, confirmed=False)
        db.add(link)
        db.commit()

        confirm_transfer_link(db, link)

        assert bank_row.transaction_type == card_row.transaction_type == "credit_card_payment"
        assert bank_row.category_id is None
        assert card_row.category_id is None
