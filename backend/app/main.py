from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .audit import record_audit_event
from .bootstrap import initialize_database
from .config import settings
from .db import get_db
from .middleware import LocalhostSecurityMiddleware
from .models import Account, AppUser, Category, CategoryRule, HoldingSnapshot, ImportBatch, ImportPreset, Institution, SecurityMetadata, SecurityPrice, SessionToken, StagingRow, Transaction, TransactionSplit, TransferLink
from .money import cents_to_decimal_string, escape_csv_formula
from .schemas import AccountCreate, AccountUpdate, BulkDeleteRequest, CategoryCreate, CategoryUpdate, DeleteConfirmRequest, HoldingMetadataUpdate, ImportPresetCreate, LoginRequest, RuleApplyRequest, RuleCreate, SetupRequest, SplitSetRequest, TransactionReviewUpdate, TransferLinkCreate
from .security import clear_login_failures, create_session, enforce_login_rate_limit, ensure_setup_state, get_session_from_request, hash_password, record_login_failure, require_csrf, set_session_cookie, verify_password
from .services.backups import create_backup, restore_backup
from .services.importers import commit_import, detect_preset_from_content, preview_import, suggest_account_for_import
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
    preset_type = detect_preset_from_content(content.decode("utf-8-sig"))
    if not preset_type:
        raise HTTPException(status_code=400, detail="Could not detect import preset")
    try:
        preview = preview_import(content, preset_type)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"preset_type": preset_type, "rows": preview.rows[:25], "warnings": preview.warnings}


@app.post("/api/imports/commit")
async def imports_commit(request: Request, account_id: int, preset_id: int | None = None, file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    preset = db.get(ImportPreset, preset_id) if preset_id else None
    content = await file.read()
    try:
        result = commit_import(db, account, preset, file.filename or "import.csv", content)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
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
        }
        for row in rows
    ]


@app.patch("/api/transactions/{transaction_id}")
def update_transaction(transaction_id: int, payload: TransactionReviewUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = db.get(Transaction, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    updates = payload.model_dump(exclude_unset=True)
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
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id))
    for split in payload.splits:
        db.add(TransactionSplit(transaction_id=transaction_id, category_id=split.category_id, amount_cents=split.amount_cents, note=split.note))
    record_audit_event(db, "transaction_split", "local-user", "transaction", str(transaction.id), {"split_count": len(payload.splits)})
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
        }
        for row in rows
    ]


@app.post("/api/rules")
def create_rule(payload: RuleCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
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
def get_category_totals(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return category_totals(db)


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
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Description", "Amount", "Type", "Review Status"])
    rows = db.scalars(select(Transaction).where(Transaction.status == "active").order_by(Transaction.transaction_date.asc())).all()
    for row in rows:
        writer.writerow(
            [
                row.transaction_date.isoformat(),
                escape_csv_formula(row.raw_description),
                cents_to_decimal_string(row.amount_cents),
                row.transaction_type,
                row.review_status,
            ]
        )
    path = Path("data/exports")
    path.mkdir(parents=True, exist_ok=True)
    export_path = path / "transactions.csv"
    export_path.write_text(output.getvalue(), encoding="utf-8")
    return FileResponse(export_path)


@app.post("/api/backups")
def backup_database(request: Request, destination: str, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    output = create_backup(Path(destination))
    record_audit_event(db, "backup_create", "local-user", "backup", str(output), {"destination": str(output)})
    db.commit()
    return {"path": str(output)}


@app.post("/api/backups/restore")
def restore_database(request: Request, source: str, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    restore_backup(Path(source))
    record_audit_event(db, "backup_restore", "local-user", "backup", str(source), {"source": source})
    db.commit()
    return {"ok": True}


@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def api_not_found(full_path: str):
    raise HTTPException(status_code=404, detail=f"API endpoint not found: /api/{full_path}")


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    index = frontend_dist / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text(encoding="utf-8"))
    return {"message": "Frontend not built yet", "path": full_path}
