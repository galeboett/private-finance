from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import Base
from app.api.imports import list_import_settings_metadata
from app.models import Account, ImportPreset, ImportSignProfile, Institution, SessionToken, StatementPdfPattern


def test_import_settings_metadata_names_saved_mapping_sign_and_pdf_choices():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        bank = Institution(name="Example Bank")
        card = Account(institution=bank, display_name="Example Card", account_type="credit_card")
        db.add_all([bank, card])
        db.flush()
        db.add_all([
            ImportPreset(account_id=card.id, name="Example CSV", preset_type="generic_csv", header_signature="date,amount", config_json="{}"),
            ImportSignProfile(account_id=card.id, preset_type="generic_csv", sign_convention="reverse_detected", decided_by="user"),
            StatementPdfPattern(institution_id=bank.id, balance_label="New balance", date_label="Closing date"),
        ])
        db.flush()

        result = list_import_settings_metadata(SessionToken(user_id=1, csrf_token="csrf"), db)

        assert result["csv_mappings"][0]["account"] == "Example Card"
        assert result["sign_profiles"][0]["account"] == "Example Card"
        assert result["pdf_patterns"][0] == {
            "id": result["pdf_patterns"][0]["id"],
            "institution_id": bank.id,
            "institution": "Example Bank",
            "balance_label": "New balance",
            "date_label": "Closing date",
        }
