from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Account, ImportBatch, StagingRow
from .importers import (
    PreviewResult,
    annotate_import_interpretation,
    commit_import,
    decode_text,
    detect_preset_from_content,
    preview_import,
    semantic_import_hash,
    suggest_account_for_import,
)
from .sign_profiles import get_sign_profile, profile_payload, resolution_payload, resolve_sign_preview


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

    files = sorted(
        (
            path
            for path in folder.rglob("*")
            if path.is_file()
            and path.suffix.casefold() in SUPPORTED_INBOX_SUFFIXES
            and ".staged" not in path.relative_to(folder).parts
        ),
        key=lambda path: path.relative_to(folder).as_posix().casefold(),
    )
    for path in files:
        relative_name = path.relative_to(folder).as_posix()
        try:
            if path.stat().st_size > max_bytes:
                errors.append({"filename": relative_name, "message": f"File exceeds the {settings.import_file_size_limit_mb} MB limit."})
                continue
            content = path.read_bytes()
            file_hash = hashlib.sha256(content).hexdigest()
            exact_match = db.scalar(select(ImportBatch).where(ImportBatch.file_hash == file_hash).order_by(ImportBatch.id.desc()))
            if exact_match:
                skipped.append({"filename": relative_name, "reason": f"Already recorded as {exact_match.status} (same file contents)."})
                continue
            suggestion = suggest_account_for_import(db, relative_name, content)
            semantic_hash = semantic_import_hash(content, suggestion.preset_type, relative_name)
            existing = db.scalar(select(ImportBatch).where(ImportBatch.semantic_hash == semantic_hash).order_by(ImportBatch.id.desc()))
            if existing:
                skipped.append({"filename": relative_name, "reason": f"Already recorded as {existing.status} (same parsed transactions)."})
                continue
            if suggestion.suggested_account_id is None:
                needs_account.append({
                    "filename": relative_name,
                    "preset_type": suggestion.preset_type,
                    "reason": suggestion.reason,
                    "proposed_account": suggestion.proposed_account,
                })
                continue

            account = db.get(Account, suggestion.suggested_account_id)
            if not account:
                needs_account.append({"filename": relative_name, "preset_type": suggestion.preset_type, "reason": "The matched account no longer exists.", "proposed_account": suggestion.proposed_account})
                continue
            raw_preview = preview_import(content, suggestion.preset_type)
            sign_resolution = resolve_sign_preview(db, account=account, preset_type=suggestion.preset_type, preview=raw_preview)
            preview = annotate_import_interpretation(sign_resolution.preview, account)
            warnings = list(preview.warnings)
            if sign_resolution.requires_confirmation:
                warnings.append("The amount signs do not match the saved or detected convention. Review the examples before confirming this import.")
            batch = ImportBatch(
                account_id=account.id,
                preset_id=None,
                filename=relative_name,
                file_hash=file_hash,
                semantic_hash=semantic_hash,
                status="pending",
                imported_rows=0,
                skipped_duplicates=0,
                warnings_json=json.dumps(warnings),
                source_path=str(path),
                match_confidence=suggestion.match_confidence,
                match_reason=suggestion.reason,
                proposed_account_json=json.dumps(suggestion.proposed_account),
                detected_preset=suggestion.preset_type,
                sign_convention=sign_resolution.sign_convention,
            )
            db.add(batch)
            db.flush()
            for raw_row, row in zip(raw_preview.rows, preview.rows, strict=True):
                db.add(
                    StagingRow(
                        import_batch_id=batch.id,
                        account_id=account.id,
                        row_index=int(row.get("row_index") or 0),
                        row_kind=str(row.get("row_kind") or "transaction"),
                        raw_json=json.dumps(raw_row, default=str),
                        normalized_json=json.dumps(row, default=str),
                    )
                )
            staged.append({"batch_id": batch.id, "filename": relative_name, "account_id": account.id, "row_count": len(preview.rows)})
        except (OSError, ValueError) as error:
            errors.append({"filename": relative_name, "message": str(error)})

    return {
        "folder": str(folder),
        "files_found": len(files),
        "staged": staged,
        "skipped": skipped,
        "needs_account": needs_account,
        "errors": errors,
    }


def stage_uploaded_import(db: Session, *, account: Account, filename: str, content: bytes, sign_convention: str = "auto") -> dict:
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
    raw_preview = preview_import(content, preset_type)
    sign_resolution = resolve_sign_preview(db, account=account, preset_type=preset_type, preview=raw_preview, requested=sign_convention)
    preview = annotate_import_interpretation(sign_resolution.preview, account)
    warnings = list(preview.warnings)
    if sign_resolution.requires_confirmation:
        warnings.append("The amount signs do not match the saved or detected convention. Review the examples before confirming this import.")
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
        warnings_json=json.dumps(warnings),
        source_path=str(source),
        match_confidence=100,
        match_reason="Account selected during manual upload.",
        proposed_account_json="{}",
        detected_preset=preset_type,
        sign_convention=sign_resolution.sign_convention,
    )
    db.add(batch)
    db.flush()
    for raw_row, row in zip(raw_preview.rows, preview.rows, strict=True):
        db.add(
            StagingRow(
                import_batch_id=batch.id,
                account_id=account.id,
                row_index=int(row.get("row_index") or 0),
                row_kind=str(row.get("row_kind") or "transaction"),
                raw_json=json.dumps(raw_row, default=str),
                normalized_json=json.dumps(row, default=str),
            )
        )
    return {"batch_id": batch.id, "filename": filename, "row_count": len(preview.rows), "preset_type": preset_type, "sign_convention": sign_resolution.sign_convention, "sign_decision": resolution_payload(sign_resolution)}


def pending_import_batches(db: Session) -> list[dict]:
    batches = db.scalars(select(ImportBatch).where(ImportBatch.status == "pending").order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())).all()
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.id.in_({batch.account_id for batch in batches}))).all()} if batches else {}
    results = []
    for batch in batches:
        all_staging_rows = db.scalars(select(StagingRow).where(StagingRow.import_batch_id == batch.id).order_by(StagingRow.row_index.asc())).all()
        preview_rows = all_staging_rows[:5]
        account = accounts.get(batch.account_id)
        raw_preview = PreviewResult(rows=[json.loads(row.raw_json) for row in all_staging_rows], warnings=[], detected_preset=batch.detected_preset)
        sign_resolution = resolve_sign_preview(db, account=account, preset_type=batch.detected_preset or "unknown", preview=raw_preview, requested=batch.sign_convention or "preset") if account else None
        saved_profile = get_sign_profile(db, batch.account_id, batch.detected_preset or "unknown")
        results.append({
            "id": batch.id,
            "filename": batch.filename,
            "preset_type": batch.detected_preset,
            "sign_convention": batch.sign_convention or "preset",
            "account_id": batch.account_id,
            "account_name": account.display_name if account else "Unknown account",
            "account_last_four": account.last_four if account else None,
            "match_confidence": batch.match_confidence,
            "match_reason": batch.match_reason,
            "row_count": db.query(StagingRow).filter(StagingRow.import_batch_id == batch.id).count(),
            "warnings": json.loads(batch.warnings_json or "[]"),
            "preview": [json.loads(row.normalized_json) for row in preview_rows],
            "created_at": batch.created_at.isoformat(),
            "sign_decision": ({**resolution_payload(sign_resolution), "profile": profile_payload(saved_profile) if saved_profile else None, "using_saved_profile": saved_profile is not None} if sign_resolution else None),
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
    return commit_import(db, account, None, batch.filename, content, actor=actor, existing_batch=batch, sign_convention=batch.sign_convention or "preset")


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
