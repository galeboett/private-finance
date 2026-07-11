from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import record_audit_event
from .bootstrap import initialize_database
from .config import settings
from .db import get_db
from .middleware import LocalhostSecurityMiddleware
from .models import Account, AppUser, Category, CategoryRule, ExpenseAllocation, HoldingSnapshot, ImportBatch, ImportPreset, Institution, SecurityMetadata, SecurityPrice, SessionToken, StagingRow, Transaction, TransactionSplit, TransferLink
from .money import cents_to_decimal_string, escape_csv_formula
from .schemas import AccountCreate, AccountUpdate, BulkDeleteRequest, BulkTransactionUpdateRequest, CategoryCreate, CategoryUpdate, DeleteConfirmRequest, HoldingMetadataUpdate, ImportPresetCreate, LoginRequest, MonthlyAllocationRequest, PasswordChangeRequest, RuleApplyRequest, RuleCreate, RuleUpdate, SetupRequest, SplitSetRequest, TransactionReviewUpdate, TransactionType, TransferLinkCreate
from .security import clear_login_failures, create_session, enforce_login_rate_limit, ensure_setup_state, get_session_from_request, hash_password, password_needs_rehash, purge_expired_sessions, record_login_failure, require_csrf, set_session_cookie, verify_password
from .services.accounts import cleanup_imported_accounts
from .services.backups import BackupError, create_backup, list_backups, resolve_backup_destination, resolve_restore_source, restore_backup
from .services.importers import commit_categorized_history, commit_import, commit_reviewed_categorized_history, decode_text, detect_preset_from_content, preview_import, review_categorized_history, suggest_account_for_import
from .services.reporting import cash_flow_summary, category_totals, dashboard_summary, latest_investment_allocation, latest_net_worth_by_account
from .services.transfers import confirm_transfer_link, create_transfer_suggestions, list_unconfirmed_transfers, reject_transfer_link

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["content-type", settings.csrf_header_name],
)
app.add_middleware(LocalhostSecurityMiddleware)


@app.exception_handler(RequestValidationError)
async def sanitized_validation_error_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        errors.append(
            {
                "type": error.get("type"),
                "loc": error.get("loc"),
                "msg": error.get("msg"),
                "ctx": error.get("ctx"),
            }
        )
    return JSONResponse({"detail": errors}, status_code=422)


def current_session(request: Request, db: Session = Depends(get_db)) -> SessionToken:
    return get_session_from_request(db, request)


@app.on_event("startup")
def on_startup():
    initialize_database()


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
frontend_assets = frontend_dist / "assets"
if frontend_assets.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_assets)), name="assets")


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    return {"ok": True, "configured": ensure_setup_state(db)}


@app.post("/api/setup")
def setup(request: SetupRequest, db: Session = Depends(get_db)):
    if ensure_setup_state(db):
        raise HTTPException(status_code=400, detail="Application already set up")
    user = AppUser(password_hash=hash_password(request.password))
    db.add(user)
    db.commit()
    record_audit_event(db, "setup", "system", "app_user", str(user.id), {"message": "Initial password created"})
    db.commit()
    return {"ok": True}


@app.post("/api/login")
def login(payload: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    client_key = request.client.host if request.client else "localhost"
    enforce_login_rate_limit(client_key)
    user = db.scalar(select(AppUser).limit(1))
    if not user or not verify_password(payload.password, user.password_hash):
        record_login_failure(client_key)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    clear_login_failures(client_key)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    purge_expired_sessions(db)
    session = create_session(db, user.id)
    db.commit()
    set_session_cookie(response, session)
    record_audit_event(db, "login", "local-user", "session", str(session.id), {"message": "Login successful"})
    db.commit()
    return {"ok": True, "csrf_token": session.csrf_token}


@app.post("/api/logout")
def logout(request: Request, response: Response, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    db.execute(delete(SessionToken).where(SessionToken.id == session.id))
    record_audit_event(db, "logout", "local-user", "session", str(session.id), {"message": "Logout"})
    db.commit()
    response.delete_cookie(settings.session_cookie_name)
    return {"ok": True}


@app.post("/api/password")
def change_password(payload: PasswordChangeRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    user = db.get(AppUser, session.user_id)
    if not user or not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    user.password_version += 1
    # Invalidate every other session so a stolen cookie dies with the old password.
    db.execute(delete(SessionToken).where(SessionToken.user_id == user.id, SessionToken.id != session.id))
    record_audit_event(db, "password_change", "local-user", "app_user", str(user.id), {"password_version": user.password_version})
    db.commit()
    return {"ok": True}


@app.get("/api/bootstrap")
def bootstrap_state(db: Session = Depends(get_db)):
    return {
        "configured": ensure_setup_state(db),
        "categories": [{"id": category.id, "key": category.key, "label": category.label} for category in db.scalars(select(Category).order_by(Category.label.asc())).all()],
    }


@app.get("/api/me")
def me(session: SessionToken = Depends(current_session)):
    return {"ok": True, "csrf_token": session.csrf_token}


@app.post("/api/accounts")
def create_account(payload: AccountCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    institution = upsert_institution(db, payload.institution_name)
    account = Account(
        institution_id=institution.id if institution else None,
        display_name=payload.display_name,
        account_type=payload.account_type,
        currency=payload.currency,
        last_four=payload.last_four,
    )
    db.add(account)
    db.flush()
    record_audit_event(db, "account_create", "local-user", "account", str(account.id), payload.model_dump())
    db.commit()
    return {"id": account.id}


def upsert_institution(db: Session, name: str | None) -> Institution | None:
    if not name:
        return None
    institution = db.scalar(select(Institution).where(Institution.name == name))
    if not institution:
        institution = Institution(name=name)
        db.add(institution)
        db.flush()
    return institution


@app.get("/api/accounts")
def list_accounts(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    accounts = db.scalars(select(Account).order_by(Account.display_name.asc())).all()
    return [
        {
            "id": account.id,
            "institution_name": account.institution.name if account.institution else None,
            "display_name": account.display_name,
            "account_type": account.account_type,
            "currency": account.currency,
            "status": account.status,
            "last_four": account.last_four,
        }
        for account in accounts
    ]


@app.post("/api/accounts/cleanup-imported")
def cleanup_accounts_from_import_labels(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    return cleanup_imported_accounts(db)


@app.patch("/api/accounts/{account_id}")
def update_account(account_id: int, payload: AccountUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    updates = payload.model_dump(exclude_unset=True)
    if "institution_name" in updates:
        institution = upsert_institution(db, updates.pop("institution_name"))
        account.institution_id = institution.id if institution else None
    for key, value in updates.items():
        setattr(account, key, value)
    record_audit_event(db, "account_update", "local-user", "account", str(account.id), payload.model_dump(exclude_unset=True))
    db.commit()
    return {"ok": True}


@app.post("/api/accounts/{account_id}/archive")
def archive_account(account_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.status = "archived"
    record_audit_event(db, "account_archive", "local-user", "account", str(account.id), {"status": "archived"})
    db.commit()
    return {"ok": True}


def category_key_from_label(label: str) -> str:
    key = "".join(char.lower() if char.isalnum() else "_" for char in label.strip())
    key = "_".join(part for part in key.split("_") if part)
    return key[:60] or "category"



def _require_delete_confirmation(confirm_text: str) -> None:
    if confirm_text != "DELETE":
        raise HTTPException(status_code=400, detail='Type DELETE to confirm deletion')


def _delete_transaction_row(db: Session, transaction: Transaction) -> None:
    db.execute(update(Transaction).where(Transaction.linked_transaction_id == transaction.id).values(linked_transaction_id=None))
    db.execute(update(Transaction).where(Transaction.duplicate_of_transaction_id == transaction.id).values(duplicate_of_transaction_id=None))
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id == transaction.id))
    db.execute(delete(ExpenseAllocation).where(ExpenseAllocation.transaction_id == transaction.id))
    db.execute(delete(TransferLink).where((TransferLink.from_transaction_id == transaction.id) | (TransferLink.to_transaction_id == transaction.id)))
    record_audit_event(
        db,
        "transaction_delete",
        "local-user",
        "transaction",
        str(transaction.id),
        {"description": transaction.raw_description, "amount_cents": transaction.amount_cents, "date": transaction.transaction_date.isoformat()},
    )
    db.delete(transaction)


def _delete_account_tree(db: Session, account: Account) -> None:
    transactions = db.scalars(select(Transaction).where(Transaction.account_id == account.id)).all()
    for transaction in transactions:
        _delete_transaction_row(db, transaction)
    db.execute(delete(StagingRow).where(StagingRow.account_id == account.id))
    db.execute(delete(HoldingSnapshot).where(HoldingSnapshot.account_id == account.id))
    db.execute(delete(ImportBatch).where(ImportBatch.account_id == account.id))
    db.execute(delete(ImportPreset).where(ImportPreset.account_id == account.id))
    record_audit_event(
        db,
        "account_delete",
        "local-user",
        "account",
        str(account.id),
        {"display_name": account.display_name, "account_type": account.account_type},
    )
    db.delete(account)


@app.delete("/api/accounts/bulk-delete")
def bulk_delete_accounts(payload: BulkDeleteRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    if not payload.ids:
        raise HTTPException(status_code=400, detail="Choose at least one account to delete")
    accounts = db.scalars(select(Account).where(Account.id.in_(payload.ids))).all()
    found_ids = {account.id for account in accounts}
    missing_ids = [account_id for account_id in payload.ids if account_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Account not found: {missing_ids[0]}")
    for account in accounts:
        _delete_account_tree(db, account)
    db.commit()
    return {"ok": True, "deleted": len(accounts)}


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    _delete_account_tree(db, account)
    db.commit()
    return {"ok": True}

@app.post("/api/categories")
def create_category(payload: CategoryCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Category label is required")
    base_key = category_key_from_label(label)
    key = base_key
    suffix = 2
    while db.scalar(select(Category).where(Category.key == key)):
        key = f"{base_key[:55]}_{suffix}"
        suffix += 1
    category = Category(key=key, label=label)
    db.add(category)
    db.flush()
    record_audit_event(db, "category_create", "local-user", "category", str(category.id), {"label": label, "key": key})
    db.commit()
    return {"id": category.id, "key": category.key, "label": category.label}


@app.patch("/api/categories/{category_id}")
def update_category(category_id: int, payload: CategoryUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Category label is required")
    category.label = label
    record_audit_event(db, "category_update", "local-user", "category", str(category.id), {"label": label})
    db.commit()
    return {"ok": True}


@app.post("/api/import-presets")
def create_import_preset(payload: ImportPresetCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    preset = ImportPreset(**payload.model_dump())
    db.add(preset)
    db.flush()
    record_audit_event(db, "preset_create", "local-user", "import_preset", str(preset.id), payload.model_dump())
    db.commit()
    return {"id": preset.id}


@app.get("/api/accounts/{account_id}/import-presets")
def list_import_presets(account_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    presets = db.scalars(select(ImportPreset).where(ImportPreset.account_id == account_id).order_by(ImportPreset.name.asc())).all()
    return [{"id": preset.id, "name": preset.name, "preset_type": preset.preset_type, "header_signature": preset.header_signature} for preset in presets]


@app.post("/api/imports/analyze")
async def imports_analyze(file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    content = await file.read()
    if len(content) > settings.import_file_size_limit_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")
    try:
        suggestion = suggest_account_for_import(db, file.filename or "import.csv", content)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {
        "preset_type": suggestion.preset_type,
        "suggested_account_id": suggestion.suggested_account_id,
        "match_confidence": suggestion.match_confidence,
        "reason": suggestion.reason,
        "proposed_account": suggestion.proposed_account,
        "warnings": suggestion.warnings,
    }


@app.post("/api/imports/preview")
async def imports_preview(account_id: int, file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    content = await file.read()
    if len(content) > settings.import_file_size_limit_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")
    try:
        preset_type = detect_preset_from_content(decode_text(content))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not preset_type:
        raise HTTPException(status_code=400, detail="Could not detect import preset")
    try:
        preview = preview_import(content, preset_type)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"preset_type": preset_type, "rows": preview.rows[:25], "warnings": preview.warnings}


@app.post("/api/imports/commit")
async def imports_commit(request: Request, account_id: int, preset_id: int | None = None, snapshot_date: str | None = None, file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
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
        result = commit_import(db, account, preset, file.filename or "import.csv", content, snapshot_date=parsed_snapshot_date)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return result



@app.post("/api/imports/categorized-history")
async def imports_categorized_history(request: Request, file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    content = await file.read()
    if len(content) > settings.import_file_size_limit_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File is too large")
    filename = file.filename or "categorized-history"
    try:
        review = review_categorized_history(filename, content)
        if review["needs_review"]:
            return {"needs_review": True, "filename": filename, "rows": review["rows"]}
        result = commit_categorized_history(db, filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"needs_review": False, **result}


@app.post("/api/imports/categorized-history/reviewed")
async def imports_reviewed_categorized_history(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    payload = await request.json()
    try:
        result = commit_reviewed_categorized_history(db, payload.get("filename") or "categorized-history", payload.get("rows") or [])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return result

@app.get("/api/imports/{batch_id}/report")
def import_report(batch_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    from .models import ImportBatch

    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return {"id": batch.id, "filename": batch.filename, "status": batch.status, "imported_rows": batch.imported_rows, "skipped_duplicates": batch.skipped_duplicates, "warnings": json.loads(batch.warnings_json)}


@app.get("/api/transactions")
def list_transactions(account_id: int | None = None, review_status: str | None = None, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    query = select(Transaction).where(Transaction.status == "active").order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
    if account_id:
        query = query.where(Transaction.account_id == account_id)
    if review_status:
        query = query.where(Transaction.review_status == review_status)
    rows = db.scalars(query).all()
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    allocation_counts = dict(db.execute(select(ExpenseAllocation.transaction_id, func.count(ExpenseAllocation.id)).group_by(ExpenseAllocation.transaction_id)).all())
    split_counts = dict(db.execute(select(TransactionSplit.transaction_id, func.count(TransactionSplit.id)).group_by(TransactionSplit.transaction_id)).all())
    return [
        {
            "id": row.id,
            "account_id": row.account_id,
            "institution_name": accounts[row.account_id].institution.name if row.account_id in accounts and accounts[row.account_id].institution else None,
            "account_name": accounts[row.account_id].display_name if row.account_id in accounts else "Unknown account",
            "transaction_date": row.transaction_date.isoformat(),
            "amount_cents": row.amount_cents,
            "amount": cents_to_decimal_string(row.amount_cents),
            "raw_description": row.raw_description,
            "user_note": row.user_note,
            "transaction_type": row.transaction_type,
            "review_status": row.review_status,
            "category_id": row.category_id,
            "duplicate_of_transaction_id": row.duplicate_of_transaction_id,
            "monthly_allocation_count": allocation_counts.get(row.id, 0),
            "split_count": split_counts.get(row.id, 0),
        }
        for row in rows
    ]


@app.patch("/api/transactions/bulk-update")
def bulk_update_transactions(payload: BulkTransactionUpdateRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transactions = db.scalars(select(Transaction).where(Transaction.id.in_(payload.ids), Transaction.status == "active")).all()
    if len(transactions) != len(set(payload.ids)):
        raise HTTPException(status_code=404, detail="One or more transactions were not found")

    field = payload.field.value
    value = payload.value
    affected_accounts = 0
    if field == "institution":
        name = str(value or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Institution name is required")
        institution = upsert_institution(db, name)
        account_ids = {transaction.account_id for transaction in transactions}
        accounts = db.scalars(select(Account).where(Account.id.in_(account_ids))).all()
        for account in accounts:
            account.institution_id = institution.id if institution else None
        affected_accounts = len(accounts)
    elif field == "account":
        try:
            account_id = int(value)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="Choose a valid account") from error
        if not db.get(Account, account_id):
            raise HTTPException(status_code=400, detail="Account not found")
        for transaction in transactions:
            transaction.account_id = account_id
    elif field == "description":
        description = str(value or "").strip()
        if not description:
            raise HTTPException(status_code=400, detail="Description is required")
        for transaction in transactions:
            transaction.raw_description = description
    elif field == "details":
        details = str(value or "").strip() or None
        for transaction in transactions:
            transaction.user_note = details
    elif field == "type":
        try:
            transaction_type = TransactionType(str(value))
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Choose a valid transaction type") from error
        for transaction in transactions:
            transaction.transaction_type = transaction_type.value
    elif field == "category":
        try:
            category_id = int(value)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="Choose a valid category") from error
        if not db.get(Category, category_id):
            raise HTTPException(status_code=400, detail="Category not found")
        for transaction in transactions:
            transaction.category_id = category_id

    record_audit_event(db, "transaction_bulk_update", "local-user", "transactions", f"bulk:{len(transactions)}", {"field": field, "value": value, "count": len(transactions), "affected_accounts": affected_accounts, "transaction_ids": [transaction.id for transaction in transactions[:50]]})
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail="This change would create duplicate transactions in the target account") from error
    return {"ok": True, "updated": len(transactions), "affected_accounts": affected_accounts}


@app.patch("/api/transactions/{transaction_id}")
def update_transaction(transaction_id: int, payload: TransactionReviewUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = db.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    updates = payload.model_dump(exclude_unset=True)
    if "category_id" in updates and updates["category_id"] is not None and not db.get(Category, updates["category_id"]):
        raise HTTPException(status_code=400, detail="Category not found")
    for key, value in updates.items():
        setattr(transaction, key, value)
    record_audit_event(db, "transaction_update", "local-user", "transaction", str(transaction.id), updates)
    db.commit()
    return {"ok": True}


@app.post("/api/transactions/{transaction_id}/void")
def void_transaction(transaction_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = db.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    transaction.status = "voided"
    record_audit_event(db, "transaction_void", "local-user", "transaction", str(transaction.id), {"status": "voided"})
    db.commit()
    return {"ok": True}


@app.delete("/api/transactions/{transaction_id}")
def delete_transaction(transaction_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    transaction = db.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    _delete_transaction_row(db, transaction)
    db.commit()
    return {"ok": True}


@app.post("/api/transactions/{transaction_id}/splits")
def set_splits(transaction_id: int, payload: SplitSetRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = db.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    split_total = sum(split.amount_cents for split in payload.splits)
    if split_total != transaction.amount_cents:
        raise HTTPException(status_code=400, detail="Split amounts must sum exactly to the transaction amount")
    if db.scalar(select(ExpenseAllocation.id).where(ExpenseAllocation.transaction_id == transaction_id)):
        raise HTTPException(status_code=400, detail="Remove the monthly allocation before creating category splits")
    category_ids = {split.category_id for split in payload.splits}
    if len(db.scalars(select(Category.id).where(Category.id.in_(category_ids))).all()) != len(category_ids):
        raise HTTPException(status_code=400, detail="One or more split categories do not exist")
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id))
    for split in payload.splits:
        db.add(TransactionSplit(transaction_id=transaction_id, category_id=split.category_id, amount_cents=split.amount_cents, note=split.note))
    record_audit_event(db, "transaction_split", "local-user", "transaction", str(transaction.id), {"split_count": len(payload.splits)})
    db.commit()
    return {"ok": True}


@app.delete("/api/categories/{category_id}")
def delete_category(category_id: int, request: Request, reassign_to: int | None = None, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    if reassign_to == category_id:
        raise HTTPException(status_code=400, detail="Choose a different replacement category")
    replacement = db.get(Category, reassign_to) if reassign_to is not None else None
    if reassign_to is not None and not replacement:
        raise HTTPException(status_code=400, detail="Replacement category not found")

    reference_counts = {
        "transactions": db.scalar(select(func.count(Transaction.id)).where(Transaction.category_id == category_id)) or 0,
        "splits": db.scalar(select(func.count(TransactionSplit.id)).where(TransactionSplit.category_id == category_id)) or 0,
        "allocations": db.scalar(select(func.count(ExpenseAllocation.id)).where(ExpenseAllocation.category_id == category_id)) or 0,
        "rules": db.scalar(select(func.count(CategoryRule.id)).where(CategoryRule.category_id == category_id)) or 0,
    }
    if sum(reference_counts.values()) and replacement is None:
        raise HTTPException(status_code=400, detail="This category is in use. Choose a replacement category to merge it safely.")
    if replacement:
        db.execute(update(Transaction).where(Transaction.category_id == category_id).values(category_id=replacement.id))
        db.execute(update(TransactionSplit).where(TransactionSplit.category_id == category_id).values(category_id=replacement.id))
        db.execute(update(ExpenseAllocation).where(ExpenseAllocation.category_id == category_id).values(category_id=replacement.id))
        db.execute(update(CategoryRule).where(CategoryRule.category_id == category_id).values(category_id=replacement.id))
        db.execute(update(Category).where(Category.parent_id == category_id).values(parent_id=replacement.id))
    else:
        db.execute(update(Category).where(Category.parent_id == category_id).values(parent_id=None))
    record_audit_event(db, "category_delete", "local-user", "category", str(category.id), {"label": category.label, "reassigned_to": replacement.id if replacement else None, **reference_counts})
    db.delete(category)
    db.commit()
    return {"ok": True, "reassigned": sum(reference_counts.values())}


@app.get("/api/transactions/{transaction_id}/splits")
def get_splits(transaction_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    transaction = db.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return [
        {"category_id": split.category_id, "amount_cents": split.amount_cents, "note": split.note}
        for split in db.scalars(select(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id).order_by(TransactionSplit.id.asc())).all()
    ]


def _month_start(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


@app.post("/api/transactions/{transaction_id}/monthly-allocation")
def set_monthly_allocation(transaction_id: int, payload: MonthlyAllocationRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = db.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if transaction.status != "active" or transaction.transaction_type != "expense":
        raise HTTPException(status_code=400, detail="Only active expense transactions can be spread across months")
    if not db.get(Category, payload.category_id):
        raise HTTPException(status_code=400, detail="Category not found")
    if db.scalar(select(TransactionSplit.id).where(TransactionSplit.transaction_id == transaction_id)):
        raise HTTPException(status_code=400, detail="A split transaction cannot also be spread across months")
    db.execute(delete(ExpenseAllocation).where(ExpenseAllocation.transaction_id == transaction_id))
    amount, remainder = divmod(abs(transaction.amount_cents), payload.months)
    sign = -1 if transaction.amount_cents < 0 else 1
    for offset in range(payload.months):
        db.add(ExpenseAllocation(
            transaction_id=transaction.id,
            category_id=payload.category_id,
            allocation_date=_month_start(payload.allocation_start, offset),
            amount_cents=sign * (amount + (1 if offset < remainder else 0)),
        ))
    record_audit_event(db, "transaction_monthly_allocation", "local-user", "transaction", str(transaction.id), {"months": payload.months, "category_id": payload.category_id, "allocation_start": payload.allocation_start.isoformat()})
    db.commit()
    return {"ok": True}


@app.delete("/api/transactions/{transaction_id}/monthly-allocation")
def delete_monthly_allocation(transaction_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = db.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.execute(delete(ExpenseAllocation).where(ExpenseAllocation.transaction_id == transaction_id))
    record_audit_event(db, "transaction_monthly_allocation_delete", "local-user", "transaction", str(transaction.id), {})
    db.commit()
    return {"ok": True}


@app.get("/api/review")
def review_inbox(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Transaction).where(
            Transaction.status == "active",
            Transaction.review_status.in_(["needs_review", "suggested", "possible_duplicate"]),
        )
    ).all()
    return [
        {
            "id": row.id,
            "description": row.raw_description,
            "amount_cents": row.amount_cents,
            "transaction_type": row.transaction_type,
            "review_status": row.review_status,
            "date": row.transaction_date.isoformat(),
            "duplicate_of_transaction_id": row.duplicate_of_transaction_id,
        }
        for row in rows
    ]


@app.post("/api/rules")
def create_rule(payload: RuleCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    if not db.get(Category, payload.category_id):
        raise HTTPException(status_code=400, detail="Category not found")
    rule = CategoryRule(**payload.model_dump())
    db.add(rule)
    db.flush()
    record_audit_event(db, "rule_create", "local-user", "category_rule", str(rule.id), payload.model_dump())
    db.commit()
    return {"id": rule.id}


@app.post("/api/rules/{rule_id}/apply")
def apply_rule(rule_id: int, payload: RuleApplyRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    if payload.scope not in {"unreviewed", "all"}:
        raise HTTPException(status_code=400, detail="Rule scope must be unreviewed or all")
    rule = db.get(CategoryRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    query = select(Transaction).where(Transaction.status == "active")
    if payload.scope == "unreviewed":
        query = query.where(Transaction.review_status.in_(["needs_review", "suggested", "possible_duplicate"]))

    matched = 0
    updated = 0
    for transaction in db.scalars(query).all():
        if not rule_matches_transaction(rule, transaction):
            continue
        matched += 1
        if apply_rule_to_transaction(rule, transaction):
            updated += 1

    record_audit_event(db, "rule_apply", "local-user", "category_rule", str(rule.id), {"scope": payload.scope, "matched": matched, "updated": updated})
    db.commit()
    return {"matched": matched, "updated": updated}


@app.get("/api/rules/{rule_id}/preview")
def preview_rule(rule_id: int, scope: str = "unreviewed", session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    if scope not in {"unreviewed", "all"}:
        raise HTTPException(status_code=400, detail="Rule scope must be unreviewed or all")
    rule = db.get(CategoryRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    query = select(Transaction).where(Transaction.status == "active")
    if scope == "unreviewed":
        query = query.where(Transaction.review_status.in_(["needs_review", "suggested", "possible_duplicate"]))
    matched = sum(1 for transaction in db.scalars(query).all() if rule_matches_transaction(rule, transaction))
    return {"matched": matched, "scope": scope}


@app.patch("/api/rules/{rule_id}")
def update_rule(rule_id: int, payload: RuleUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    rule = db.get(CategoryRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    updates = payload.model_dump(exclude_unset=True)
    if "category_id" in updates and not db.get(Category, updates["category_id"]):
        raise HTTPException(status_code=400, detail="Category not found")
    if "match_text" in updates and not str(updates["match_text"]).strip():
        raise HTTPException(status_code=400, detail="Match text is required")
    for key, value in updates.items():
        setattr(rule, key, value)
    record_audit_event(db, "rule_update", "local-user", "category_rule", str(rule.id), updates)
    db.commit()
    return payload_from_rule(rule)


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    rule = db.get(CategoryRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    record_audit_event(db, "rule_delete", "local-user", "category_rule", str(rule.id), {"match_text": rule.match_text})
    db.delete(rule)
    db.commit()
    return {"ok": True}


@app.get("/api/rules")
def list_rules(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    rules = db.scalars(select(CategoryRule).order_by(CategoryRule.priority.asc(), CategoryRule.id.asc())).all()
    return [payload_from_rule(rule) for rule in rules]


def payload_from_rule(rule: CategoryRule) -> dict:
    return {
        "id": rule.id,
        "category_id": rule.category_id,
        "priority": rule.priority,
        "field_name": rule.field_name,
        "match_text": rule.match_text,
        "suggested_transaction_type": rule.suggested_transaction_type,
    }



def apply_rule_to_transaction(rule: CategoryRule, transaction: Transaction) -> bool:
    changed = False
    if transaction.category_id != rule.category_id:
        transaction.category_id = rule.category_id
        changed = True
    if transaction.transaction_type != rule.suggested_transaction_type:
        transaction.transaction_type = rule.suggested_transaction_type
        changed = True
    if transaction.review_status != "confirmed":
        transaction.review_status = "confirmed"
        changed = True
    return changed

def rule_matches_transaction(rule: CategoryRule, transaction: Transaction) -> bool:
    if rule.field_name != "raw_description":
        return False
    return rule.match_text.upper() in transaction.raw_description.upper()


@app.post("/api/transfer-links")
def create_transfer_link(payload: TransferLinkCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = TransferLink(**payload.model_dump())
    db.add(link)
    db.flush()
    record_audit_event(db, "transfer_link_create", "local-user", "transfer_link", str(link.id), payload.model_dump())
    db.commit()
    return {"id": link.id}


@app.get("/api/transfers/unconfirmed")
def get_unconfirmed_transfers(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_unconfirmed_transfers(db)


@app.post("/api/transfers/detect")
def detect_transfers(request: Request, window_days: int = 5, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    if window_days < 1 or window_days > 30:
        raise HTTPException(status_code=400, detail="Transfer matching window must be between 1 and 30 days")
    return create_transfer_suggestions(db, window_days=window_days)


@app.post("/api/transfers/{link_id}/confirm")
def confirm_transfer(link_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = db.get(TransferLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Transfer candidate not found")
    try:
        return confirm_transfer_link(db, link)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/transfers/{link_id}/reject")
def reject_transfer(link_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = db.get(TransferLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Transfer candidate not found")
    return reject_transfer_link(db, link)


@app.get("/api/dashboard/summary")
def get_dashboard_summary(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return dashboard_summary(db)


@app.get("/api/cash-flow")
def get_cash_flow(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return cash_flow_summary(db)


@app.get("/api/category-totals")
def get_category_totals(
    start_date: date | None = None,
    end_date: date | None = None,
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    return category_totals(db, start_date=start_date, end_date=end_date)


@app.get("/api/net-worth/timeseries")
def get_net_worth_timeseries(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    rows = db.execute(
        select(HoldingSnapshot.snapshot_date, HoldingSnapshot.market_value_cents).order_by(HoldingSnapshot.snapshot_date.asc(), HoldingSnapshot.id.asc())
    ).all()
    grouped: dict[str, int] = {}
    for snapshot_date, market_value_cents in rows:
        key = snapshot_date.isoformat()
        grouped[key] = grouped.get(key, 0) + market_value_cents
    return [{"date": key, "market_value_cents": value} for key, value in grouped.items()]


@app.get("/api/net-worth/accounts")
def get_net_worth_accounts(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return latest_net_worth_by_account(db)


@app.get("/api/investments/holdings")
def get_investment_holdings(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    metadata = {item.symbol.upper(): item for item in db.scalars(select(SecurityMetadata)).all()}
    prices = db.scalars(select(SecurityPrice).order_by(SecurityPrice.price_date.asc(), SecurityPrice.id.asc())).all()
    latest_prices: dict[str, SecurityPrice] = {}
    for price in prices:
        latest_prices[price.symbol.upper()] = price
    rows = db.scalars(select(HoldingSnapshot).order_by(HoldingSnapshot.snapshot_date.asc(), HoldingSnapshot.id.asc())).all()
    latest_dates: dict[int, object] = {}
    for row in rows:
        latest_dates[row.account_id] = max(latest_dates.get(row.account_id, row.snapshot_date), row.snapshot_date)
    latest_rows = [row for row in rows if latest_dates.get(row.account_id) == row.snapshot_date]
    payload = []
    for row in latest_rows:
        symbol_key = (row.symbol or "").upper()
        meta = metadata.get(symbol_key)
        latest_price = latest_prices.get(symbol_key)
        displayed_price_cents = latest_price.price_cents if latest_price else row.price_cents
        displayed_price_date = latest_price.price_date.isoformat() if latest_price else row.snapshot_date.isoformat()
        displayed_value_cents = row.market_value_cents
        if latest_price and row.quantity_basis_points is not None:
            displayed_value_cents = round((row.quantity_basis_points * latest_price.price_cents) / 10000)
        payload.append(
            {
                "id": row.id,
                "account_id": row.account_id,
                "account": accounts[row.account_id].display_name if row.account_id in accounts else "Unknown account",
                "snapshot_date": row.snapshot_date.isoformat(),
                "symbol": row.symbol,
                "description": meta.user_description if meta and meta.user_description else row.description,
                "csv_description": row.description,
                "user_description": meta.user_description if meta else None,
                "quantity": row.quantity_basis_points / 10000 if row.quantity_basis_points is not None else None,
                "price_cents": row.price_cents,
                "display_price_cents": displayed_price_cents,
                "price_date": displayed_price_date,
                "market_value_cents": row.market_value_cents,
                "display_market_value_cents": displayed_value_cents,
                "asset_class": row.asset_class,
            }
        )
    return payload


@app.patch("/api/investments/holding-metadata")
def update_holding_metadata(payload: HoldingMetadataUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    symbol = payload.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    metadata = db.scalar(select(SecurityMetadata).where(SecurityMetadata.symbol == symbol))
    if not metadata:
        metadata = SecurityMetadata(symbol=symbol)
        db.add(metadata)
        db.flush()
    metadata.user_description = payload.user_description.strip() if payload.user_description else None
    record_audit_event(db, "holding_metadata_update", "local-user", "security_metadata", symbol, {"symbol": symbol})
    db.commit()
    return {"ok": True}



def _delete_holding_row(db: Session, holding: HoldingSnapshot) -> None:
    record_audit_event(
        db,
        "holding_delete",
        "local-user",
        "holding_snapshot",
        str(holding.id),
        {"symbol": holding.symbol, "market_value_cents": holding.market_value_cents, "snapshot_date": holding.snapshot_date.isoformat()},
    )
    db.delete(holding)


@app.delete("/api/investments/holdings/bulk-delete")
def bulk_delete_holdings(payload: BulkDeleteRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    if not payload.ids:
        raise HTTPException(status_code=400, detail="Choose at least one holding to delete")
    holdings = db.scalars(select(HoldingSnapshot).where(HoldingSnapshot.id.in_(payload.ids))).all()
    found_ids = {holding.id for holding in holdings}
    missing_ids = [holding_id for holding_id in payload.ids if holding_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Holding row not found: {missing_ids[0]}")
    for holding in holdings:
        _delete_holding_row(db, holding)
    db.commit()
    return {"ok": True, "deleted": len(holdings)}

@app.delete("/api/investments/holdings/{holding_id}")
def delete_holding(holding_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    holding = db.get(HoldingSnapshot, holding_id)
    if not holding:
        raise HTTPException(status_code=404, detail="Holding row not found")
    _delete_holding_row(db, holding)
    db.commit()
    return {"ok": True}


@app.get("/api/investments/allocation")
def get_investment_allocation(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return latest_investment_allocation(db)


@app.get("/api/investments/value-timeseries")
def get_investment_value_timeseries(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return get_net_worth_timeseries(session, db)



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
    TransferLink,
    HoldingSnapshot,
    SecurityMetadata,
    SecurityPrice,
]


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


@app.get("/api/exports/app-data.json")
def export_app_data(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    payload = {
        "format": "private-finance-app-data",
        "version": 1,
        "generated_at": datetime.utcnow().isoformat(),
        "tables": {},
    }
    for model in APP_EXPORT_TABLES:
        rows = db.scalars(select(model).order_by(model.id.asc())).all()
        payload["tables"][model.__tablename__] = [_serialize_model(row) for row in rows]
    return JSONResponse(
        payload,
        headers={"Content-Disposition": "attachment; filename=private-finance-app-data.json"},
    )


@app.post("/api/imports/app-data")
async def import_app_data(
    request: Request,
    file: UploadFile = File(...),
    confirm_text: str = Form(...),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    require_csrf(request, session)
    if confirm_text != "IMPORT":
        raise HTTPException(status_code=400, detail='Type IMPORT to confirm replacing app data')
    try:
        payload = json.loads((await file.read()).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Choose a valid app-data JSON export") from exc
    if payload.get("format") != "private-finance-app-data" or not isinstance(payload.get("tables"), dict):
        raise HTTPException(status_code=400, detail="This file is not a private finance app-data export")

    tables = payload["tables"]
    for model in reversed(APP_EXPORT_TABLES):
        db.execute(delete(model))
    for model in APP_EXPORT_TABLES:
        for row in tables.get(model.__tablename__, []):
            db.add(_deserialize_model(model, row))
    record_audit_event(db, "app_data_import", "local-user", "app_data", file.filename or "upload", {"version": payload.get("version")})
    db.commit()
    return {"ok": True}

@app.get("/api/exports/transactions.csv")
def export_transactions(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    categories = {category.id: category.label for category in db.scalars(select(Category)).all()}
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Posted Date", "Account", "Institution", "Description", "Amount", "Type", "Category", "Review Status", "Note"])
    rows = db.scalars(select(Transaction).where(Transaction.status == "active").order_by(Transaction.transaction_date.asc(), Transaction.id.asc())).all()
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


@app.get("/api/backups")
def get_backups(session: SessionToken = Depends(current_session)):
    return {"backup_dir": str(Path(settings.backup_dir).resolve()), "backups": list_backups()}


@app.post("/api/backups")
def backup_database(request: Request, destination: str | None = None, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        resolved = resolve_backup_destination(destination)
        output = create_backup(resolved)
    except BackupError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit_event(db, "backup_create", "local-user", "backup", str(output), {"destination": str(output)})
    db.commit()
    return {"path": str(output)}


@app.post("/api/backups/restore")
def restore_database(request: Request, source: str, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        resolved = resolve_restore_source(source)
    except BackupError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    # Audit before the swap: the restored database's audit trail may predate this event.
    record_audit_event(db, "backup_restore", "local-user", "backup", str(resolved), {"source": str(resolved)})
    db.commit()
    db.close()
    try:
        safety_copy = restore_backup(resolved)
    except BackupError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    initialize_database()
    return {"ok": True, "pre_restore_copy": str(safety_copy)}


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def api_not_found(full_path: str):
    raise HTTPException(status_code=404, detail=f"API endpoint not found: /api/{full_path}")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    index = frontend_dist / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return {"message": "Frontend not built yet", "path": full_path}
