from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Account, ImportBatch, StagingRow
from .importers import commit_import, decode_text, detect_preset_from_content, preview_import, semantic_import_hash, suggest_account_for_import


SUPPORTED_INBOX_SUFFIXES = {".csv"}


def inbox_directory() -> Path:
    folder = settings.import_inbox_dir.expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def scan_import_inbox(db: Session) -> dict:
    folder = inbox_directory()
    max_bytes = settings.import_file_size_limit_mb * 1024 * 1024
    staged: list[dict] = []
    skipped: list[dict] = []
    needs_account: list[dict] = []
    errors: list[dict] = []

    files = sorted((path for path in folder.iterdir() if path.is_file() and path.suffix.casefold() in SUPPORTED_INBOX_SUFFIXES), key=lambda path: path.name.casefold())
    for path in files:
        try:
            if path.stat().st_size > max_bytes:
                errors.append({"filename": path.name, "message": f"File exceeds the {settings.import_file_size_limit_mb} MB limit."})
                continue
            content = path.read_bytes()
            file_hash = hashlib.sha256(content).hexdigest()
            exact_match = db.scalar(select(ImportBatch).where(ImportBatch.file_hash == file_hash).order_by(ImportBatch.id.desc()))
            if exact_match:
                skipped.append({"filename": path.name, "reason": f"Already recorded as {exact_match.status} (same file contents)."})
                continue
            suggestion = suggest_account_for_import(db, path.name, content)
            semantic_hash = semantic_import_hash(content, suggestion.preset_type, path.name)
            existing = db.scalar(select(ImportBatch).where(ImportBatch.semantic_hash == semantic_hash).order_by(ImportBatch.id.desc()))
            if existing:
                skipped.append({"filename": path.name, "reason": f"Already recorded as {existing.status} (same parsed transactions)."})
                continue
            if suggestion.suggested_account_id is None:
                needs_account.append({
                    "filename": path.name,
                    "preset_type": suggestion.preset_type,
                    "reason": suggestion.reason,
                    "proposed_account": suggestion.proposed_account,
                })
                continue

            account = db.get(Account, suggestion.suggested_account_id)
            if not account:
                needs_account.append({"filename": path.name, "preset_type": suggestion.preset_type, "reason": "The matched account no longer exists.", "proposed_account": suggestion.proposed_account})
                continue
            preview = preview_import(content, suggestion.preset_type)
            batch = ImportBatch(
                account_id=account.id,
                preset_id=None,
                filename=path.name,
                file_hash=file_hash,
                semantic_hash=semantic_hash,
                status="pending",
                imported_rows=0,
                skipped_duplicates=0,
                warnings_json=json.dumps(preview.warnings),
                source_path=str(path),
                match_confidence=suggestion.match_confidence,
                match_reason=suggestion.reason,
                proposed_account_json=json.dumps(suggestion.proposed_account),
                detected_preset=suggestion.preset_type,
            )
            db.add(batch)
            db.flush()
            for row in preview.rows:
                db.add(
                    StagingRow(
                        import_batch_id=batch.id,
                        account_id=account.id,
                        row_index=int(row.get("row_index") or 0),
                        row_kind=str(row.get("row_kind") or "transaction"),
                        raw_json=json.dumps(row, default=str),
                        normalized_json=json.dumps(row, default=str),
                    )
                )
            staged.append({"batch_id": batch.id, "filename": path.name, "account_id": account.id, "row_count": len(preview.rows)})
        except (OSError, ValueError) as error:
            errors.append({"filename": path.name, "message": str(error)})

    return {
        "folder": str(folder),
        "files_found": len(files),
        "staged": staged,
        "skipped": skipped,
        "needs_account": needs_account,
        "errors": errors,
    }


def stage_uploaded_import(db: Session, *, account: Account, filename: str, content: bytes) -> dict:
    """Copy a manual upload into managed storage and stage it for the same review flow as inbox files."""
    max_bytes = settings.import_file_size_limit_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise ValueError(f"File exceeds the {settings.import_file_size_limit_mb} MB limit.")
    file_hash = hashlib.sha256(content).hexdigest()
    exact_match = db.scalar(select(ImportBatch).where(ImportBatch.file_hash == file_hash).order_by(ImportBatch.id.desc()))
    if exact_match:
        raise ValueError(f"This file is already recorded as {exact_match.status}.")
    preset_type = detect_preset_from_content(decode_text(content), filename)
    if not preset_type:
        raise ValueError("Could not detect this CSV format. Choose a supported CSV or create a reusable column mapping.")
    semantic_hash = semantic_import_hash(content, preset_type, filename)
    semantic_match = db.scalar(select(ImportBatch).where(ImportBatch.semantic_hash == semantic_hash).order_by(ImportBatch.id.desc()))
    if semantic_match:
        raise ValueError(f"These transactions are already recorded as {semantic_match.status}.")
    preview = preview_import(content, preset_type)
    managed_folder = inbox_directory() / ".staged"
    managed_folder.mkdir(parents=True, exist_ok=True)
    safe_suffix = Path(filename).suffix.casefold() if Path(filename).suffix else ".csv"
    source = managed_folder / f"{file_hash}{safe_suffix}"
    source.write_bytes(content)
    batch = ImportBatch(
        account_id=account.id,
        preset_id=None,
        filename=filename,
        file_hash=file_hash,
        semantic_hash=semantic_hash,
        status="pending",
        imported_rows=0,
        skipped_duplicates=0,
        warnings_json=json.dumps(preview.warnings),
        source_path=str(source),
        match_confidence=100,
        match_reason="Account selected during manual upload.",
        proposed_account_json="{}",
        detected_preset=preset_type,
    )
    db.add(batch)
    db.flush()
    for row in preview.rows:
        db.add(
            StagingRow(
                import_batch_id=batch.id,
                account_id=account.id,
                row_index=int(row.get("row_index") or 0),
                row_kind=str(row.get("row_kind") or "transaction"),
                raw_json=json.dumps(row, default=str),
                normalized_json=json.dumps(row, default=str),
            )
        )
    return {"batch_id": batch.id, "filename": filename, "row_count": len(preview.rows), "preset_type": preset_type}


def pending_import_batches(db: Session) -> list[dict]:
    batches = db.scalars(select(ImportBatch).where(ImportBatch.status == "pending").order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())).all()
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.id.in_({batch.account_id for batch in batches}))).all()} if batches else {}
    results = []
    for batch in batches:
        preview_rows = db.scalars(select(StagingRow).where(StagingRow.import_batch_id == batch.id).order_by(StagingRow.row_index.asc()).limit(5)).all()
        account = accounts.get(batch.account_id)
        results.append({
            "id": batch.id,
            "filename": batch.filename,
            "preset_type": batch.detected_preset,
            "account_id": batch.account_id,
            "account_name": account.display_name if account else "Unknown account",
            "account_last_four": account.last_four if account else None,
            "match_confidence": batch.match_confidence,
            "match_reason": batch.match_reason,
            "row_count": db.query(StagingRow).filter(StagingRow.import_batch_id == batch.id).count(),
            "warnings": json.loads(batch.warnings_json or "[]"),
            "preview": [json.loads(row.normalized_json) for row in preview_rows],
            "created_at": batch.created_at.isoformat(),
        })
    return results


def confirm_pending_import(db: Session, batch: ImportBatch, actor: str) -> dict:
    if batch.status != "pending":
        raise ValueError("Only pending inbox imports can be confirmed")
    source = _validated_source_path(batch)
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != batch.file_hash:
        raise ValueError("The source file changed after it was staged. Discard this batch and scan again.")
    account = db.get(Account, batch.account_id)
    if not account:
        raise ValueError("The matched account no longer exists")
    return commit_import(db, account, None, batch.filename, content, actor=actor, existing_batch=batch)


def discard_pending_import(batch: ImportBatch) -> dict:
    if batch.status != "pending":
        raise ValueError("Only pending inbox imports can be discarded")
    batch.status = "discarded"
    return {"ok": True}


def _validated_source_path(batch: ImportBatch) -> Path:
    if not batch.source_path:
        raise ValueError("This inbox batch has no source file")
    source = Path(batch.source_path).expanduser().resolve()
    folder = inbox_directory()
    try:
        source.relative_to(folder)
    except ValueError as error:
        raise ValueError("The staged source file is outside the configured import inbox") from error
    if not source.is_file():
        raise ValueError("The staged source file is no longer available")
    return source
