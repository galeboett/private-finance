from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..bootstrap import initialize_database
from ..config import settings
from ..db import get_db
from ..models import (
    Account,
    Category,
    CategoryRule,
    DuplicatePairDecision,
    ExpenseAllocation,
    HoldingLot,
    HoldingSnapshot,
    ImportBatch,
    ImportPreset,
    Institution,
    NetWorthSnapshot,
    PaymentVerificationDismissal,
    PdfExtractionTemplate,
    RefundLink,
    SecurityMetadata,
    SecurityPrice,
    SessionToken,
    StatementCheckpoint,
    StatementPdfPattern,
    StagingRow,
    Transaction,
    TransactionSplit,
    TransferLink,
)
from ..money import cents_to_decimal_string, escape_csv_formula
from ..schemas import BackupCreateRequest, BackupRestoreRequest, EncryptedExportRequest
from ..security import require_csrf, require_recent_reauthentication
from ..services.backups import (
    BackupError,
    create_backup,
    list_backups,
    resolve_backup_destination,
    resolve_restore_source,
    restore_backup,
)
from ..services.mutation_log import MutationChange, full_values, journal_mutation
from ..services.encryption import ENCRYPTED_MAGIC, EncryptionError, decrypt_payload, encrypt_payload
from ..services.transaction_queries import live_transaction_select
from .dependencies import actor_for_session, current_session


router = APIRouter()


APP_EXPORT_TABLES = [
    Institution,
    Account,
    Category,
    ImportPreset,
    ImportBatch,
    StagingRow,
    CategoryRule,
    Transaction,
    TransactionSplit,
    ExpenseAllocation,
    TransferLink,
    RefundLink,
    PaymentVerificationDismissal,
    DuplicatePairDecision,
    HoldingSnapshot,
    HoldingLot,
    NetWorthSnapshot,
    StatementCheckpoint,
    StatementPdfPattern,
    PdfExtractionTemplate,
    SecurityMetadata,
    SecurityPrice,
]

APP_EXPORT_ENTITY_TYPES = {
    Institution: "institution",
    Account: "account",
    Category: "category",
    ImportPreset: "import_preset",
    ImportBatch: "import_batch",
    StagingRow: "staging_row",
    CategoryRule: "category_rule",
    Transaction: "transaction",
    TransactionSplit: "transaction_split",
    ExpenseAllocation: "expense_allocation",
    TransferLink: "transfer_link",
    RefundLink: "refund_link",
    PaymentVerificationDismissal: "payment_verification_dismissal",
    DuplicatePairDecision: "duplicate_pair_decision",
    HoldingSnapshot: "holding_snapshot",
    HoldingLot: "holding_lot",
    NetWorthSnapshot: "net_worth_snapshot",
    StatementCheckpoint: "statement_checkpoint",
    StatementPdfPattern: "statement_pdf_pattern",
    PdfExtractionTemplate: "pdf_extraction_template",
    SecurityMetadata: "security_metadata",
    SecurityPrice: "security_price",
}


def _serialize_model(row) -> dict:
    payload = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if isinstance(value, (date, datetime)):
            payload[column.name] = value.isoformat()
        else:
            payload[column.name] = value
    return payload


def _deserialize_model(model, payload: dict):
    values = {}
    for column in model.__table__.columns:
        if column.name not in payload:
            continue
        value = payload[column.name]
        if value is not None:
            try:
                python_type = column.type.python_type
            except NotImplementedError:
                python_type = None
            if python_type is date:
                value = date.fromisoformat(value)
            elif python_type is datetime:
                value = datetime.fromisoformat(value)
        values[column.name] = value
    return model(**values)


def _app_data_payload(db: Session) -> dict:
    payload = {
        "format": "private-finance-app-data",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "tables": {},
    }
    for model in APP_EXPORT_TABLES:
        rows = db.scalars(select(model).order_by(model.id.asc())).all()
        payload["tables"][model.__tablename__] = [_serialize_model(row) for row in rows]
    return payload


@router.get("/api/exports/app-data.json")
def export_app_data(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_recent_reauthentication(session)
    payload = _app_data_payload(db)
    return JSONResponse(
        payload,
        headers={"Content-Disposition": "attachment; filename=private-finance-app-data.json"},
    )


@router.post("/api/exports/app-data.encrypted")
def export_encrypted_app_data(payload: EncryptedExportRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    require_recent_reauthentication(session)
    serialized = json.dumps(_app_data_payload(db), separators=(",", ":")).encode("utf-8")
    try:
        encrypted = encrypt_payload(serialized, payload.passphrase)
    except EncryptionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return StreamingResponse(
        iter([encrypted]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=private-finance-app-data.pfenc"},
    )


@router.post("/api/imports/app-data")
async def import_app_data(
    request: Request,
    file: UploadFile = File(...),
    confirm_text: str = Form(...),
    passphrase: str | None = Form(default=None),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    require_csrf(request, session)
    require_recent_reauthentication(session)
    if confirm_text != "IMPORT":
        raise HTTPException(status_code=400, detail='Type IMPORT to confirm replacing app data')
    try:
        file_bytes = await file.read()
        if file_bytes.startswith(ENCRYPTED_MAGIC):
            if not passphrase:
                raise HTTPException(status_code=400, detail="Enter the encryption passphrase for this export")
            file_bytes = decrypt_payload(file_bytes, passphrase)
        payload = json.loads(file_bytes.decode("utf-8-sig"))
    except EncryptionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Choose a valid app-data JSON export") from exc
    if payload.get("format") != "private-finance-app-data" or not isinstance(payload.get("tables"), dict):
        raise HTTPException(status_code=400, detail="This file is not a private finance app-data export")

    tables = payload["tables"]
    before_images = {(APP_EXPORT_ENTITY_TYPES[model], row.id): full_values(row) for model in APP_EXPORT_TABLES for row in db.scalars(select(model)).all()}
    for model in reversed(APP_EXPORT_TABLES):
        db.execute(delete(model))
    for model in APP_EXPORT_TABLES:
        for row in tables.get(model.__tablename__, []):
            db.add(_deserialize_model(model, row))
    db.flush()
    after_images = {(APP_EXPORT_ENTITY_TYPES[model], row.id): full_values(row) for model in APP_EXPORT_TABLES for row in db.scalars(select(model)).all()}
    keys = sorted(set(before_images) | set(after_images))
    operation_id = journal_mutation(db, kind="replace", entity_type="mixed", actor=actor_for_session(session), description=f'Restored app data from "{file.filename or "upload"}"', changes=[MutationChange(entity_id, before_images.get((entity_type, entity_id)), after_images.get((entity_type, entity_id)), entity_type=entity_type) for entity_type, entity_id in keys])
    record_audit_event(db, "app_data_import", "local-user", "app_data", file.filename or "upload", {"version": payload.get("version")})
    db.commit()
    return {"ok": True, "operation_id": operation_id}

@router.get("/api/exports/transactions.csv")
def export_transactions(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_recent_reauthentication(session)
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    categories = {category.id: category.label for category in db.scalars(select(Category)).all()}
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Posted Date", "Account", "Institution", "Description", "Amount", "Type", "Category", "Review Status", "Note"])
    rows = db.scalars(live_transaction_select().order_by(Transaction.transaction_date.asc(), Transaction.id.asc())).all()
    for row in rows:
        account = accounts.get(row.account_id)
        writer.writerow(
            [
                row.transaction_date.isoformat(),
                row.posted_date.isoformat() if row.posted_date else "",
                escape_csv_formula(account.display_name) if account else "",
                escape_csv_formula(account.institution.name) if account and account.institution else "",
                escape_csv_formula(row.raw_description),
                cents_to_decimal_string(row.amount_cents),
                row.transaction_type,
                categories.get(row.category_id, ""),
                row.review_status,
                escape_csv_formula(row.user_note or ""),
            ]
        )
    # Stream from memory: no plaintext copy is left behind on disk.
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transactions.csv"},
    )


@router.get("/api/backups")
def get_backups(session: SessionToken = Depends(current_session)):
    return {"backup_dir": str(Path(settings.backup_dir).resolve()), "backups": list_backups()}


@router.post("/api/backups")
def backup_database(payload: BackupCreateRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        resolved = resolve_backup_destination(payload.destination, encrypted=bool(payload.passphrase))
        output = create_backup(resolved, payload.passphrase)
    except BackupError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit_event(db, "backup_create", "local-user", "backup", str(output), {"destination": str(output)})
    db.commit()
    return {"path": str(output)}


@router.post("/api/backups/restore")
def restore_database(payload: BackupRestoreRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    require_recent_reauthentication(session)
    try:
        resolved = resolve_restore_source(payload.source)
    except BackupError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    # Audit before the swap: the restored database's audit trail may predate this event.
    record_audit_event(db, "backup_restore", "local-user", "backup", str(resolved), {"source": str(resolved)})
    db.commit()
    db.close()
    try:
        safety_copy = restore_backup(resolved, payload.passphrase)
    except BackupError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    initialize_database()
    return {"ok": True, "pre_restore_copy": str(safety_copy)}
