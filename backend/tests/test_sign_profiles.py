from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Account, ImportSignProfile, Institution, Operation
from app.services.accounts import merge_account_into
from app.services.importers import PreviewResult
from app.services.operation_history import undo_operation
from app.services.sign_profiles import analyze_sign_distribution, get_sign_profile, resolve_sign_preview, save_sign_profile


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _account(db: Session, account_type: str = "credit_card", name: str = "Card") -> Account:
    institution = Institution(name=f"Bank {name}")
    account = Account(institution=institution, display_name=name, account_type=account_type)
    db.add(account)
    db.flush()
    return account


def _preview(amounts: list[str], description: str = "Purchase") -> PreviewResult:
    return PreviewResult(
        rows=[
            {"row_index": index, "row_kind": "transaction", "transaction_date": "2026-07-01", "raw_description": description, "amount": amount}
            for index, amount in enumerate(amounts, start=1)
        ],
        warnings=[],
        detected_preset="card_activity",
    )


def test_credit_card_heuristic_uses_eighty_five_percent_threshold():
    engine = _database()
    with Session(engine) as db:
        card = _account(db)
        assert analyze_sign_distribution(_preview(["-10"] * 17 + ["5"] * 3), card)["recommended_sign_convention"] == "preset"
        assert analyze_sign_distribution(_preview(["10"] * 17 + ["-5"] * 3), card)["recommended_sign_convention"] == "reverse"
        assert analyze_sign_distribution(_preview(["-10"] * 16 + ["5"] * 4), card)["recommended_sign_convention"] is None


def test_checking_heuristic_only_uses_payroll_like_rows():
    engine = _database()
    with Session(engine) as db:
        checking = _account(db, "checking", "Checking")
        consistent = analyze_sign_distribution(_preview(["2500"], "ACME PAYROLL"), checking)
        contradictory = analyze_sign_distribution(_preview(["-2500"], "DIRECT DEPOSIT ACME"), checking)
        unrelated = analyze_sign_distribution(_preview(["-20"], "Grocery Store"), checking)
        assert consistent["recommended_sign_convention"] == "preset"
        assert contradictory["recommended_sign_convention"] == "reverse"
        assert unrelated["status"] == "insufficient_data"


def test_user_profile_takes_precedence_over_more_specific_auto_profile():
    engine = _database()
    with Session(engine) as db:
        card = _account(db)
        db.add_all([
            ImportSignProfile(account_id=card.id, preset_type=None, sign_convention="canonical_as_detected", decided_by="user"),
            ImportSignProfile(account_id=card.id, preset_type="card_activity", sign_convention="reverse_detected", decided_by="auto_detected"),
        ])
        db.flush()
        profile = get_sign_profile(db, card.id, "card_activity")
        resolution = resolve_sign_preview(db, account=card, preset_type="card_activity", preview=_preview(["-10"]), requested="auto")
        assert profile is not None and profile.decided_by == "user"
        assert resolution.sign_convention == "preset"


def test_saved_profile_anomaly_requires_confirmation_without_silent_flip():
    engine = _database()
    with Session(engine) as db:
        card = _account(db)
        db.add(ImportSignProfile(account_id=card.id, preset_type="card_activity", sign_convention="canonical_as_detected", decided_by="user"))
        db.flush()
        resolution = resolve_sign_preview(db, account=card, preset_type="card_activity", preview=_preview(["10"] * 10), requested="auto")
        assert resolution.sign_convention == "preset"
        assert resolution.preview.rows[0]["amount"] == "10"
        assert resolution.requires_confirmation is True


def test_profile_change_is_journaled_and_undoable():
    engine = _database()
    with Session(engine) as db:
        card = _account(db)
        profile, operation_id = save_sign_profile(
            db,
            account=card,
            preset_type="card_activity",
            sign_convention="reverse_detected",
            actor="user:7",
            sample_note="Confirmed from Jul 2026 statement",
        )
        db.commit()
        assert db.get(Operation, operation_id).entity_type == "import_sign_profile"
        assert profile.sign_convention == "reverse_detected"

        undo_operation(db, operation_id=operation_id, actor="user:7")
        db.commit()
        assert db.scalar(select(ImportSignProfile)) is None


def test_account_merge_preserves_nonconflicting_profiles_and_prefers_target_conflicts():
    engine = _database()
    with Session(engine) as db:
        source = _account(db, name="Source")
        target = _account(db, name="Target")
        db.add_all([
            ImportSignProfile(account_id=source.id, preset_type="card_activity", sign_convention="reverse_detected", decided_by="user"),
            ImportSignProfile(account_id=source.id, preset_type="amex_activity", sign_convention="reverse_detected", decided_by="user"),
            ImportSignProfile(account_id=target.id, preset_type="card_activity", sign_convention="canonical_as_detected", decided_by="user"),
        ])
        db.flush()

        merge_account_into(db, source, target)
        db.commit()

        profiles = db.scalars(select(ImportSignProfile).where(ImportSignProfile.account_id == target.id).order_by(ImportSignProfile.preset_type)).all()
        assert [(profile.preset_type, profile.sign_convention) for profile in profiles] == [
            ("amex_activity", "reverse_detected"),
            ("card_activity", "canonical_as_detected"),
        ]
