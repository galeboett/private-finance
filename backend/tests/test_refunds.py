from datetime import date

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Category, RefundLink, Transaction, TransferLink
from app.schemas import TransactionFilter
from app.services.operation_history import undo_operation
from app.services.refunds import MAX_AUTOMATIC_SUGGESTIONS, OverRefundError, confirm_refund_link, create_manual_refund_link, create_refund_suggestions, detect_refund_candidates, list_manual_refund_candidates, reject_refund_link, score_refund_match
from app.services.transaction_filters import transaction_filter_conditions
from app.services.transfers import detect_transfer_candidates


def _transaction(account_id: int, amount_cents: int, when: date, description: str, source_hash: str) -> Transaction:
    return Transaction(
        account_id=account_id,
        transaction_date=when,
        amount_cents=amount_cents,
        raw_description=description,
        transaction_type="expense",
        review_status="needs_review",
        source_hash=source_hash,
        source_ordinal=1,
    )


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_scores_same_account_partial_refund_with_merchant_overlap():
    account = Account(id=1, display_name="Card", account_type="credit_card")
    expense = _transaction(1, -12000, date(2026, 7, 1), "ACME STORE PURCHASE", "expense")
    refund = _transaction(1, 4500, date(2026, 7, 8), "ACME STORE REFUND", "refund")

    confidence = score_refund_match(expense, refund, {1: account})

    assert confidence is not None
    assert confidence >= 70


def test_score_rejects_autopay_even_when_amount_and_date_match():
    account = Account(id=1, display_name="Card", account_type="credit_card")
    expense = _transaction(1, -149335, date(2026, 7, 1), "AMEX PURCHASE", "expense")
    payment = _transaction(1, 149335, date(2026, 7, 4), "AUTOPAY PAYMENT - THANK YOU", "payment")

    assert score_refund_match(expense, payment, {1: account}) is None


def test_payment_abbreviations_do_not_hide_merchants_containing_same_letters():
    account = Account(id=1, display_name="Card", account_type="credit_card")
    expense = _transaction(1, -12000, date(2026, 7, 1), "COACH STORE PURCHASE", "expense")
    money_back = _transaction(1, 12000, date(2026, 7, 4), "COACH STORE", "money-back")

    assert score_refund_match(expense, money_back, {1: account}) is not None


def test_suggestion_detection_excludes_confirmed_transfer_rows():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        checking = Account(display_name="Checking", account_type="checking")
        db.add_all([card, checking])
        db.flush()
        expense = _transaction(card.id, -10000, date(2026, 7, 1), "ACME", "expense")
        refund = _transaction(card.id, 10000, date(2026, 7, 5), "ACME REFUND", "refund")
        bank = _transaction(checking.id, -10000, date(2026, 7, 5), "ACME PAYMENT", "bank")
        db.add_all([expense, refund, bank])
        db.flush()
        db.add(TransferLink(from_transaction_id=bank.id, to_transaction_id=refund.id, match_confidence=90, confirmed=True))
        db.commit()

        assert detect_refund_candidates(db) == []


def test_confirming_multiple_partial_refunds_copies_category_and_filter_finds_links():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        shopping = Category(key="shopping", label="Shopping")
        db.add_all([card, shopping])
        db.flush()
        expense = _transaction(card.id, -10000, date(2026, 7, 1), "ACME STORE", "expense")
        expense.category_id = shopping.id
        refunds = [
            _transaction(card.id, 2500, date(2026, 7, 3), "ACME RETURN", "refund-1"),
            _transaction(card.id, 3000, date(2026, 7, 6), "ACME RETURN", "refund-2"),
        ]
        db.add_all([expense, *refunds])
        db.flush()
        links = [RefundLink(expense_transaction_id=expense.id, refund_transaction_id=row.id, match_confidence=90, confirmed=False) for row in refunds]
        db.add_all(links)
        db.commit()

        for link in links:
            confirm_refund_link(db, link)

        assert all(row.transaction_type == "refund" and row.category_id == shopping.id and row.review_status == "confirmed" for row in refunds)
        linked_ids = list(db.scalars(select(Transaction.id).where(*transaction_filter_conditions(TransactionFilter(has_refund=True))).order_by(Transaction.id)))
        assert linked_ids == [expense.id, refunds[0].id, refunds[1].id]


def test_over_refund_requires_explicit_confirmation():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        expense = _transaction(card.id, -5000, date(2026, 7, 1), "ACME", "expense")
        first = _transaction(card.id, 4000, date(2026, 7, 2), "ACME REFUND", "refund-1")
        second = _transaction(card.id, 2000, date(2026, 7, 3), "ACME REFUND", "refund-2")
        db.add_all([expense, first, second])
        db.flush()
        first_link = RefundLink(expense_transaction_id=expense.id, refund_transaction_id=first.id, match_confidence=90, confirmed=True)
        second_link = RefundLink(expense_transaction_id=expense.id, refund_transaction_id=second.id, match_confidence=90, confirmed=False)
        db.add_all([first_link, second_link])
        db.commit()

        with pytest.raises(OverRefundError):
            confirm_refund_link(db, second_link)
        result = confirm_refund_link(db, second_link, allow_over_refund=True)

        assert result["would_exceed_expense"] is True
        assert second_link.confirmed is True


def test_suggestions_and_dismissals_are_journaled_and_undoable():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        db.add_all([
            _transaction(card.id, -10000, date(2026, 7, 1), "ACME STORE", "expense"),
            _transaction(card.id, 10000, date(2026, 7, 3), "ACME STORE REFUND", "refund"),
        ])
        db.commit()

        created = create_refund_suggestions(db)
        link = db.scalar(select(RefundLink))
        rejected = reject_refund_link(db, link)

        assert created["created"] == 1
        assert created["operation_id"]
        assert rejected["operation_id"]
        assert db.scalar(select(RefundLink)) is None


def test_confirmed_refunds_are_not_transfer_candidates():
    with _session() as db:
        checking = Account(display_name="Checking", account_type="checking")
        card = Account(display_name="Card", account_type="credit_card")
        db.add_all([checking, card])
        db.flush()
        expense = _transaction(card.id, -10000, date(2026, 7, 1), "ACME STORE", "expense")
        refund = _transaction(card.id, 10000, date(2026, 7, 2), "ACME REFUND", "refund")
        bank = _transaction(checking.id, -10000, date(2026, 7, 2), "CARD PAYMENT", "bank")
        db.add_all([expense, refund, bank])
        db.flush()
        db.add(RefundLink(expense_transaction_id=expense.id, refund_transaction_id=refund.id, match_confidence=100, confirmed=True))
        db.commit()

        assert detect_transfer_candidates(db) == []


def test_undoing_manual_link_removes_link_and_restores_refund_classification():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        expense = _transaction(card.id, -10000, date(2026, 7, 1), "ACME", "expense")
        refund = _transaction(card.id, 10000, date(2026, 7, 2), "ACME REFUND", "refund")
        db.add_all([expense, refund])
        db.commit()

        result = create_manual_refund_link(db, expense_transaction_id=expense.id, refund_transaction_id=refund.id)
        undo_operation(db, operation_id=result["operation_id"], actor="local-user")
        db.commit()

        assert db.scalar(select(RefundLink)) is None
        assert db.get(Transaction, refund.id).transaction_type == "expense"
        assert db.get(Transaction, refund.id).review_status == "needs_review"


def test_manual_picker_only_returns_plausible_refunds_for_selected_expense():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        expense = _transaction(card.id, -200000, date(2026, 7, 1), "COSTCO WHSE #0479", "expense")
        actual_refund = _transaction(card.id, 155094, date(2026, 7, 10), "COSTCO WHSE #0479 MOBILE REFUND", "refund")
        autopay = _transaction(card.id, 149335, date(2026, 7, 4), "AUTOPAY PAYMENT - THANK YOU", "autopay")
        unrelated = _transaction(card.id, 26450, date(2026, 7, 5), "AMAZON MARKETPLACE", "amazon")
        db.add_all([expense, actual_refund, autopay, unrelated])
        db.commit()

        candidates = list_manual_refund_candidates(db, expense_transaction_id=expense.id)

        assert [candidate["id"] for candidate in candidates] == [actual_refund.id]


def test_refresh_removes_runaway_suggestions_and_caps_replacements():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        stale_links = []
        for index in range(MAX_AUTOMATIC_SUGGESTIONS + 15):
            expense = _transaction(card.id, -(10000 + index), date(2026, 7, 1), f"MERCHANT {index} PURCHASE", f"expense-{index}")
            refund = _transaction(card.id, 10000 + index, date(2026, 7, 2), f"MERCHANT {index} REFUND", f"refund-{index}")
            db.add_all([expense, refund])
            db.flush()
            stale_links.append(RefundLink(expense_transaction_id=expense.id, refund_transaction_id=refund.id, match_confidence=70, confirmed=False))
        db.add_all(stale_links)
        db.commit()

        result = create_refund_suggestions(db)

        assert result["removed"] == MAX_AUTOMATIC_SUGGESTIONS + 15
        assert result["created"] == MAX_AUTOMATIC_SUGGESTIONS
        assert result["limited"] is True
        assert db.query(RefundLink).count() == MAX_AUTOMATIC_SUGGESTIONS


def test_refresh_bulk_clears_thousands_of_irrelevant_payment_suggestions():
    with _session() as db:
        card = Account(display_name="Card", account_type="credit_card")
        db.add(card)
        db.flush()
        expense = _transaction(card.id, -149335, date(2026, 7, 1), "AMEX PURCHASE", "expense")
        db.add(expense)
        db.flush()
        payment_count = 3001
        db.execute(insert(Transaction), [
            {
                "account_id": card.id,
                "transaction_date": date(2026, 7, 4),
                "amount_cents": 149335,
                "raw_description": f"AUTOPAY PAYMENT - THANK YOU {index}",
                "transaction_type": "credit_card_payment",
                "review_status": "suggested",
                "source_hash": f"runaway-payment-{index}",
                "source_ordinal": 1,
            }
            for index in range(payment_count)
        ])
        payment_ids = list(db.scalars(select(Transaction.id).where(Transaction.source_hash.like("runaway-payment-%"))))
        db.execute(insert(RefundLink), [
            {
                "expense_transaction_id": expense.id,
                "refund_transaction_id": payment_id,
                "match_confidence": 70,
                "confirmed": False,
            }
            for payment_id in payment_ids
        ])
        db.commit()

        result = create_refund_suggestions(db)

        assert result["removed"] == payment_count
        assert result["created"] == 0
        assert db.query(RefundLink).count() == 0
