from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, Transaction
from app.services.accounts import cleanup_imported_accounts, infer_account_characterization, infer_last_four
from app.services.importers import _find_or_create_history_account


def test_infer_credit_card_institution_from_account_name():
    boa = infer_account_characterization("BoA Cash 3056")
    chase = infer_account_characterization("Bonvoy Chase")
    citi = infer_account_characterization("Citi Premier")

    assert boa.institution_name == "Bank of America"
    assert boa.account_type == "credit_card"
    assert chase.institution_name == "Chase"
    assert chase.account_type == "credit_card"
    assert citi.institution_name == "Citi"
    assert citi.account_type == "credit_card"


def test_infer_preserves_brokeragelink_as_brokerage():
    brokerage = infer_account_characterization("Brokeragelink", current_type="brokerage")

    assert brokerage.account_type == "brokerage"
    assert brokerage.institution_name is None


def test_infer_last_four_from_account_name_ignores_years():
    assert infer_last_four("BoA Cash 3970 (premium rewards)") == "3970"
    assert infer_last_four("Chase Freedom (2025, prev csp)") is None


def test_categorized_history_account_creation_uses_inferred_metadata():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        account, created = _find_or_create_history_account(session, "Discover")

        assert created is True
        assert account.account_type == "credit_card"
        assert account.institution.name == "Discover"


def test_cleanup_imported_accounts_merges_case_duplicates_and_recharacterizes_cards():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        checkings = Account(display_name="Checkings", account_type="checking")
        duplicate_checkings = Account(display_name="checkings", account_type="checking")
        boa = Account(display_name="BoA Cash 3056", account_type="checking")
        session.add_all([checkings, duplicate_checkings, boa])
        session.flush()
        session.add(
            Transaction(
                account_id=duplicate_checkings.id,
                transaction_date=date(2026, 1, 1),
                amount_cents=100,
                raw_description="Opening",
                transaction_type="income",
                review_status="confirmed",
                source_hash="source-1",
            )
        )
        session.commit()

        result = cleanup_imported_accounts(session)
        accounts = session.scalars(select(Account).order_by(Account.display_name)).all()
        cleaned_checkings = session.scalar(select(Account).where(Account.display_name == "Checkings"))
        moved_transaction = session.scalar(select(Transaction).where(Transaction.source_hash == "source-1"))
        cleaned_boa = session.scalar(select(Account).where(Account.display_name == "BoA Cash 3056"))

        assert result["merged"] == 1
        assert [account.display_name for account in accounts] == ["BoA Cash 3056", "Checkings"]
        assert moved_transaction.account_id == cleaned_checkings.id
        assert cleaned_boa.account_type == "credit_card"
        assert cleaned_boa.institution.name == "Bank of America"
        assert cleaned_boa.last_four == "3056"
