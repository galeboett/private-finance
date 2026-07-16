from datetime import date

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.bootstrap import migrate_category_rules_for_optional_category
from app.db import Base
from app.main import apply_rule, apply_rule_to_row, apply_rule_to_transaction, create_rule, rule_matches_transaction
from app.models import Account, Category, CategoryRule, PaymentVerificationDismissal, SessionToken, Transaction
from app.schemas import RuleApplyRequest, RuleCreate, TransactionType


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

def test_apply_rule_to_transaction_confirms_match():
    rule = CategoryRule(category_id=7, field_name="raw_description", match_text="coffee", suggested_transaction_type="expense")
    transaction = Transaction(
        account_id=1,
        transaction_date=date(2026, 7, 1),
        amount_cents=-525,
        raw_description="coffee",
        transaction_type="income",
        review_status="suggested",
        source_hash="hash",
        source_ordinal=1,
    )

    assert apply_rule_to_transaction(rule, transaction)
    assert transaction.category_id == 7
    assert transaction.transaction_type == "expense"
    assert transaction.review_status == "confirmed"


def test_card_payment_rule_needs_no_category_and_clears_existing_category():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        account = Account(display_name="Card", account_type="credit_card")
        category = Category(key="shopping", label="Shopping")
        db.add_all([account, category])
        db.flush()
        transaction = Transaction(account_id=account.id, category_id=category.id, transaction_date=date(2026, 7, 4), amount_cents=149335, raw_description="AUTOPAY PAYMENT - THANK YOU", transaction_type="refund", review_status="needs_review", source_hash="card-payment-rule")
        db.add(transaction)
        db.commit()
        request = Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})
        session = SessionToken(user_id=7, csrf_token="csrf")

        created = create_rule(RuleCreate(category_id=None, field_name="raw_description", match_text="AUTOPAY PAYMENT", suggested_transaction_type=TransactionType.CREDIT_CARD_PAYMENT), request, session, db)
        rule = db.get(CategoryRule, created["id"])
        result = apply_rule(rule.id, RuleApplyRequest(scope="unreviewed"), request, session, db)

        assert rule.category_id is None
        assert result["updated"] == 1
        assert transaction.category_id is None
        assert transaction.transaction_type == "credit_card_payment"
        assert transaction.review_status == "confirmed"


def test_refund_rule_requires_and_applies_category():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        card = Account(display_name="Card", account_type="credit_card")
        shopping = Category(key="shopping-refund", label="Shopping")
        db.add_all([card, shopping])
        db.flush()
        refund = Transaction(account_id=card.id, transaction_date=date(2026, 7, 8), amount_cents=2500, raw_description="ACME RETURN", transaction_type="income", review_status="needs_review", source_hash="refund-rule")
        db.add(refund)
        db.commit()
        request = Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})
        session = SessionToken(user_id=7, csrf_token="csrf")

        created = create_rule(RuleCreate(category_id=shopping.id, field_name="raw_description", match_text="ACME RETURN", suggested_transaction_type=TransactionType.REFUND), request, session, db)
        result = apply_rule(created["id"], RuleApplyRequest(scope="unreviewed"), request, session, db)

        assert result["updated"] == 1
        assert refund.transaction_type == "refund"
        assert refund.category_id == shopping.id
        assert refund.review_status == "confirmed"


def test_apply_rule_to_one_row_confirms_and_journals_reclassification_dismissal():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        card = Account(display_name="Card", account_type="credit_card")
        category = Category(key="fees", label="Fees")
        db.add_all([card, category])
        db.flush()
        transaction = Transaction(account_id=card.id, transaction_date=date(2026, 7, 1), amount_cents=2900, raw_description="ONLINE PAYMENT FEE", transaction_type="credit_card_payment", review_status="needs_review", source_hash="rule-one-row")
        rule = CategoryRule(category_id=category.id, field_name="raw_description", match_text="ONLINE PAYMENT FEE", suggested_transaction_type="expense", priority=100)
        db.add_all([transaction, rule])
        db.commit()
        request = Request({"type": "http", "headers": [(b"x-csrf-token", b"csrf")]})
        session = SessionToken(user_id=7, csrf_token="csrf")

        result = apply_rule_to_row(rule.id, transaction.id, request, session, db)

        assert result["updated"] == 1
        assert result["operation_id"]
        assert transaction.transaction_type == "expense"
        assert transaction.category_id == category.id
        assert transaction.review_status == "confirmed"
        assert db.scalar(select(PaymentVerificationDismissal).where(PaymentVerificationDismissal.transaction_id == transaction.id)) is not None


def test_existing_category_rules_table_migrates_to_nullable_category():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE categories (id INTEGER NOT NULL PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE category_rules (id INTEGER NOT NULL PRIMARY KEY, category_id INTEGER NOT NULL REFERENCES categories(id), priority INTEGER NOT NULL, field_name VARCHAR(40) NOT NULL, match_text VARCHAR(255) NOT NULL, suggested_transaction_type VARCHAR(40) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        connection.execute(text("INSERT INTO categories (id) VALUES (1)"))
        connection.execute(text("INSERT INTO category_rules VALUES (1, 1, 100, 'raw_description', 'COFFEE', 'expense', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))

        migrate_category_rules_for_optional_category(connection)
        connection.execute(text("INSERT INTO category_rules (id, category_id, priority, field_name, match_text, suggested_transaction_type, created_at, updated_at) VALUES (2, NULL, 100, 'raw_description', 'AUTOPAY', 'credit_card_payment', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))

        category_column = next(column for column in inspect(connection).get_columns("category_rules") if column["name"] == "category_id")
        assert category_column["nullable"] is True
        assert connection.execute(text("SELECT COUNT(*) FROM category_rules")).scalar_one() == 2
