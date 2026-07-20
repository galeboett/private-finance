from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Account, ImportBatch, StagingRow
from .importers import (
    AccountImportSuggestion,
    PreviewResult,
    annotate_import_interpretation,
    commit_import,
    decode_text,
    detect_preset_from_content,
    holding_enrichment_available,
    preview_import,
    semantic_import_hash,
    suggest_account_for_import,
)
from .importers_ofx import commit_ofx_import, parse_ofx, semantic_ofx_hash, suggest_ofx_account
from .sign_profiles import analyze_sign_distribution, get_sign_profile, profile_payload, resolution_payload, resolve_sign_preview
from .statement_pdf import (
    commit_pdf_statement,
    extract_statement_pdf,
    saved_pdf_pattern,
    semantic_pdf_hash,
    statement_preview_row,
    suggest_pdf_account,
)
from .pdf_teaching import apply_pdf_templates, cache_pdf_content, forget_pdf_content, templates_for_account


SUPPORTED_INBOX_SUFFIXES = {".csv", ".ofx", ".qfx", ".pdf"}


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
            if path.suffix.casefold() == ".pdf" and exact_match and exact_match.status == "pending" and exact_match.detected_preset == "pdf_statement":
                row_count = _refresh_pending_pdf_preview(db, exact_match, content, relative_name)
                staged.append({"batch_id": exact_match.id, "filename": relative_name, "account_id": exact_match.account_id, "row_count": row_count, "refreshed": True})
                continue
            refreshes_holding_data = bool(exact_match and holding_enrichment_available(db, exact_match, content, relative_name))
            if exact_match and not refreshes_holding_data:
                skipped.append({"filename": relative_name, "reason": f"Already recorded as {exact_match.status} (same file contents)."})
                continue
            is_ofx = path.suffix.casefold() in {".ofx", ".qfx"}
            is_pdf = path.suffix.casefold() == ".pdf"
            if is_ofx:
                suggested_account, match_confidence, match_reason, proposed_account, replacement_candidate_id = suggest_ofx_account(db, content)
                suggestion = AccountImportSuggestion("ofx_statement", suggested_account.id if suggested_account else None, match_confidence, match_reason, proposed_account, [], replacement_candidate_id)
            elif is_pdf:
                pdf_preview = extract_statement_pdf(content, relative_name)
                suggested_account, match_confidence, match_reason, proposed_account, replacement_candidate_id = suggest_pdf_account(db, relative_name, pdf_preview)
                suggestion = AccountImportSuggestion("pdf_statement", suggested_account.id if suggested_account else None, match_confidence, match_reason, proposed_account, pdf_preview.warnings, replacement_candidate_id)
            else:
                suggestion = suggest_account_for_import(db, relative_name, content)
            if refreshes_holding_data and exact_match:
                suggestion.suggested_account_id = exact_match.account_id
                suggestion.match_confidence = 100
                suggestion.reason = "Matched the account from the earlier import so missing holding data can be refreshed."
            semantic_hash = semantic_ofx_hash(content) if is_ofx else semantic_pdf_hash(content) if is_pdf else semantic_import_hash(content, suggestion.preset_type, relative_name)
            existing = db.scalar(select(ImportBatch).where(ImportBatch.semantic_hash == semantic_hash).order_by(ImportBatch.id.desc()))
            if existing and not refreshes_holding_data:
                refreshes_holding_data = holding_enrichment_available(db, existing, content, relative_name)
                if refreshes_holding_data:
                    suggestion.suggested_account_id = existing.account_id
                    suggestion.match_confidence = 100
                    suggestion.reason = "Matched the account from the earlier import so missing holding data can be refreshed."
            if existing and not refreshes_holding_data:
                skipped.append({"filename": relative_name, "reason": f"Already recorded as {existing.status} (same parsed transactions)."})
                continue
            if suggestion.suggested_account_id is None:
                needs_account.append({
                    "filename": relative_name,
                    "preset_type": suggestion.preset_type,
                    "reason": suggestion.reason,
                    "proposed_account": suggestion.proposed_account,
                    "replacement_candidate_id": suggestion.replacement_candidate_id,
                })
                continue

            account = db.get(Account, suggestion.suggested_account_id)
            if not account:
                needs_account.append({"filename": relative_name, "preset_type": suggestion.preset_type, "reason": "The matched account no longer exists.", "proposed_account": suggestion.proposed_account})
                continue
            if is_ofx:
                parsed = parse_ofx(content)
                raw_preview = PreviewResult(rows=parsed.rows, warnings=parsed.warnings, detected_preset="ofx_statement")
                preview = annotate_import_interpretation(raw_preview, account)
                sign_resolution = None
                if analyze_sign_distribution(raw_preview, account).get("status") == "contradicts_detected":
                    preview.warnings.append("OFX amount signs look unusual for this account. OFX signs are imported as provided; verify the preview before confirming.")
            elif is_pdf:
                pattern = saved_pdf_pattern(db, account)
                parsed_pdf = extract_statement_pdf(content, relative_name, preferred_label=pattern.balance_label if pattern else None)
                normalized = apply_pdf_templates(content, templates_for_account(db, account), account, statement_preview_row(parsed_pdf, account))
                raw_preview = PreviewResult(rows=[normalized], warnings=parsed_pdf.warnings, detected_preset="pdf_statement")
                preview = raw_preview
                sign_resolution = None
            else:
                raw_preview = preview_import(content, suggestion.preset_type)
                sign_resolution = resolve_sign_preview(db, account=account, preset_type=suggestion.preset_type, preview=raw_preview)
                preview = annotate_import_interpretation(sign_resolution.preview, account)
            warnings = list(preview.warnings)
            if refreshes_holding_data:
                warnings.append("This positions file was already imported, but it can fill missing cost basis data. Confirm to refresh the holdings.")
            if sign_resolution and sign_resolution.requires_confirmation:
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
                sign_convention=sign_resolution.sign_convention if sign_resolution else "preset",
            )
            db.add(batch)
            db.flush()
            if is_pdf:
                cache_pdf_content(batch.id, content)
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
            if is_pdf and normalized.get("auto_commit_eligible"):
                committed = commit_pdf_statement(db, batch, account, actor="system:pdf-template")
                staged.append({"batch_id": batch.id, "filename": relative_name, "account_id": account.id, "row_count": 1, "auto_committed": True, "operation_id": committed["operation_id"]})
            else:
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
    refreshes_holding_data = bool(exact_match and exact_match.account_id == account.id and holding_enrichment_available(db, exact_match, content, filename))
    if exact_match and not refreshes_holding_data:
        raise ValueError(f"This file is already recorded as {exact_match.status}.")
    is_ofx = Path(filename).suffix.casefold() in {".ofx", ".qfx"}
    is_pdf = Path(filename).suffix.casefold() == ".pdf"
    preset_type = "ofx_statement" if is_ofx else "pdf_statement" if is_pdf else detect_preset_from_content(decode_text(content), filename)
    if not preset_type:
        raise ValueError("Could not detect this file format. Choose a supported CSV, OFX, or QFX file.")
    semantic_hash = semantic_ofx_hash(content) if is_ofx else semantic_pdf_hash(content) if is_pdf else semantic_import_hash(content, preset_type, filename)
    semantic_match = db.scalar(select(ImportBatch).where(ImportBatch.semantic_hash == semantic_hash).order_by(ImportBatch.id.desc()))
    if semantic_match and semantic_match.account_id == account.id and not refreshes_holding_data:
        refreshes_holding_data = holding_enrichment_available(db, semantic_match, content, filename)
    if semantic_match and not refreshes_holding_data:
        raise ValueError(f"These transactions are already recorded as {semantic_match.status}.")
    if is_ofx:
        parsed = parse_ofx(content)
        raw_preview = PreviewResult(rows=parsed.rows, warnings=parsed.warnings, detected_preset="ofx_statement")
        preview = annotate_import_interpretation(raw_preview, account)
        sign_resolution = None
        if analyze_sign_distribution(raw_preview, account).get("status") == "contradicts_detected":
            preview.warnings.append("OFX amount signs look unusual for this account. OFX signs are imported as provided; verify the preview before confirming.")
    elif is_pdf:
        pattern = saved_pdf_pattern(db, account)
        parsed_pdf = extract_statement_pdf(content, filename, preferred_label=pattern.balance_label if pattern else None)
        normalized = apply_pdf_templates(content, templates_for_account(db, account), account, statement_preview_row(parsed_pdf, account))
        raw_preview = PreviewResult(rows=[normalized], warnings=parsed_pdf.warnings, detected_preset="pdf_statement")
        preview = raw_preview
        sign_resolution = None
    else:
        raw_preview = preview_import(content, preset_type)
        sign_resolution = resolve_sign_preview(db, account=account, preset_type=preset_type, preview=raw_preview, requested=sign_convention)
        preview = annotate_import_interpretation(sign_resolution.preview, account)
    warnings = list(preview.warnings)
    if refreshes_holding_data:
        warnings.append("This positions file was already imported, but it can fill missing cost basis data. Confirm to refresh the holdings.")
    if sign_resolution and sign_resolution.requires_confirmation:
        warnings.append("The amount signs do not match the saved or detected convention. Review the examples before confirming this import.")
    managed_folder = inbox_directory() / ".staged"
    managed_folder.mkdir(parents=True, exist_ok=True)
    safe_suffix = Path(filename).suffix.casefold() if Path(filename).suffix else ".csv"
    source = managed_folder / f"{file_hash}{safe_suffix}"
    if not is_pdf:
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
        source_path=None if is_pdf else str(source),
        match_confidence=100,
        match_reason="Account selected during manual upload.",
        proposed_account_json="{}",
        detected_preset=preset_type,
        sign_convention=sign_resolution.sign_convention if sign_resolution else "preset",
    )
    db.add(batch)
    db.flush()
    if is_pdf:
        cache_pdf_content(batch.id, content)
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
    if is_pdf and normalized.get("auto_commit_eligible"):
        committed = commit_pdf_statement(db, batch, account, actor="system:pdf-template")
        return {"batch_id": batch.id, "filename": filename, "row_count": 1, "preset_type": preset_type, "auto_committed": True, "operation_id": committed["operation_id"], "sign_convention": "preset", "sign_decision": None}
    return {"batch_id": batch.id, "filename": filename, "row_count": len(preview.rows), "preset_type": preset_type, "sign_convention": sign_resolution.sign_convention if sign_resolution else "preset", "sign_decision": resolution_payload(sign_resolution) if sign_resolution else None}


def pending_import_batches(db: Session) -> list[dict]:
    batches = db.scalars(select(ImportBatch).where(ImportBatch.status == "pending").order_by(ImportBatch.created_at.desc(), ImportBatch.id.desc())).all()
    accounts = {account.id: account for account in db.scalars(select(Account).where(Account.id.in_({batch.account_id for batch in batches}))).all()} if batches else {}
    results = []
    for batch in batches:
        all_staging_rows = db.scalars(select(StagingRow).where(StagingRow.import_batch_id == batch.id).order_by(StagingRow.row_index.asc())).all()
        preview_rows = all_staging_rows[:5]
        account = accounts.get(batch.account_id)
        raw_preview = PreviewResult(rows=[json.loads(row.raw_json) for row in all_staging_rows], warnings=[], detected_preset=batch.detected_preset)
        sign_resolution = resolve_sign_preview(db, account=account, preset_type=batch.detected_preset or "unknown", preview=raw_preview, requested=batch.sign_convention or "preset") if account and batch.detected_preset not in {"ofx_statement", "pdf_statement"} else None
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
    account = db.get(Account, batch.account_id)
    if not account:
        raise ValueError("The matched account no longer exists")
    if batch.detected_preset == "pdf_statement":
        return commit_pdf_statement(db, batch, account, actor=actor)
    source = _validated_source_path(batch)
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != batch.file_hash:
        raise ValueError("The source file changed after it was staged. Discard this batch and scan again.")
    if batch.detected_preset == "ofx_statement":
        return commit_ofx_import(db, account, batch.filename, content, actor=actor, existing_batch=batch)
    return commit_import(db, account, None, batch.filename, content, actor=actor, existing_batch=batch, sign_convention=batch.sign_convention or "preset")


def discard_pending_import(batch: ImportBatch) -> dict:
    if batch.status != "pending":
        raise ValueError("Only pending inbox imports can be discarded")
    batch.status = "discarded"
    forget_pdf_content(batch.id)
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


def _refresh_pending_pdf_preview(db: Session, batch: ImportBatch, content: bytes, filename: str) -> int:
    account = db.get(Account, batch.account_id)
    if not account:
        raise ValueError("The matched account no longer exists")
    pattern = saved_pdf_pattern(db, account)
    preview = extract_statement_pdf(content, filename, preferred_label=pattern.balance_label if pattern else None)
    normalized = apply_pdf_templates(content, templates_for_account(db, account), account, statement_preview_row(preview, account))
    cache_pdf_content(batch.id, content)
    row = db.scalar(select(StagingRow).where(StagingRow.import_batch_id == batch.id, StagingRow.row_kind == "statement_balance"))
    if row is None:
        row = StagingRow(import_batch_id=batch.id, account_id=account.id, row_index=1, row_kind="statement_balance", raw_json="{}", normalized_json="{}")
        db.add(row)
    row.raw_json = json.dumps(normalized)
    row.normalized_json = json.dumps(normalized)
    batch.warnings_json = json.dumps(preview.warnings)
    batch.source_path = str((inbox_directory() / filename).resolve())
    return 1
