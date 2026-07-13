from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.models import Account, ImportBatch, Institution, Operation, StagingRow, Transaction
from app.services.import_inbox import confirm_pending_import, discard_pending_import, pending_import_batches, scan_import_inbox, stage_uploaded_import


CARD_CSV = b"Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n07/10/2026,07/11/2026,Market,Shopping,Sale,-42.50,\n"
CARD_CSV_FORMAT_VARIANT = b"\xef\xbb\xbfTransaction Date,Post Date,Description,Category,Type,Amount,Memo\r\n07/10/2026,07/11/2026,Market,Shopping,Sale,-42.50,\r\n\r\n"
GENERIC_MAPPED_CSV = b"PF Date,PF Description,PF Amount\n2026-07-09,Local Cafe,-12.34\n"


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def _matching_account(db: Session) -> Account:
    institution = Institution(name="Chase")
    account = Account(institution=institution, display_name="Chase Sapphire", account_type="credit_card", last_four="1234")
    db.add(account)
    db.commit()
    return account


def test_scan_stages_matched_file_confirm_journals_import_and_keeps_source(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    source = tmp_path / "chase_sapphire_1234.csv"
    source.write_bytes(CARD_CSV)
    engine = _database()
    with Session(engine) as db:
        account = _matching_account(db)

        scan = scan_import_inbox(db)
        db.commit()
        assert scan["files_found"] == 1
        assert len(scan["staged"]) == 1
        assert scan["needs_account"] == []
        batch = db.get(ImportBatch, scan["staged"][0]["batch_id"])
        assert batch.status == "pending"
        assert batch.account_id == account.id
        assert db.scalar(select(StagingRow).where(StagingRow.import_batch_id == batch.id)) is not None
        assert pending_import_batches(db)[0]["preview"][0]["raw_description"] == "Market"

        result = confirm_pending_import(db, batch, "user:7")
        db.commit()
        assert result["inserted"] == 1
        assert result["operation_id"]
        assert batch.status == "committed"
        assert db.scalar(select(Transaction).where(Transaction.import_batch_id == batch.id)).raw_description == "Market"
        operation = db.get(Operation, result["operation_id"])
        assert operation.kind == "import"
        assert operation.actor == "user:7"
        assert source.exists()

        rescanned = scan_import_inbox(db)
        assert len(rescanned["skipped"]) == 1
        assert rescanned["staged"] == []


def test_unmatched_file_is_reported_without_creating_a_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    (tmp_path / "unknown.csv").write_bytes(CARD_CSV)
    engine = _database()
    with Session(engine) as db:
        result = scan_import_inbox(db)
        assert len(result["needs_account"]) == 1
        assert db.scalar(select(ImportBatch)) is None


def test_discard_keeps_source_and_prevents_the_same_fingerprint_from_restaging(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    source = tmp_path / "chase_sapphire_1234.csv"
    source.write_bytes(CARD_CSV)
    engine = _database()
    with Session(engine) as db:
        _matching_account(db)
        scan = scan_import_inbox(db)
        batch = db.get(ImportBatch, scan["staged"][0]["batch_id"])
        assert discard_pending_import(batch) == {"ok": True}
        db.commit()

        assert batch.status == "discarded"
        assert source.exists()
        assert scan_import_inbox(db)["skipped"][0]["reason"] == "Already recorded as discarded (same file contents)."


def test_manual_upload_uses_the_pending_review_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    engine = _database()
    with Session(engine) as db:
        account = _matching_account(db)
        result = stage_uploaded_import(db, account=account, filename="manual-card.csv", content=CARD_CSV)
        db.commit()

        batch = db.get(ImportBatch, result["batch_id"])
        assert batch.status == "pending"
        assert batch.match_confidence == 100
        assert batch.source_path and (tmp_path / ".staged" / f"{batch.file_hash}.csv").exists()
        assert pending_import_batches(db)[0]["account_name"] == "Chase Sapphire"
        assert db.scalar(select(Transaction)) is None

        committed = confirm_pending_import(db, batch, "user:7")
        db.commit()
        assert committed["inserted"] == 1
        assert db.scalar(select(Transaction)).raw_description == "Market"


def test_mapped_generic_csv_can_be_staged_and_confirmed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    engine = _database()
    with Session(engine) as db:
        account = _matching_account(db)
        staged = stage_uploaded_import(db, account=account, filename="mapped-custom.csv", content=GENERIC_MAPPED_CSV)
        batch = db.get(ImportBatch, staged["batch_id"])
        assert batch.detected_preset == "generic_mapped"

        result = confirm_pending_import(db, batch, "user:7")
        db.commit()
        transaction = db.scalar(select(Transaction))
        assert result["inserted"] == 1
        assert transaction.raw_description == "Local Cafe"
        assert transaction.amount_cents == -1234


def test_confirmation_rejects_a_file_changed_after_staging(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    source = tmp_path / "chase_sapphire_1234.csv"
    source.write_bytes(CARD_CSV)
    engine = _database()
    with Session(engine) as db:
        _matching_account(db)
        scan = scan_import_inbox(db)
        batch = db.get(ImportBatch, scan["staged"][0]["batch_id"])
        source.write_bytes(CARD_CSV + b"07/12/2026,07/12/2026,Cafe,Dining,Sale,-9.00,\n")

        try:
            confirm_pending_import(db, batch, "user:7")
        except ValueError as error:
            assert "changed after it was staged" in str(error)
        else:
            raise AssertionError("Confirmation should reject changed source files")


def test_download_suffix_and_harmless_csv_formatting_still_count_as_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    (tmp_path / "May2026_1234.csv").write_bytes(CARD_CSV)
    (tmp_path / "May2026_1234 (1).csv").write_bytes(CARD_CSV_FORMAT_VARIANT)
    engine = _database()
    with Session(engine) as db:
        _matching_account(db)
        result = scan_import_inbox(db)

        assert len(result["staged"]) == 1
        assert len(result["skipped"]) == 1
        assert "same parsed transactions" in result["skipped"][0]["reason"]


def test_similarly_named_downloads_with_different_rows_are_both_staged(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    (tmp_path / "May2026_1234.csv").write_bytes(CARD_CSV)
    (tmp_path / "May2026_1234 (1).csv").write_bytes(CARD_CSV.replace(b"-42.50", b"-52.50"))
    engine = _database()
    with Session(engine) as db:
        _matching_account(db)
        result = scan_import_inbox(db)

        assert len(result["staged"]) == 2
        assert result["skipped"] == []
