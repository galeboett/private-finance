import csv
import io
import json
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..config import settings
from ..db import get_db
from ..models import Account, ImportBatch, ImportPreset, ImportSignProfile, Institution, SessionToken, StatementPdfPattern
from ..schemas import ImportPresetCreate, StatementBalancePreviewUpdate
from ..security import require_csrf
from ..services.import_inbox import confirm_pending_import, discard_pending_import, inbox_directory, pending_import_batches, scan_import_inbox, stage_uploaded_import
from ..services.importers import PreviewResult, annotate_import_interpretation, commit_categorized_history, commit_import, commit_reviewed_categorized_history, decode_text, detect_preset_from_content, preview_import, review_categorized_history, suggest_account_for_import
from ..services.importers_ofx import parse_ofx, suggest_ofx_account
from ..services.mutation_log import MutationChange, full_values, journal_mutation
from ..services.sign_profiles import profile_payload, resolution_payload, resolve_sign_preview, save_sign_profile
from ..services.statement_pdf import extract_statement_pdf, saved_pdf_pattern, statement_preview_row, suggest_pdf_account, update_statement_preview
from ..services.pdf_teaching import apply_pdf_templates, templates_for_account
from .dependencies import actor_for_session, current_session


router = APIRouter()


@router.post("/api/import-presets")
def create_import_preset(payload: ImportPresetCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    preset = ImportPreset(**payload.model_dump())
    db.add(preset)
    db.flush()
    operation_id = journal_mutation(db, kind="create", entity_type="import_preset", actor=actor_for_session(session), description=f'Created import preset "{preset.name}"', changes=[MutationChange(preset.id, None, full_values(preset))])
    record_audit_event(db, "preset_create", "local-user", "import_preset", str(preset.id), payload.model_dump())
    db.commit()
    return {"id": preset.id, "operation_id": operation_id}


@router.get("/api/accounts/{account_id}/import-presets")
def list_import_presets(account_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    presets = db.scalars(select(ImportPreset).where(ImportPreset.account_id == account_id).order_by(ImportPreset.name.asc())).all()
    return [{"id": preset.id, "name": preset.name, "preset_type": preset.preset_type, "header_signature": preset.header_signature} for preset in presets]


@router.post("/api/imports/analyze")
async def imports_analyze(file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    content = await file.read()
    if len(content) > settings.import_file_size_limit_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")
    filename = file.filename or "import.csv"
    suffix = Path(filename).suffix.casefold()
    if suffix in {".ofx", ".qfx"}:
        try:
            account, confidence, reason, proposed, replacement_candidate_id = suggest_ofx_account(db, content)
            parsed = parse_ofx(content)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"preset_type": "ofx_statement", "suggested_account_id": account.id if account else None, "replacement_candidate_id": replacement_candidate_id, "match_confidence": confidence, "reason": reason, "proposed_account": proposed, "warnings": parsed.warnings}
    if suffix == ".pdf":
        try:
            pdf_preview = extract_statement_pdf(content, filename)
            account, confidence, reason, proposed, replacement_candidate_id = suggest_pdf_account(db, filename, pdf_preview)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"preset_type": "pdf_statement", "suggested_account_id": account.id if account else None, "replacement_candidate_id": replacement_candidate_id, "match_confidence": confidence, "reason": reason, "proposed_account": proposed, "warnings": pdf_preview.warnings}
    try:
        suggestion = suggest_account_for_import(db, file.filename or "import.csv", content)
    except ValueError as error:
        try:
            text_content = decode_text(content)
            reader = csv.reader(io.StringIO(text_content))
            headers = next(reader, [])
            samples = [dict(zip(headers, row)) for row in list(reader)[:3]]
        except (ValueError, csv.Error) as parse_error:
            raise HTTPException(status_code=400, detail=str(parse_error)) from parse_error
        if len(headers) < 3:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"preset_type": None, "suggested_account_id": None, "replacement_candidate_id": None, "match_confidence": 0, "reason": "Choose the date, description, and amount columns once. This browser will remember the mapping for matching headers.", "proposed_account": None, "warnings": [], "headers": headers, "sample_rows": samples}
    return {
        "preset_type": suggestion.preset_type,
        "suggested_account_id": suggestion.suggested_account_id,
        "replacement_candidate_id": suggestion.replacement_candidate_id,
        "match_confidence": suggestion.match_confidence,
        "reason": suggestion.reason,
        "proposed_account": suggestion.proposed_account,
        "warnings": suggestion.warnings,
    }


@router.post("/api/imports/preview")
async def imports_preview(account_id: int, sign_convention: Literal["auto", "preset", "reverse"] = "auto", file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.account_type == "external":
        raise HTTPException(status_code=400, detail="Untracked accounts do not accept imports")
    content = await file.read()
    if len(content) > settings.import_file_size_limit_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")
    filename = file.filename or "import.csv"
    suffix = Path(filename).suffix.casefold()
    if suffix in {".ofx", ".qfx"}:
        try:
            parsed = parse_ofx(content)
            preview = annotate_import_interpretation(PreviewResult(rows=parsed.rows, warnings=parsed.warnings, detected_preset="ofx_statement"), account)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"preset_type": "ofx_statement", "sign_convention": "preset", "sign_decision": None, "rows": preview.rows[:25], "warnings": preview.warnings}
    if suffix == ".pdf":
        try:
            pattern = saved_pdf_pattern(db, account)
            pdf_preview = extract_statement_pdf(content, filename, preferred_label=pattern.balance_label if pattern else None)
            row = apply_pdf_templates(content, templates_for_account(db, account), account, statement_preview_row(pdf_preview, account))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"preset_type": "pdf_statement", "sign_convention": "preset", "sign_decision": None, "rows": [row], "warnings": pdf_preview.warnings}
    try:
        preset_type = detect_preset_from_content(decode_text(content), file.filename or "import.csv")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not preset_type:
        raise HTTPException(status_code=400, detail="Could not detect import preset")
    try:
        resolution = resolve_sign_preview(db, account=account, preset_type=preset_type, preview=preview_import(content, preset_type), requested=sign_convention)
        preview = annotate_import_interpretation(resolution.preview, account)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"preset_type": preset_type, "sign_convention": resolution.sign_convention, "sign_decision": resolution_payload(resolution), "rows": preview.rows[:25], "warnings": preview.warnings}


@router.post("/api/imports/commit")
async def imports_commit(request: Request, account_id: int, preset_id: int | None = None, snapshot_date: str | None = None, sign_convention: Literal["auto", "preset", "reverse"] = "auto", file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.account_type == "external":
        raise HTTPException(status_code=400, detail="Untracked accounts do not accept imports")
    preset = db.get(ImportPreset, preset_id) if preset_id else None
    content = await file.read()
    if len(content) > settings.import_file_size_limit_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")
    parsed_snapshot_date: date | None = None
    if snapshot_date:
        try:
            parsed_snapshot_date = date.fromisoformat(snapshot_date)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="snapshot_date must be YYYY-MM-DD") from error
    try:
        detected_preset = preset.preset_type if preset else detect_preset_from_content(decode_text(content), file.filename or "import.csv")
        if not detected_preset:
            raise ValueError("Could not detect import preset")
        resolution = resolve_sign_preview(db, account=account, preset_type=detected_preset, preview=preview_import(content, detected_preset), requested=sign_convention)
        result = commit_import(db, account, preset, file.filename or "import.csv", content, actor=actor_for_session(session), snapshot_date=parsed_snapshot_date, sign_convention=resolution.sign_convention)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return result


@router.post("/api/imports/categorized-history")
async def imports_categorized_history(request: Request, sign_convention: Literal["charges_positive", "canonical"] = "charges_positive", file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    content = await file.read()
    if len(content) > settings.import_file_size_limit_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File is too large")
    filename = file.filename or "categorized-history"
    try:
        review = review_categorized_history(filename, content)
        if review["needs_review"]:
            return {"needs_review": True, "filename": filename, "rows": review["rows"]}
        result = commit_categorized_history(db, filename, content, actor=actor_for_session(session), sign_convention=sign_convention)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return {"needs_review": False, **result}


@router.post("/api/imports/categorized-history/reviewed")
async def imports_reviewed_categorized_history(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    payload = await request.json()
    try:
        result = commit_reviewed_categorized_history(db, payload.get("filename") or "categorized-history", payload.get("rows") or [], actor=actor_for_session(session), sign_convention=payload.get("sign_convention") or "charges_positive")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return result


@router.post("/api/imports/stage")
async def stage_manual_import(request: Request, account_id: int, sign_convention: Literal["auto", "preset", "reverse"] = "auto", file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    if account.account_type == "external":
        raise HTTPException(status_code=400, detail="Untracked accounts do not accept imports")
    content = await file.read()
    try:
        result = stage_uploaded_import(db, account=account, filename=file.filename or "import.csv", content=content, sign_convention=sign_convention)
    except (UnicodeDecodeError, ValueError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return {**result, "pending": pending_import_batches(db)}


@router.get("/api/import-sign-profiles")
def list_import_sign_profiles(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    profiles = db.scalars(select(ImportSignProfile).order_by(ImportSignProfile.account_id, ImportSignProfile.preset_type, ImportSignProfile.id)).all()
    return [profile_payload(profile) for profile in profiles]


@router.get("/api/settings/import-metadata")
def list_import_settings_metadata(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    accounts = {row.id: row.display_name for row in db.scalars(select(Account)).all()}
    institutions = {row.id: row.name for row in db.scalars(select(Institution)).all()}
    return {
        "sign_profiles": [{**profile_payload(profile), "account": accounts.get(profile.account_id, f"Account {profile.account_id}")} for profile in db.scalars(select(ImportSignProfile).order_by(ImportSignProfile.account_id, ImportSignProfile.preset_type)).all()],
        "csv_mappings": [{"id": preset.id, "account_id": preset.account_id, "account": accounts.get(preset.account_id, f"Account {preset.account_id}"), "name": preset.name, "preset_type": preset.preset_type} for preset in db.scalars(select(ImportPreset).order_by(ImportPreset.account_id, ImportPreset.name)).all()],
        "pdf_patterns": [{"id": pattern.id, "institution_id": pattern.institution_id, "institution": institutions.get(pattern.institution_id, f"Institution {pattern.institution_id}"), "balance_label": pattern.balance_label, "date_label": pattern.date_label} for pattern in db.scalars(select(StatementPdfPattern).order_by(StatementPdfPattern.institution_id)).all()],
    }


@router.put("/api/import-sign-profiles/{account_id}")
async def put_import_sign_profile(account_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    payload = await request.json()
    preset_type = str(payload.get("preset_type") or "").strip() or None
    sample_note = str(payload.get("sample_note") or "").strip() or None
    try:
        profile, operation_id = save_sign_profile(db, account=account, preset_type=preset_type, sign_convention=str(payload.get("sign_convention") or ""), actor=actor_for_session(session), sample_note=sample_note)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return {**profile_payload(profile), "operation_id": operation_id}


@router.get("/api/imports/inbox")
def get_import_inbox(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return {"folder": str(inbox_directory()), "pending": pending_import_batches(db)}


@router.post("/api/imports/inbox/scan")
def scan_inbox(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    result = scan_import_inbox(db)
    record_audit_event(db, "import_inbox_scan", actor_for_session(session), "import_inbox", result["folder"], {"files_found": result["files_found"], "staged": len(result["staged"]), "needs_account": len(result["needs_account"]), "errors": len(result["errors"])})
    db.commit()
    return {**result, "pending": pending_import_batches(db)}


@router.post("/api/imports/{batch_id}/confirm")
def confirm_inbox_import(batch_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    try:
        result = confirm_pending_import(db, batch, actor_for_session(session))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return result


@router.patch("/api/imports/{batch_id}/statement-preview")
def edit_statement_balance_preview(batch_id: int, payload: StatementBalancePreviewUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    try:
        result = update_statement_preview(db, batch, statement_date=payload.statement_date, balance_cents=payload.balance_cents, candidate_index=payload.candidate_index)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return {"preview": result, "pending": pending_import_batches(db)}


@router.post("/api/imports/{batch_id}/discard")
def discard_inbox_import(batch_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    try:
        result = discard_pending_import(batch)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit_event(db, "import_inbox_discard", actor_for_session(session), "import_batch", str(batch.id), {"filename": batch.filename})
    db.commit()
    return result


@router.get("/api/imports/{batch_id}/report")
def import_report(batch_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return {"id": batch.id, "filename": batch.filename, "status": batch.status, "imported_rows": batch.imported_rows, "skipped_duplicates": batch.skipped_duplicates, "warnings": json.loads(batch.warnings_json)}
