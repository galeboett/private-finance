from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base
from app.models import Account, HoldingSnapshot, ImportBatch, ImportSignProfile, Institution, Operation, StagingRow, Transaction
from app.services.import_inbox import confirm_pending_import, discard_pending_import, pending_import_batches, scan_import_inbox, stage_uploaded_import
from app.services.importers import commit_import


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


def test_scan_restages_committed_positions_file_when_it_can_fill_missing_cost_basis(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    content = (
        b'"Positions for account Individual ...373 as of 03:44 AM ET, 2026/07/14"\n\n'
        b'"Symbol","Description","Qty (Quantity)","Price","Mkt Val (Market Value)","Cost Basis","Asset Type",\n'
        b'"VOO","VANGUARD S&P 500 ETF","94.527","688.50","$65,081.84","$42,361.99","ETF",\n'
    )
    source = tmp_path / "Individual-Positions-2026-07-14-034412.csv"
    source.write_bytes(content)
    engine = _database()
    with Session(engine) as db:
        account = Account(display_name="CS Investment Account", account_type="brokerage", last_four="373")
        db.add(account)
        db.commit()

        commit_import(db, account, None, source.name, content, actor="user:7")
        db.commit()
        holding = db.scalar(select(HoldingSnapshot))
        assert holding.cost_basis_cents == 4236199

        holding.cost_basis_cents = None
        db.commit()
        enrichment_scan = scan_import_inbox(db)
        assert len(enrichment_scan["staged"]) == 1
        assert enrichment_scan["skipped"] == []
        enrichment_batch = db.get(ImportBatch, enrichment_scan["staged"][0]["batch_id"])
        assert "fill missing cost basis" in enrichment_batch.warnings_json

        confirm_pending_import(db, enrichment_batch, "user:7")
        db.commit()
        refreshed = db.scalar(select(HoldingSnapshot))
        assert refreshed.cost_basis_cents == 4236199
        assert scan_import_inbox(db)["skipped"][0]["reason"].startswith("Already recorded as committed")


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


def test_account_subfolders_route_generic_statement_names_by_last_four(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    first_folder = tmp_path / "boa-checking-1016"
    second_folder = tmp_path / "boa-checking-6768"
    first_folder.mkdir()
    second_folder.mkdir()
    checking_csv = b"Date,Description,Amount,Running Bal.\n07/10/2026,Deposit,100.00,100.00\n"
    (first_folder / "stmt.csv").write_bytes(checking_csv)
    (second_folder / "stmt (1).csv").write_bytes(checking_csv.replace(b"100.00", b"200.00"))
    engine = _database()
    with Session(engine) as db:
        institution = Institution(name="Bank of America")
        first = Account(institution=institution, display_name="Checkings", account_type="checking", last_four="1016")
        second = Account(institution=institution, display_name="Checkings", account_type="checking", last_four="6768")
        db.add_all([first, second])
        db.commit()

        result = scan_import_inbox(db)

        assert result["files_found"] == 2
        assert result["needs_account"] == []
        assert {row["filename"] for row in result["staged"]} == {"boa-checking-1016/stmt.csv", "boa-checking-6768/stmt (1).csv"}
        batches = db.scalars(select(ImportBatch).order_by(ImportBatch.filename)).all()
        assert [(batch.filename, batch.account_id) for batch in batches] == [
            ("boa-checking-1016/stmt.csv", first.id),
            ("boa-checking-6768/stmt (1).csv", second.id),
        ]


def test_manual_stage_can_reverse_detected_amount_signs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    engine = _database()
    with Session(engine) as db:
        account = _matching_account(db)
        result = stage_uploaded_import(db, account=account, filename="manual-card.csv", content=CARD_CSV, sign_convention="reverse")
        batch = db.get(ImportBatch, result["batch_id"])

        assert batch.sign_convention == "reverse"
        assert pending_import_batches(db)[0]["preview"][0]["amount"] == "42.50"
        assert pending_import_batches(db)[0]["preview"][0]["interpreted_transaction_type"] == "refund"

        confirm_pending_import(db, batch, "user:7")
        db.commit()
        transaction = db.scalar(select(Transaction))
        assert transaction.amount_cents == 4250
        assert transaction.transaction_type == "refund"


def test_manual_stage_uses_saved_sign_profile_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "import_inbox_dir", tmp_path)
    engine = _database()
    with Session(engine) as db:
        account = _matching_account(db)
        db.add(ImportSignProfile(account_id=account.id, preset_type="card_activity", sign_convention="reverse_detected", decided_by="user"))
        db.flush()

        result = stage_uploaded_import(db, account=account, filename="manual-card.csv", content=CARD_CSV)
        batch = db.get(ImportBatch, result["batch_id"])
        pending = pending_import_batches(db)[0]

        assert batch.sign_convention == "reverse"
        assert pending["preview"][0]["amount"] == "42.50"
        assert pending["sign_decision"]["using_saved_profile"] is True
        assert pending["sign_decision"]["profile"]["sign_convention"] == "reverse_detected"
