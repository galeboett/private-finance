from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, AccountIdentifier, Institution
from app.services.account_identifiers import matching_accounts_for_last_four, record_account_identifier
from app.services.importers import suggest_account_for_import


CARD_CSV = b"Posted Date,Reference Number,Payee,Address,Amount\n05/01/2026,123,Store,Addr,-12.34\n"


def test_replacement_card_preserves_old_suffix_as_an_import_alias():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        institution = Institution(name="Chase")
        session.add(institution)
        session.flush()
        account = Account(
            institution_id=institution.id,
            display_name="Chase Freedom",
            account_type="credit_card",
            last_four="1234",
        )
        session.add(account)
        session.flush()
        record_account_identifier(session, account, "1234", source="backfill")

        suggestion = suggest_account_for_import(session, "Chase5678_Activity.csv", CARD_CSV)

        assert suggestion.suggested_account_id is None
        assert suggestion.replacement_candidate_id == account.id

        record_account_identifier(session, account, "5678", source="import_confirmation")
        session.commit()

        identifiers = session.scalars(
            select(AccountIdentifier).where(AccountIdentifier.account_id == account.id).order_by(AccountIdentifier.identifier_value)
        ).all()
        assert [(row.identifier_value, row.is_current) for row in identifiers] == [("1234", False), ("5678", True)]
        assert matching_accounts_for_last_four(session, [account], "1234") == [account]
        assert matching_accounts_for_last_four(session, [account], "5678") == [account]

        old_statement = suggest_account_for_import(session, "Chase1234_Activity.csv", CARD_CSV)
        new_statement = suggest_account_for_import(session, "Chase5678_Activity.csv", CARD_CSV)
        assert old_statement.suggested_account_id == account.id
        assert new_statement.suggested_account_id == account.id
