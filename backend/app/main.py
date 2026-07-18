from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import record_audit_event
from .api.aggregation import router as aggregation_router
from .api.dependencies import current_session, transaction_filter_dependency
from .bootstrap import initialize_database
from .config import settings
from .db import get_db
from .middleware import LocalhostSecurityMiddleware
from .models import Account, AccountIdentifier, AppUser, Category, CategoryRule, DuplicatePairDecision, ExpenseAllocation, HoldingLot, HoldingSnapshot, ImportBatch, ImportPreset, ImportSignProfile, Institution, NetWorthSnapshot, PaymentVerificationDismissal, RefundLink, RefundPairDecision, RefundReviewResolution, SecurityMetadata, SecurityPrice, SessionToken, StatementCheckpoint, StatementPdfPattern, StagingRow, Transaction, TransactionSplit, TransferLink
from .money import cents_to_decimal_string, escape_csv_formula
from .schemas import AccountCreate, AccountIdentifierCreate, AccountUpdate, BulkDeleteRequest, BulkDuplicateResolutionRequest, BulkIdsRequest, BulkRuleCreateRequest, BulkTransactionUpdateRequest, CategoryCreate, CategoryUpdate, DeleteConfirmRequest, DuplicateResolutionRequest, DuplicateSelectionPreviewRequest, DuplicateSelectionResolutionRequest, ExternalPaymentRequest, HistoricalRefundBulkRequest, HoldingLotCreate, HoldingLotUpdate, HoldingMetadataUpdate, ImportPresetCreate, LoginRequest, ManualTransactionCreate, MonthlyAllocationRequest, NetWorthSnapshotUpdate, NetWorthSnapshotUpsert, OperationBulkUpdateRequest, PasswordChangeRequest, PaymentVerificationDismissRequest, RefundConfirmRequest, RefundLinkCreate, RefundNoExpenseRequest, RefundSelectionRequest, ReviewStatus, RuleApplyRequest, RuleCreate, RuleUpdate, SetupRequest, SplitSetRequest, StatementBalancePreviewUpdate, StatementCheckpointCreate, TransactionFilter, TransactionReviewUpdate, TransactionType, TransferLinkCreate, UndoOperationRequest
from .security import clear_login_failures, create_session, enforce_login_rate_limit, ensure_setup_state, hash_password, password_needs_rehash, purge_expired_sessions, record_login_failure, require_csrf, set_session_cookie, verify_password
from .services.accounts import cleanup_imported_accounts
from .services.account_identifiers import record_account_identifier
from .services.backups import BackupError, create_backup, list_backups, resolve_backup_destination, resolve_restore_source, restore_backup
from .services.duplicates import duplicate_queue_summary, link_historical_refund_pairs, pending_duplicate_pairs, preview_duplicate_selection, preview_historical_refund_links, preview_safe_duplicate_resolution, resolve_all_exact_duplicates, resolve_duplicate, resolve_duplicate_selection, resolve_safe_duplicate_reimports
from .services.duplicate_scan import scan_ledger_duplicates
from .services.importers import PreviewResult, annotate_import_interpretation, commit_categorized_history, commit_import, commit_reviewed_categorized_history, decode_text, detect_preset_from_content, preview_import, review_categorized_history, suggest_account_for_import
from .services.import_inbox import confirm_pending_import, discard_pending_import, inbox_directory, pending_import_batches, scan_import_inbox, stage_uploaded_import
from .services.importers_ofx import parse_ofx, suggest_ofx_account
from .services.statement_pdf import extract_statement_pdf, saved_pdf_pattern, statement_preview_row, suggest_pdf_account, update_statement_preview
from .services.history_cleanup import apply_categorized_history_sign_cleanup, preview_categorized_history_sign_cleanup
from .services.mutation_log import MutationChange, changed_values, full_values, journal_mutation
from .services.operation_history import OperationConflict, list_operations, operation_detail, undo_operation
from .services.reconciliation import list_reconciliation_statuses, reconciliation_status, save_manual_checkpoint
from .services.refunds import OverRefundError, confirm_refund_link, confirm_refund_selections, create_manual_refund_link, create_refund_suggestions, delete_refund_link, list_manual_refund_candidates, list_refund_links, list_refund_suggestion_groups, reject_refund_candidates, reject_refund_link, resolve_refunds_without_expense
from .services.reporting import cash_flow_summary, category_totals, dashboard_summary, latest_investment_allocation, latest_net_worth_by_account
from .services.sign_profiles import profile_payload, resolution_payload, resolve_sign_preview, save_sign_profile
from .services.snapshots import account_is_anchored, current_account_value, net_worth_contributors, net_worth_series, net_worth_stats, net_worth_unanchored_accounts, refresh_holding_net_worth_snapshot, upsert_net_worth_snapshot
from .services.transaction_filters import transaction_filter_conditions
from .services.transaction_queries import get_live_transaction, live_transaction_filters, live_transaction_select
from .services.transfers import auto_dismiss_reclassified_payment, confirm_transfer_link, create_transfer_suggestions, dismiss_payment_verification, list_payment_verification, list_unconfirmed_transfers, reject_transfer_link, settle_payment_from_external

app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["content-type", settings.csrf_header_name],
)
app.add_middleware(LocalhostSecurityMiddleware)
app.include_router(aggregation_router)

UNASSIGNED_ACCOUNT_MARKER = "SYSTEM"
CATEGORYLESS_TRANSACTION_TYPES = {TransactionType.TRANSFER.value, TransactionType.CREDIT_CARD_PAYMENT.value}
CATEGORY_REQUIRED_FOR_CONFIRMATION = {TransactionType.EXPENSE.value, TransactionType.REFUND.value}


def actor_for_session(session: SessionToken) -> str:
    return f"user:{session.user_id}"


def normalize_transaction_labels(value: object) -> str | None:
    labels = []
    for raw in str(value or "").split(","):
        label = " ".join(raw.strip().casefold().replace("|", "").split())
        if label and label not in labels:
            labels.append(label)
    return f"|{'|'.join(labels)}|" if labels else None


def normalize_transaction_updates(updates: dict) -> dict:
    if updates.get("transaction_type") in CATEGORYLESS_TRANSACTION_TYPES:
        updates["category_id"] = None
    return updates


def validate_transaction_confirmation(transaction: Transaction, updates: dict) -> None:
    next_status = updates.get("review_status", transaction.review_status)
    next_type = updates.get("transaction_type", transaction.transaction_type)
    next_category_id = updates.get("category_id", transaction.category_id)
    if next_status == ReviewStatus.CONFIRMED.value and next_type in CATEGORY_REQUIRED_FOR_CONFIRMATION and next_category_id is None:
        noun = "refund" if next_type == TransactionType.REFUND.value else "expense"
        raise HTTPException(status_code=400, detail=f"Choose a category before confirming this {noun}")


def append_payment_reclassification_dismissal(db: Session, transaction: Transaction, updates: dict, changes: list[MutationChange]) -> None:
    if "transaction_type" not in updates or transaction.transaction_type == TransactionType.CREDIT_CARD_PAYMENT.value:
        return
    dismissal = auto_dismiss_reclassified_payment(db, transaction)
    if dismissal:
        changes.append(MutationChange(dismissal.id, None, full_values(dismissal), entity_type="payment_verification_dismissal"))


def normalized_rule_category(db: Session, category_id: int | None, transaction_type: TransactionType | str) -> int | None:
    type_value = transaction_type.value if isinstance(transaction_type, TransactionType) else transaction_type
    if type_value in CATEGORYLESS_TRANSACTION_TYPES:
        return None
    if category_id is None:
        raise HTTPException(status_code=400, detail="Choose a category for this rule")
    if not db.get(Category, category_id):
        raise HTTPException(status_code=400, detail="Category not found")
    return category_id


def transaction_labels(value: str | None) -> list[str]:
    return [label for label in (value or "").strip("|").split("|") if label]


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


@app.get("/api/operations")
def get_operations(
    limit: int = Query(default=50, ge=1, le=200),
    entity_type: str | None = None,
    actor: str | None = None,
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    return list_operations(db, limit=limit, entity_type=entity_type, actor=actor)


@app.get("/api/operations/{operation_id}")
def get_operation(operation_id: str, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    result = operation_detail(db, operation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Operation not found")
    return result


@app.post("/api/operations/{operation_id}/undo")
def undo_logged_operation(
    operation_id: str,
    payload: UndoOperationRequest,
    request: Request,
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    require_csrf(request, session)
    try:
        result = undo_operation(
            db,
            operation_id=operation_id,
            actor=actor_for_session(session),
            unconflicted_only=payload.unconflicted_only,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OperationConflict as error:
        raise HTTPException(status_code=409, detail={"message": str(error), "conflicts": error.entity_ids}) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit_event(db, "operation_undo", actor_for_session(session), "operation", operation_id, result)
    db.commit()
    return result


@app.post("/api/operations/bulk-update")
def operation_bulk_update(payload: OperationBulkUpdateRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transactions = db.scalars(live_transaction_select(Transaction.id.in_(payload.ids))).all()
    if len(transactions) != len(set(payload.ids)):
        raise HTTPException(status_code=404, detail="One or more transactions were not found")
    updates = normalize_transaction_updates(payload.patch.model_dump(exclude_unset=True))
    if not updates:
        raise HTTPException(status_code=400, detail="Provide at least one field to update")
    if "account_id" in updates:
        account = db.get(Account, updates["account_id"])
        if not account or account.last_four == UNASSIGNED_ACCOUNT_MARKER:
            raise HTTPException(status_code=400, detail="Choose a valid account")
    if "category_id" in updates and updates["category_id"] is not None and not db.get(Category, updates["category_id"]):
        raise HTTPException(status_code=400, detail="Category not found")
    for transaction in transactions:
        validate_transaction_confirmation(transaction, updates)
    changes: list[MutationChange] = []
    for transaction in transactions:
        before = changed_values(transaction, updates.keys())
        for key, value in updates.items():
            setattr(transaction, key, value)
        changes.append(MutationChange(transaction.id, before, changed_values(transaction, updates.keys())))
        append_payment_reclassification_dismissal(db, transaction, updates, changes)
    operation_id = journal_mutation(db, kind="bulk_update", entity_type="transaction", actor=actor_for_session(session), description=f"Updated {len(transactions)} transactions", changes=changes)
    db.commit()
    return {"ok": True, "updated": len(transactions), "operation_id": operation_id}


@app.post("/api/operations/bulk-create-rules")
def operation_bulk_create_rules(payload: BulkRuleCreateRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    rule_values = []
    for rule_payload in payload.rules:
        values = rule_payload.model_dump()
        values["category_id"] = normalized_rule_category(db, rule_payload.category_id, rule_payload.suggested_transaction_type)
        rule_values.append(values)
    rules = [CategoryRule(**values) for values in rule_values]
    db.add_all(rules)
    db.flush()
    operation_id = journal_mutation(db, kind="create", entity_type="category_rule", actor=actor_for_session(session), description=f"Created {len(rules)} category rules", changes=[MutationChange(rule.id, None, full_values(rule)) for rule in rules])
    db.commit()
    return {"ok": True, "created": len(rules), "operation_id": operation_id}


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
        "categories": [{"id": category.id, "key": category.key, "label": category.label, "parent_id": category.parent_id} for category in db.scalars(select(Category).order_by(Category.label.asc())).all()],
        "net_worth_notice": net_worth_unanchored_accounts(db),
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
        last_four=payload.last_four or None,
        net_worth_inclusion="never" if payload.account_type == "external" else payload.net_worth_inclusion,
    )
    db.add(account)
    db.flush()
    identifier = None
    if payload.last_four:
        try:
            identifier = record_account_identifier(db, account, payload.last_four, source="manual")
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    create_changes = [MutationChange(account.id, None, full_values(account))]
    if identifier:
        create_changes.append(MutationChange(identifier.id, None, full_values(identifier), entity_type="account_identifier"))
    operation_id = journal_mutation(db, kind="create", entity_type="account", actor=actor_for_session(session), description=f'Created account "{account.display_name}"', changes=create_changes)
    record_audit_event(db, "account_create", "local-user", "account", str(account.id), payload.model_dump())
    db.commit()
    return {"id": account.id, "operation_id": operation_id}


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
    accounts = db.scalars(select(Account).where((Account.last_four.is_(None)) | (Account.last_four != UNASSIGNED_ACCOUNT_MARKER)).order_by(Account.display_name.asc())).all()
    result = []
    recent_activity_start = date.today() - timedelta(days=30)
    for account in accounts:
        anchored = account_is_anchored(db, account.id)
        latest_running_balance = db.scalar(
            live_transaction_select(Transaction.account_id == account.id, Transaction.running_balance_cents.is_not(None))
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .limit(1)
        )
        latest_holding_date = db.scalar(select(func.max(HoldingSnapshot.snapshot_date)).where(HoldingSnapshot.account_id == account.id))
        latest_anchor_date = max(
            filter(None, [
                db.scalar(select(func.max(NetWorthSnapshot.snapshot_date)).where(NetWorthSnapshot.account_id == account.id)),
                db.scalar(select(func.max(StatementCheckpoint.statement_date)).where(StatementCheckpoint.account_id == account.id)),
            ]),
            default=None,
        )
        if account.account_type == "external":
            sidebar_balance_cents = None
            sidebar_balance_kind = "excluded"
            sidebar_balance_as_of = None
        elif account.net_worth_inclusion == "auto" and not anchored:
            sidebar_balance_cents = None
            sidebar_balance_kind = "unanchored"
            sidebar_balance_as_of = None
        elif account.account_type in {"brokerage", "retirement"} and latest_holding_date:
            sidebar_balance_cents = db.scalar(
                select(func.coalesce(func.sum(HoldingSnapshot.market_value_cents), 0)).where(
                    HoldingSnapshot.account_id == account.id, HoldingSnapshot.snapshot_date == latest_holding_date
                )
            )
            sidebar_balance_kind = "investment_snapshot"
            sidebar_balance_as_of = latest_holding_date.isoformat()
        elif anchored:
            sidebar_balance_cents = current_account_value(db, account)
            sidebar_balance_kind = "anchored_balance"
            sidebar_balance_as_of = latest_anchor_date.isoformat() if latest_anchor_date else None
        elif latest_running_balance:
            sidebar_balance_cents = latest_running_balance.running_balance_cents
            sidebar_balance_kind = "running_balance"
            sidebar_balance_as_of = latest_running_balance.transaction_date.isoformat()
        else:
            sidebar_balance_cents = db.scalar(
                select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(*live_transaction_filters(
                    Transaction.account_id == account.id,
                    Transaction.transaction_date >= recent_activity_start,
                ))
            )
            sidebar_balance_kind = "recent_activity"
            latest_transaction_date = db.scalar(
                select(func.max(Transaction.transaction_date)).where(*live_transaction_filters(Transaction.account_id == account.id))
            )
            sidebar_balance_as_of = latest_transaction_date.isoformat() if latest_transaction_date else None
        result.append({
            "id": account.id,
            "institution_name": account.institution.name if account.institution else None,
            "display_name": account.display_name,
            "account_type": account.account_type,
            "currency": account.currency,
            "status": account.status,
            "last_four": account.last_four,
            "net_worth_inclusion": account.net_worth_inclusion,
            "is_anchored": anchored,
            "sidebar_balance_cents": sidebar_balance_cents,
            "sidebar_balance_kind": sidebar_balance_kind,
            "sidebar_balance_as_of": sidebar_balance_as_of,
        })
    return result


@app.get("/api/accounts/{account_id}/identifiers")
def list_account_identifiers(account_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    identifiers = db.scalars(
        select(AccountIdentifier)
        .where(AccountIdentifier.account_id == account_id)
        .order_by(AccountIdentifier.is_current.desc(), AccountIdentifier.created_at.desc())
    ).all()
    return [
        {
            "id": identifier.id,
            "identifier_type": identifier.identifier_type,
            "last_four": identifier.identifier_value,
            "is_current": identifier.is_current,
            "source": identifier.source,
            "valid_from": identifier.valid_from,
            "valid_to": identifier.valid_to,
        }
        for identifier in identifiers
    ]


@app.post("/api/accounts/{account_id}/identifiers")
def create_account_identifier(account_id: int, payload: AccountIdentifierCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account or account.status != "active":
        raise HTTPException(status_code=404, detail="Active account not found")
    if account.account_type != "credit_card":
        raise HTTPException(status_code=400, detail="Replacement card numbers can only be added to credit-card accounts")
    before = changed_values(account, ["last_four"])
    identifier_before = {
        row.id: full_values(row)
        for row in db.scalars(select(AccountIdentifier).where(AccountIdentifier.account_id == account.id)).all()
    }
    try:
        identifier = record_account_identifier(
            db,
            account,
            payload.last_four,
            make_current=payload.make_current,
            source=payload.source,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    identifier_changes = [
        MutationChange(row.id, identifier_before.get(row.id), full_values(row), entity_type="account_identifier")
        for row in db.scalars(select(AccountIdentifier).where(AccountIdentifier.account_id == account.id)).all()
        if identifier_before.get(row.id) != full_values(row)
    ]
    operation_id = journal_mutation(
        db,
        kind="update",
        entity_type="account",
        actor=actor_for_session(session),
        description=f'Updated card number for "{account.display_name}"',
        changes=[MutationChange(account.id, before, changed_values(account, ["last_four"])), *identifier_changes],
    )
    record_audit_event(
        db,
        "account_identifier_create",
        "local-user",
        "account",
        str(account.id),
        {"last_four": identifier.identifier_value, "make_current": payload.make_current, "source": payload.source},
    )
    db.commit()
    return {"ok": True, "account_id": account.id, "last_four": account.last_four, "operation_id": operation_id}


@app.get("/api/reconciliation")
def get_reconciliation_statuses(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_reconciliation_statuses(db)


@app.post("/api/accounts/{account_id}/statement-checkpoints")
def create_statement_checkpoint(account_id: int, payload: StatementCheckpointCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account or account.status != "active":
        raise HTTPException(status_code=404, detail="Active account not found")
    saved = save_manual_checkpoint(
        db,
        account=account,
        statement_date=payload.statement_date,
        statement_balance_cents=payload.statement_balance_cents,
        actor=actor_for_session(session),
    )
    db.commit()
    return {**saved, "reconciliation": reconciliation_status(db, account)}


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
    changed_fields = {"institution_id" if key == "institution_name" else key for key in updates}
    if updates.get("account_type") == "external":
        changed_fields.add("net_worth_inclusion")
    before = changed_values(account, changed_fields)
    identifier_before = {
        row.id: full_values(row)
        for row in db.scalars(select(AccountIdentifier).where(AccountIdentifier.account_id == account.id)).all()
    } if "last_four" in changed_fields else {}
    if "institution_name" in updates:
        institution = upsert_institution(db, updates.pop("institution_name"))
        account.institution_id = institution.id if institution else None
    updated_last_four = updates.pop("last_four", None) if "last_four" in updates else None
    for key, value in updates.items():
        setattr(account, key, value)
    if updated_last_four:
        try:
            record_account_identifier(db, account, updated_last_four, source="manual")
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    elif "last_four" in changed_fields and updated_last_four is None:
        account.last_four = None
        for identifier in db.scalars(
            select(AccountIdentifier).where(
                AccountIdentifier.account_id == account.id,
                AccountIdentifier.is_current.is_(True),
            )
        ).all():
            identifier.is_current = False
            identifier.valid_to = date.today()
    if account.account_type == "external":
        account.net_worth_inclusion = "never"
    identifier_changes = [
        MutationChange(row.id, identifier_before.get(row.id), full_values(row), entity_type="account_identifier")
        for row in db.scalars(select(AccountIdentifier).where(AccountIdentifier.account_id == account.id)).all()
        if identifier_before.get(row.id) != full_values(row)
    ]
    operation_id = journal_mutation(db, kind="update", entity_type="account", actor=actor_for_session(session), description=f'Updated account "{account.display_name}"', changes=[MutationChange(account.id, before, changed_values(account, changed_fields)), *identifier_changes])
    record_audit_event(db, "account_update", "local-user", "account", str(account.id), payload.model_dump(exclude_unset=True))
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.post("/api/accounts/{account_id}/archive")
def archive_account(account_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    before = changed_values(account, ["status"])
    account.status = "archived"
    operation_id = journal_mutation(db, kind="update", entity_type="account", actor=actor_for_session(session), description=f'Archived account "{account.display_name}"', changes=[MutationChange(account.id, before, changed_values(account, ["status"]))])
    record_audit_event(db, "account_archive", "local-user", "account", str(account.id), {"status": "archived"})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


def category_key_from_label(label: str) -> str:
    key = "".join(char.lower() if char.isalnum() else "_" for char in label.strip())
    key = "_".join(part for part in key.split("_") if part)
    return key[:60] or "category"


def normalized_category_label(label: str) -> str:
    """Compare category labels without case, whitespace, or punctuation noise."""
    return "".join(character.casefold() for character in label if character.isalnum())


def cleanup_duplicate_categories(db: Session, actor: str = "local-user") -> dict:
    """Merge categories that differ only in presentation, preserving references."""
    categories = db.scalars(select(Category).order_by(Category.id.asc())).all()
    canonical_by_label: dict[str, Category] = {}
    merged = 0
    reassigned = 0
    changes: list[MutationChange] = []
    for category in categories:
        normalized = normalized_category_label(category.label)
        if not normalized:
            continue
        replacement = canonical_by_label.get(normalized)
        if replacement is None:
            canonical_by_label[normalized] = category
            continue
        reference_counts = {
            "transactions": db.scalar(select(func.count(Transaction.id)).where(Transaction.category_id == category.id)) or 0,
            "splits": db.scalar(select(func.count(TransactionSplit.id)).where(TransactionSplit.category_id == category.id)) or 0,
            "allocations": db.scalar(select(func.count(ExpenseAllocation.id)).where(ExpenseAllocation.category_id == category.id)) or 0,
            "rules": db.scalar(select(func.count(CategoryRule.id)).where(CategoryRule.category_id == category.id)) or 0,
        }
        changes.append(MutationChange(category.id, full_values(category), None, entity_type="category"))
        reference_groups = [
            ("transaction", db.scalars(select(Transaction).where(Transaction.category_id == category.id)).all(), "category_id"),
            ("transaction_split", db.scalars(select(TransactionSplit).where(TransactionSplit.category_id == category.id)).all(), "category_id"),
            ("expense_allocation", db.scalars(select(ExpenseAllocation).where(ExpenseAllocation.category_id == category.id)).all(), "category_id"),
            ("category_rule", db.scalars(select(CategoryRule).where(CategoryRule.category_id == category.id)).all(), "category_id"),
            ("category", db.scalars(select(Category).where(Category.parent_id == category.id)).all(), "parent_id"),
        ]
        for entity_type, rows, field in reference_groups:
            changes.extend(MutationChange(row.id, changed_values(row, [field]), {"id": row.id, field: replacement.id}, entity_type=entity_type) for row in rows)
        db.execute(update(Transaction).where(Transaction.category_id == category.id).values(category_id=replacement.id))
        db.execute(update(TransactionSplit).where(TransactionSplit.category_id == category.id).values(category_id=replacement.id))
        db.execute(update(ExpenseAllocation).where(ExpenseAllocation.category_id == category.id).values(category_id=replacement.id))
        db.execute(update(CategoryRule).where(CategoryRule.category_id == category.id).values(category_id=replacement.id))
        db.execute(update(Category).where(Category.parent_id == category.id).values(parent_id=replacement.id))
        record_audit_event(db, "category_merge", actor, "category", str(replacement.id), {"source_category_id": category.id, "source_label": category.label, "target_label": replacement.label, **reference_counts})
        db.delete(category)
        merged += 1
        reassigned += sum(reference_counts.values())
    operation_id = journal_mutation(db, kind="merge", entity_type="mixed", actor=actor, description=f"Merged {merged} duplicate categories", changes=changes) if changes else None
    db.commit()
    return {"merged": merged, "reassigned": reassigned, "operation_id": operation_id}



def _require_delete_confirmation(confirm_text: str) -> None:
    if confirm_text != "DELETE":
        raise HTTPException(status_code=400, detail='Type DELETE to confirm deletion')


def _delete_transaction_row(db: Session, transaction: Transaction) -> None:
    """Hard-delete an internal duplicate during account-merge maintenance."""
    db.execute(update(Transaction).where(Transaction.linked_transaction_id == transaction.id).values(linked_transaction_id=None))
    db.execute(update(Transaction).where(Transaction.duplicate_of_transaction_id == transaction.id).values(duplicate_of_transaction_id=None))
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id == transaction.id))
    db.execute(delete(ExpenseAllocation).where(ExpenseAllocation.transaction_id == transaction.id))
    db.execute(delete(TransferLink).where((TransferLink.from_transaction_id == transaction.id) | (TransferLink.to_transaction_id == transaction.id)))
    db.execute(delete(RefundLink).where((RefundLink.expense_transaction_id == transaction.id) | (RefundLink.refund_transaction_id == transaction.id)))
    db.execute(delete(RefundPairDecision).where((RefundPairDecision.expense_transaction_id == transaction.id) | (RefundPairDecision.refund_transaction_id == transaction.id)))
    db.execute(delete(RefundReviewResolution).where(RefundReviewResolution.refund_transaction_id == transaction.id))
    db.execute(delete(PaymentVerificationDismissal).where(PaymentVerificationDismissal.transaction_id == transaction.id))
    db.execute(delete(DuplicatePairDecision).where((DuplicatePairDecision.transaction_a_id == transaction.id) | (DuplicatePairDecision.transaction_b_id == transaction.id)))
    record_audit_event(
        db,
        "transaction_delete",
        "local-user",
        "transaction",
        str(transaction.id),
        {"description": transaction.raw_description, "amount_cents": transaction.amount_cents, "date": transaction.transaction_date.isoformat()},
    )
    db.delete(transaction)


def _soft_delete_transaction(db: Session, transaction: Transaction, actor: str) -> str:
    return _soft_delete_transactions(db, [transaction], actor)


def _soft_delete_transactions(db: Session, transactions: list[Transaction], actor: str) -> str:
    deleted_at = datetime.now(UTC).replace(tzinfo=None)
    changes: list[MutationChange] = []
    for transaction in transactions:
        before = changed_values(transaction, ["deleted_at"])
        transaction.deleted_at = deleted_at
        changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["deleted_at"])))
    operation_id = journal_mutation(
        db,
        kind="delete",
        entity_type="transaction",
        actor=actor,
        description=(
            f'Deleted transaction "{transactions[0].raw_description}"'
            if len(transactions) == 1
            else f"Deleted {len(transactions)} transactions"
        ),
        changes=changes,
    )
    for transaction in transactions:
        record_audit_event(
            db,
            "transaction_delete",
            actor,
            "transaction",
            str(transaction.id),
            {"description": transaction.raw_description, "operation_id": operation_id},
        )
    return operation_id


def _restore_transactions(db: Session, transactions: list[Transaction], actor: str) -> str:
    changes: list[MutationChange] = []
    for transaction in transactions:
        before = changed_values(transaction, ["deleted_at"])
        transaction.deleted_at = None
        changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["deleted_at"])))
    return journal_mutation(
        db,
        kind="restore",
        entity_type="transaction",
        actor=actor,
        description=(
            f'Restored transaction "{transactions[0].raw_description}"'
            if len(transactions) == 1
            else f"Restored {len(transactions)} transactions"
        ),
        changes=changes,
    )


def _delete_account_tree(db: Session, account: Account) -> list[MutationChange]:
    transactions = db.scalars(select(Transaction).where(Transaction.account_id == account.id)).all()
    if account.last_four == UNASSIGNED_ACCOUNT_MARKER:
        raise HTTPException(status_code=400, detail="The system account used for transaction review cannot be deleted")
    presets = db.scalars(select(ImportPreset).where(ImportPreset.account_id == account.id)).all()
    sign_profiles = db.scalars(select(ImportSignProfile).where(ImportSignProfile.account_id == account.id)).all()
    batches = db.scalars(select(ImportBatch).where(ImportBatch.account_id == account.id)).all()
    staging_rows = db.scalars(select(StagingRow).where(StagingRow.account_id == account.id)).all()
    holdings = db.scalars(select(HoldingSnapshot).where(HoldingSnapshot.account_id == account.id)).all()
    lots = db.scalars(select(HoldingLot).where(HoldingLot.account_id == account.id)).all()
    checkpoints = db.scalars(select(StatementCheckpoint).where(StatementCheckpoint.account_id == account.id)).all()
    identifiers = db.scalars(select(AccountIdentifier).where(AccountIdentifier.account_id == account.id)).all()
    changes: list[MutationChange] = [MutationChange(account.id, full_values(account), None, entity_type="account")]
    changes.extend(MutationChange(preset.id, full_values(preset), None, entity_type="import_preset") for preset in presets)
    changes.extend(MutationChange(profile.id, full_values(profile), None, entity_type="import_sign_profile") for profile in sign_profiles)
    changes.extend(MutationChange(batch.id, full_values(batch), None, entity_type="import_batch") for batch in batches)
    changes.extend(MutationChange(row.id, full_values(row), None, entity_type="staging_row") for row in staging_rows)
    changes.extend(MutationChange(holding.id, full_values(holding), None, entity_type="holding_snapshot") for holding in holdings)
    changes.extend(MutationChange(lot.id, full_values(lot), None, entity_type="holding_lot") for lot in lots)
    changes.extend(MutationChange(checkpoint.id, full_values(checkpoint), None, entity_type="statement_checkpoint") for checkpoint in checkpoints)
    changes.extend(MutationChange(identifier.id, full_values(identifier), None, entity_type="account_identifier") for identifier in identifiers)
    unassigned_account = None
    if transactions:
        unassigned_account = Account(
            display_name=f"Needs account ({account.display_name})",
            account_type="other",
            currency=account.currency,
            status="archived",
            last_four=UNASSIGNED_ACCOUNT_MARKER,
        )
        db.add(unassigned_account)
        db.flush()
        for transaction in transactions:
            before = changed_values(transaction, ["account_id", "import_batch_id", "review_status"])
            transaction.account_id = unassigned_account.id
            transaction.import_batch_id = None
            transaction.review_status = "needs_review"
            changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["account_id", "import_batch_id", "review_status"]), entity_type="transaction"))
        changes.append(MutationChange(unassigned_account.id, None, full_values(unassigned_account), entity_type="account"))
    db.execute(delete(StagingRow).where(StagingRow.account_id == account.id))
    db.execute(delete(HoldingSnapshot).where(HoldingSnapshot.account_id == account.id))
    db.execute(delete(HoldingLot).where(HoldingLot.account_id == account.id))
    db.execute(delete(StatementCheckpoint).where(StatementCheckpoint.account_id == account.id))
    db.execute(delete(ImportBatch).where(ImportBatch.account_id == account.id))
    db.execute(delete(ImportPreset).where(ImportPreset.account_id == account.id))
    db.execute(delete(ImportSignProfile).where(ImportSignProfile.account_id == account.id))
    db.execute(delete(AccountIdentifier).where(AccountIdentifier.account_id == account.id))
    record_audit_event(
        db,
        "account_delete",
        "local-user",
        "account",
        str(account.id),
        {"display_name": account.display_name, "account_type": account.account_type, "preserved_transactions": len(transactions)},
    )
    db.delete(account)
    return changes


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
    changes: list[MutationChange] = []
    for account in accounts:
        changes.extend(_delete_account_tree(db, account))
    operation_id = journal_mutation(db, kind="delete", entity_type="mixed", actor=actor_for_session(session), description=f"Deleted {len(accounts)} accounts", changes=changes)
    db.commit()
    return {"ok": True, "deleted": len(accounts), "operation_id": operation_id}


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    changes = _delete_account_tree(db, account)
    operation_id = journal_mutation(db, kind="delete", entity_type="mixed", actor=actor_for_session(session), description=f'Deleted account "{account.display_name}"', changes=changes)
    db.commit()
    return {"ok": True, "operation_id": operation_id}

@app.post("/api/categories")
def create_category(payload: CategoryCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Category label is required")
    normalized_label = normalized_category_label(label)
    if payload.parent_id is not None and not db.get(Category, payload.parent_id):
        raise HTTPException(status_code=400, detail="Parent category not found")
    existing = next((category for category in db.scalars(select(Category).order_by(Category.id.asc())).all() if normalized_category_label(category.label) == normalized_label), None)
    if existing:
        return {"id": existing.id, "key": existing.key, "label": existing.label, "parent_id": existing.parent_id}
    base_key = category_key_from_label(label)
    key = base_key
    suffix = 2
    while db.scalar(select(Category).where(Category.key == key)):
        key = f"{base_key[:55]}_{suffix}"
        suffix += 1
    category = Category(key=key, label=label, parent_id=payload.parent_id)
    db.add(category)
    db.flush()
    operation_id = journal_mutation(db, kind="create", entity_type="category", actor=actor_for_session(session), description=f'Created category "{category.label}"', changes=[MutationChange(category.id, None, full_values(category))])
    record_audit_event(db, "category_create", "local-user", "category", str(category.id), {"label": label, "key": key})
    db.commit()
    return {"id": category.id, "key": category.key, "label": category.label, "parent_id": category.parent_id, "operation_id": operation_id}


@app.post("/api/categories/cleanup-duplicates")
def cleanup_categories_from_import_labels(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    return cleanup_duplicate_categories(db)


@app.patch("/api/categories/{category_id}")
def update_category(category_id: int, payload: CategoryUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Category label is required")
    if payload.parent_id == category_id:
        raise HTTPException(status_code=400, detail="A category cannot be its own parent")
    if payload.parent_id is not None and not db.get(Category, payload.parent_id):
        raise HTTPException(status_code=400, detail="Parent category not found")
    before = changed_values(category, ["label", "parent_id"])
    category.label = label
    category.parent_id = payload.parent_id
    operation_id = journal_mutation(db, kind="update", entity_type="category", actor=actor_for_session(session), description=f'Updated category "{label}"', changes=[MutationChange(category.id, before, changed_values(category, ["label", "parent_id"]))])
    record_audit_event(db, "category_update", "local-user", "category", str(category.id), {"label": label})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.post("/api/import-presets")
def create_import_preset(payload: ImportPresetCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    preset = ImportPreset(**payload.model_dump())
    db.add(preset)
    db.flush()
    operation_id = journal_mutation(db, kind="create", entity_type="import_preset", actor=actor_for_session(session), description=f'Created import preset "{preset.name}"', changes=[MutationChange(preset.id, None, full_values(preset))])
    record_audit_event(db, "preset_create", "local-user", "import_preset", str(preset.id), payload.model_dump())
    db.commit()
    return {"id": preset.id, "operation_id": operation_id}


@app.get("/api/accounts/{account_id}/import-presets")
def list_import_presets(account_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    presets = db.scalars(select(ImportPreset).where(ImportPreset.account_id == account_id).order_by(ImportPreset.name.asc())).all()
    return [{"id": preset.id, "name": preset.name, "preset_type": preset.preset_type, "header_signature": preset.header_signature} for preset in presets]


@app.post("/api/imports/analyze")
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
        return {
            "preset_type": None,
            "suggested_account_id": None,
            "replacement_candidate_id": None,
            "match_confidence": 0,
            "reason": "Choose the date, description, and amount columns once. This browser will remember the mapping for matching headers.",
            "proposed_account": None,
            "warnings": [],
            "headers": headers,
            "sample_rows": samples,
        }
    return {
        "preset_type": suggestion.preset_type,
        "suggested_account_id": suggestion.suggested_account_id,
        "replacement_candidate_id": suggestion.replacement_candidate_id,
        "match_confidence": suggestion.match_confidence,
        "reason": suggestion.reason,
        "proposed_account": suggestion.proposed_account,
        "warnings": suggestion.warnings,
    }


@app.post("/api/imports/preview")
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
            row = statement_preview_row(pdf_preview, account)
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


@app.post("/api/imports/commit")
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



@app.post("/api/imports/categorized-history")
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"needs_review": False, **result}


@app.post("/api/imports/categorized-history/reviewed")
async def imports_reviewed_categorized_history(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    payload = await request.json()
    try:
        result = commit_reviewed_categorized_history(db, payload.get("filename") or "categorized-history", payload.get("rows") or [], actor=actor_for_session(session), sign_convention=payload.get("sign_convention") or "charges_positive")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return result


@app.post("/api/imports/stage")
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


@app.get("/api/import-sign-profiles")
def list_import_sign_profiles(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    profiles = db.scalars(select(ImportSignProfile).order_by(ImportSignProfile.account_id, ImportSignProfile.preset_type, ImportSignProfile.id)).all()
    return [profile_payload(profile) for profile in profiles]


@app.get("/api/settings/import-metadata")
def list_import_settings_metadata(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    accounts = {row.id: row.display_name for row in db.scalars(select(Account)).all()}
    institutions = {row.id: row.name for row in db.scalars(select(Institution)).all()}
    return {
        "sign_profiles": [
            {**profile_payload(profile), "account": accounts.get(profile.account_id, f"Account {profile.account_id}")}
            for profile in db.scalars(select(ImportSignProfile).order_by(ImportSignProfile.account_id, ImportSignProfile.preset_type)).all()
        ],
        "csv_mappings": [
            {"id": preset.id, "account_id": preset.account_id, "account": accounts.get(preset.account_id, f"Account {preset.account_id}"), "name": preset.name, "preset_type": preset.preset_type}
            for preset in db.scalars(select(ImportPreset).order_by(ImportPreset.account_id, ImportPreset.name)).all()
        ],
        "pdf_patterns": [
            {"id": pattern.id, "institution_id": pattern.institution_id, "institution": institutions.get(pattern.institution_id, f"Institution {pattern.institution_id}"), "balance_label": pattern.balance_label, "date_label": pattern.date_label}
            for pattern in db.scalars(select(StatementPdfPattern).order_by(StatementPdfPattern.institution_id)).all()
        ],
    }


@app.put("/api/import-sign-profiles/{account_id}")
async def put_import_sign_profile(account_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    payload = await request.json()
    preset_type = str(payload.get("preset_type") or "").strip() or None
    sample_note = str(payload.get("sample_note") or "").strip() or None
    try:
        profile, operation_id = save_sign_profile(
            db,
            account=account,
            preset_type=preset_type,
            sign_convention=str(payload.get("sign_convention") or ""),
            actor=actor_for_session(session),
            sample_note=sample_note,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return {**profile_payload(profile), "operation_id": operation_id}


@app.get("/api/maintenance/categorized-history-signs")
def categorized_history_sign_cleanup_preview(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return preview_categorized_history_sign_cleanup(db)


@app.post("/api/maintenance/categorized-history-signs")
async def categorized_history_sign_cleanup_apply(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    payload = await request.json()
    confirm_text = str(payload.get("confirm_text") or "")
    if confirm_text.strip().upper() != "NORMALIZE":
        raise HTTPException(status_code=400, detail='Type "NORMALIZE" to apply the categorized-history cleanup')
    preview = preview_categorized_history_sign_cleanup(db)
    backup_name = None
    if preview["candidate_transactions"] > 0:
        backup_name = f"pre-history-sign-cleanup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.sqlite3"
        try:
            create_backup(resolve_backup_destination(backup_name))
        except BackupError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        result = apply_categorized_history_sign_cleanup(db, actor=actor_for_session(session), confirm_text=confirm_text)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return {**result, "backup_name": backup_name}


@app.get("/api/imports/inbox")
def get_import_inbox(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return {"folder": str(inbox_directory()), "pending": pending_import_batches(db)}


@app.post("/api/imports/inbox/scan")
def scan_inbox(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    result = scan_import_inbox(db)
    record_audit_event(db, "import_inbox_scan", actor_for_session(session), "import_inbox", result["folder"], {"files_found": result["files_found"], "staged": len(result["staged"]), "needs_account": len(result["needs_account"]), "errors": len(result["errors"])})
    db.commit()
    return {**result, "pending": pending_import_batches(db)}


@app.post("/api/imports/{batch_id}/confirm")
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


@app.patch("/api/imports/{batch_id}/statement-preview")
def edit_statement_balance_preview(batch_id: int, payload: StatementBalancePreviewUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    try:
        result = update_statement_preview(
            db,
            batch,
            statement_date=payload.statement_date,
            balance_cents=payload.balance_cents,
            candidate_index=payload.candidate_index,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return {"preview": result, "pending": pending_import_batches(db)}


@app.post("/api/imports/{batch_id}/discard")
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

@app.get("/api/imports/{batch_id}/report")
def import_report(batch_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    from .models import ImportBatch

    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return {"id": batch.id, "filename": batch.filename, "status": batch.status, "imported_rows": batch.imported_rows, "skipped_duplicates": batch.skipped_duplicates, "warnings": json.loads(batch.warnings_json)}


@app.post("/api/transactions/manual")
def create_manual_transaction(payload: ManualTransactionCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, payload.account_id)
    if not account or account.status != "active" or account.last_four == UNASSIGNED_ACCOUNT_MARKER:
        raise HTTPException(status_code=400, detail="Choose an active account")
    if payload.amount_cents == 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero")
    category = db.get(Category, payload.category_id) if payload.category_id is not None else None
    if payload.category_id is not None and not category:
        raise HTTPException(status_code=400, detail="Category not found")
    if account.account_type in {"brokerage", "retirement"}:
        transaction_type = TransactionType.INVESTMENT_FLOW.value
        category_id = None
    elif payload.amount_cents < 0:
        transaction_type = TransactionType.EXPENSE.value
        if category is None:
            raise HTTPException(status_code=400, detail="Choose a category for money out")
        category_id = category.id
    else:
        transaction_type = TransactionType.REFUND.value if account.account_type == "credit_card" else TransactionType.INCOME.value
        category_id = category.id if category else None
    description = " ".join(payload.description.split())
    if not description:
        raise HTTPException(status_code=400, detail="Description is required")
    transaction = Transaction(
        account_id=account.id,
        transaction_date=payload.transaction_date,
        amount_cents=payload.amount_cents,
        raw_description=description,
        normalized_payee=description[:255],
        labels=normalize_transaction_labels(",".join(payload.labels)),
        transaction_type=transaction_type,
        category_id=category_id,
        review_status=ReviewStatus.CONFIRMED.value,
        source_hash=f"manual:{uuid4().hex}",
    )
    db.add(transaction)
    db.flush()
    operation_id = journal_mutation(
        db,
        kind="create",
        entity_type="transaction",
        actor=actor_for_session(session),
        description=f'Added manual transaction "{description}"',
        changes=[MutationChange(transaction.id, None, full_values(transaction))],
    )
    record_audit_event(db, "transaction_manual_create", actor_for_session(session), "transaction", str(transaction.id), {"account_id": account.id, "amount_cents": transaction.amount_cents, "operation_id": operation_id})
    db.commit()
    return {"ok": True, "transaction_id": transaction.id, "operation_id": operation_id}


@app.get("/api/transactions")
def list_transactions(
    account_id: int | None = None,
    filters: TransactionFilter = Depends(transaction_filter_dependency),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    if account_id is not None and account_id not in filters.accounts:
        filters = filters.model_copy(update={"accounts": [*filters.accounts, account_id]})
    query = select(Transaction).where(*transaction_filter_conditions(filters)).order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
    rows = db.scalars(query).all()
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    allocations_by_transaction: dict[int, list[ExpenseAllocation]] = {}
    for allocation in db.scalars(select(ExpenseAllocation).order_by(ExpenseAllocation.allocation_date, ExpenseAllocation.id)).all():
        allocations_by_transaction.setdefault(allocation.transaction_id, []).append(allocation)
    splits_by_transaction: dict[int, list[TransactionSplit]] = {}
    for split in db.scalars(select(TransactionSplit).order_by(TransactionSplit.id)).all():
        splits_by_transaction.setdefault(split.transaction_id, []).append(split)
    confirmed_refund_links = db.scalars(select(RefundLink).where(RefundLink.confirmed.is_(True))).all()
    refund_transaction_ids = {link.refund_transaction_id for link in confirmed_refund_links}
    refund_amounts = {
        row.id: row.amount_cents
        for row in db.scalars(select(Transaction).where(Transaction.id.in_(refund_transaction_ids))).all()
    } if refund_transaction_ids else {}
    refund_total_by_expense: dict[int, int] = {}
    refund_count_by_expense: dict[int, int] = {}
    refund_expense_by_refund: dict[int, int] = {}
    for link in confirmed_refund_links:
        refund_total_by_expense[link.expense_transaction_id] = refund_total_by_expense.get(link.expense_transaction_id, 0) + refund_amounts.get(link.refund_transaction_id, 0)
        refund_count_by_expense[link.expense_transaction_id] = refund_count_by_expense.get(link.expense_transaction_id, 0) + 1
        refund_expense_by_refund[link.refund_transaction_id] = link.expense_transaction_id
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
            "labels": transaction_labels(row.labels),
            "duplicate_of_transaction_id": row.duplicate_of_transaction_id,
            "monthly_allocation_count": len(allocations_by_transaction.get(row.id, [])),
            "split_count": len(splits_by_transaction.get(row.id, [])),
            "refund_total_cents": refund_total_by_expense.get(row.id, 0),
            "refund_link_count": refund_count_by_expense.get(row.id, 0),
            "refund_expense_id": refund_expense_by_refund.get(row.id),
            "reporting_category_ids": (
                [allocation.category_id for allocation in allocations_by_transaction[row.id]]
                if row.id in allocations_by_transaction
                else [split.category_id for split in splits_by_transaction[row.id]]
                if row.id in splits_by_transaction
                else [row.category_id]
            ),
            "reporting_dates": (
                [allocation.allocation_date.isoformat() for allocation in allocations_by_transaction[row.id]]
                if row.id in allocations_by_transaction
                else [row.transaction_date.isoformat()]
            ),
        }
        for row in rows
    ]


@app.get("/api/transactions/ids")
def list_transaction_ids(
    account_id: int | None = None,
    filters: TransactionFilter = Depends(transaction_filter_dependency),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    if account_id is not None and account_id not in filters.accounts:
        filters = filters.model_copy(update={"accounts": [*filters.accounts, account_id]})
    return list(db.scalars(select(Transaction.id).where(*transaction_filter_conditions(filters)).order_by(Transaction.id)).all())


@app.patch("/api/transactions/bulk-update")
def bulk_update_transactions(payload: BulkTransactionUpdateRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transactions = db.scalars(live_transaction_select(Transaction.id.in_(payload.ids))).all()
    if len(transactions) != len(set(payload.ids)):
        raise HTTPException(status_code=404, detail="One or more transactions were not found")

    field = payload.field.value
    value = payload.value
    affected_accounts = 0
    journal_entity_type = "transaction"
    journal_changes: list[MutationChange] = []
    if field == "institution":
        name = str(value or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Institution name is required")
        institution = upsert_institution(db, name)
        account_ids = {transaction.account_id for transaction in transactions}
        accounts = db.scalars(select(Account).where(Account.id.in_(account_ids))).all()
        for account in accounts:
            before = changed_values(account, ["institution_id"])
            account.institution_id = institution.id if institution else None
            journal_changes.append(MutationChange(account.id, before, changed_values(account, ["institution_id"])))
        affected_accounts = len(accounts)
        journal_entity_type = "account"
    elif field == "account":
        try:
            account_id = int(value)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="Choose a valid account") from error
        target_account = db.get(Account, account_id)
        if not target_account or target_account.last_four == UNASSIGNED_ACCOUNT_MARKER:
            raise HTTPException(status_code=400, detail="Account not found")
        for transaction in transactions:
            before = changed_values(transaction, ["account_id"])
            transaction.account_id = account_id
            journal_changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["account_id"])))
    elif field == "description":
        description = str(value or "").strip()
        if not description:
            raise HTTPException(status_code=400, detail="Description is required")
        for transaction in transactions:
            before = changed_values(transaction, ["raw_description"])
            transaction.raw_description = description
            journal_changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["raw_description"])))
    elif field == "details":
        details = str(value or "").strip() or None
        for transaction in transactions:
            before = changed_values(transaction, ["user_note"])
            transaction.user_note = details
            journal_changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["user_note"])))
    elif field == "type":
        try:
            transaction_type = TransactionType(str(value))
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Choose a valid transaction type") from error
        for transaction in transactions:
            fields = ["transaction_type", "category_id"] if transaction_type.value in CATEGORYLESS_TRANSACTION_TYPES else ["transaction_type"]
            before = changed_values(transaction, fields)
            transaction.transaction_type = transaction_type.value
            if transaction_type.value in CATEGORYLESS_TRANSACTION_TYPES:
                transaction.category_id = None
            journal_changes.append(MutationChange(transaction.id, before, changed_values(transaction, fields)))
            append_payment_reclassification_dismissal(db, transaction, {"transaction_type": transaction_type.value}, journal_changes)
    elif field == "category":
        try:
            category_id = int(value)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="Choose a valid category") from error
        if not db.get(Category, category_id):
            raise HTTPException(status_code=400, detail="Category not found")
        for transaction in transactions:
            before = changed_values(transaction, ["category_id"])
            transaction.category_id = category_id
            journal_changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["category_id"])))
    elif field == "date":
        try:
            transaction_date = date.fromisoformat(str(value))
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Choose a valid transaction date") from error
        for transaction in transactions:
            before = changed_values(transaction, ["transaction_date"])
            transaction.transaction_date = transaction_date
            journal_changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["transaction_date"])))
    elif field == "labels":
        labels = normalize_transaction_labels(value)
        for transaction in transactions:
            before = changed_values(transaction, ["labels"])
            transaction.labels = labels
            journal_changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["labels"])))

    actor = actor_for_session(session)
    operation_id = journal_mutation(
        db,
        kind="bulk_update",
        entity_type=journal_entity_type,
        actor=actor,
        description=f"Changed {field} on {len(journal_changes)} {journal_entity_type}{'' if len(journal_changes) == 1 else 's'}",
        changes=journal_changes,
    )
    record_audit_event(db, "transaction_bulk_update", actor, "transactions", f"bulk:{len(transactions)}", {"field": field, "value": value, "count": len(transactions), "affected_accounts": affected_accounts, "transaction_ids": [transaction.id for transaction in transactions[:50]], "operation_id": operation_id})
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail="This change would create duplicate transactions in the target account") from error
    return {"ok": True, "updated": len(transactions), "affected_accounts": affected_accounts, "operation_id": operation_id}


@app.delete("/api/transactions/bulk-delete")
def bulk_delete_transactions(payload: BulkDeleteRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    transactions = db.scalars(live_transaction_select(Transaction.id.in_(payload.ids))).all()
    if len(transactions) != len(set(payload.ids)):
        raise HTTPException(status_code=404, detail="One or more transactions were not found")
    operation_id = _soft_delete_transactions(db, transactions, actor_for_session(session))
    db.commit()
    return {"ok": True, "deleted": len(transactions), "operation_id": operation_id}


@app.post("/api/transactions/{transaction_id}/restore")
def restore_transaction(transaction_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = db.get(Transaction, transaction_id)
    if not transaction or transaction.deleted_at is None:
        raise HTTPException(status_code=404, detail="Deleted transaction not found")
    actor = actor_for_session(session)
    operation_id = _restore_transactions(db, [transaction], actor)
    record_audit_event(db, "transaction_restore", actor, "transaction", str(transaction.id), {"operation_id": operation_id})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.post("/api/transactions/bulk-restore")
def restore_transactions(payload: BulkIdsRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transactions = db.scalars(select(Transaction).where(Transaction.id.in_(payload.ids), Transaction.deleted_at.is_not(None))).all()
    if len(transactions) != len(set(payload.ids)):
        raise HTTPException(status_code=404, detail="One or more deleted transactions were not found")
    actor = actor_for_session(session)
    operation_id = _restore_transactions(db, transactions, actor)
    db.commit()
    return {"ok": True, "restored": len(transactions), "operation_id": operation_id}


@app.delete("/api/transactions/bulk-permanent-delete")
def permanently_delete_transactions(payload: BulkDeleteRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    transactions = db.scalars(select(Transaction).where(Transaction.id.in_(payload.ids), Transaction.deleted_at.is_not(None))).all()
    if len(transactions) != len(set(payload.ids)):
        raise HTTPException(status_code=404, detail="One or more deleted transactions were not found")
    for transaction in transactions:
        _delete_transaction_row(db, transaction)
    db.commit()
    return {"ok": True, "deleted": len(transactions)}


@app.delete("/api/transactions/{transaction_id}/permanent")
def permanently_delete_transaction(transaction_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    transaction = db.get(Transaction, transaction_id)
    if not transaction or transaction.deleted_at is None:
        raise HTTPException(status_code=404, detail="Deleted transaction not found")
    _delete_transaction_row(db, transaction)
    db.commit()
    return {"ok": True}


@app.patch("/api/transactions/{transaction_id}")
def update_transaction(transaction_id: int, payload: TransactionReviewUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = get_live_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    updates = normalize_transaction_updates(payload.model_dump(exclude_unset=True))
    if "account_id" in updates:
        account = db.get(Account, updates["account_id"])
        if not account or account.last_four == UNASSIGNED_ACCOUNT_MARKER:
            raise HTTPException(status_code=400, detail="Choose a valid account")
    if "category_id" in updates and updates["category_id"] is not None and not db.get(Category, updates["category_id"]):
        raise HTTPException(status_code=400, detail="Category not found")
    next_review_status = updates.get("review_status", transaction.review_status)
    next_account = db.get(Account, updates.get("account_id", transaction.account_id))
    if next_review_status == "confirmed" and (not next_account or next_account.last_four == UNASSIGNED_ACCOUNT_MARKER):
        raise HTTPException(status_code=400, detail="Choose an account before confirming this transaction")
    validate_transaction_confirmation(transaction, updates)
    before = changed_values(transaction, updates.keys())
    for key, value in updates.items():
        setattr(transaction, key, value)
    actor = actor_for_session(session)
    changes = [MutationChange(transaction.id, before, changed_values(transaction, updates.keys()))]
    append_payment_reclassification_dismissal(db, transaction, updates, changes)
    operation_id = journal_mutation(
        db,
        kind="update",
        entity_type="transaction",
        actor=actor,
        description=f'Updated transaction "{transaction.raw_description}"',
        changes=changes,
    )
    record_audit_event(db, "transaction_update", actor, "transaction", str(transaction.id), {**updates, "operation_id": operation_id})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.post("/api/transactions/{transaction_id}/void")
def void_transaction(transaction_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = get_live_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    before = changed_values(transaction, ["status"])
    transaction.status = "voided"
    actor = actor_for_session(session)
    operation_id = journal_mutation(
        db,
        kind="update",
        entity_type="transaction",
        actor=actor,
        description=f'Voided transaction "{transaction.raw_description}"',
        changes=[MutationChange(transaction.id, before, changed_values(transaction, ["status"]))],
    )
    record_audit_event(db, "transaction_void", actor, "transaction", str(transaction.id), {"status": "voided", "operation_id": operation_id})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.delete("/api/transactions/{transaction_id}")
def delete_transaction(transaction_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    transaction = get_live_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    operation_id = _soft_delete_transaction(db, transaction, actor_for_session(session))
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.post("/api/transactions/{transaction_id}/splits")
def set_splits(transaction_id: int, payload: SplitSetRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = get_live_transaction(db, transaction_id)
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
    existing_splits = db.scalars(select(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id)).all()
    before_by_id = {split.id: full_values(split) for split in existing_splits}
    db.execute(delete(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id))
    for split in payload.splits:
        db.add(TransactionSplit(transaction_id=transaction_id, category_id=split.category_id, amount_cents=split.amount_cents, note=split.note))
    db.flush()
    new_splits = db.scalars(select(TransactionSplit).where(TransactionSplit.transaction_id == transaction_id)).all()
    after_by_id = {split.id: full_values(split) for split in new_splits}
    operation_id = journal_mutation(
        db,
        kind="replace",
        entity_type="transaction_split",
        actor=actor_for_session(session),
        description=f'Replaced category splits for "{transaction.raw_description}"',
        changes=[MutationChange(split_id, before_by_id.get(split_id), after_by_id.get(split_id)) for split_id in sorted(set(before_by_id) | set(after_by_id))],
    )
    record_audit_event(db, "transaction_split", "local-user", "transaction", str(transaction.id), {"split_count": len(payload.splits)})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


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
    target_category_id = replacement.id if replacement else None
    changes: list[MutationChange] = [MutationChange(category.id, full_values(category), None, entity_type="category")]
    reference_groups = [
        ("transaction", db.scalars(select(Transaction).where(Transaction.category_id == category_id)).all(), "category_id"),
        ("transaction_split", db.scalars(select(TransactionSplit).where(TransactionSplit.category_id == category_id)).all(), "category_id"),
        ("expense_allocation", db.scalars(select(ExpenseAllocation).where(ExpenseAllocation.category_id == category_id)).all(), "category_id"),
        ("category_rule", db.scalars(select(CategoryRule).where(CategoryRule.category_id == category_id)).all(), "category_id"),
        ("category", db.scalars(select(Category).where(Category.parent_id == category_id)).all(), "parent_id"),
    ]
    for entity_type, rows, field in reference_groups:
        changes.extend(MutationChange(row.id, changed_values(row, [field]), {"id": row.id, field: target_category_id}, entity_type=entity_type) for row in rows)
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
    operation_id = journal_mutation(db, kind="delete", entity_type="mixed" if len(changes) > 1 else "category", actor=actor_for_session(session), description=f'Deleted category "{category.label}"', changes=changes)
    db.commit()
    return {"ok": True, "reassigned": sum(reference_counts.values()), "operation_id": operation_id}


@app.get("/api/transactions/{transaction_id}/splits")
def get_splits(transaction_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    transaction = get_live_transaction(db, transaction_id)
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
    transaction = get_live_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if transaction.status != "active" or transaction.transaction_type != "expense":
        raise HTTPException(status_code=400, detail="Only active expense transactions can be spread across months")
    if not db.get(Category, payload.category_id):
        raise HTTPException(status_code=400, detail="Category not found")
    if db.scalar(select(TransactionSplit.id).where(TransactionSplit.transaction_id == transaction_id)):
        raise HTTPException(status_code=400, detail="A split transaction cannot also be spread across months")
    existing_allocations = db.scalars(select(ExpenseAllocation).where(ExpenseAllocation.transaction_id == transaction_id)).all()
    before_by_id = {allocation.id: full_values(allocation) for allocation in existing_allocations}
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
    db.flush()
    new_allocations = db.scalars(select(ExpenseAllocation).where(ExpenseAllocation.transaction_id == transaction_id)).all()
    after_by_id = {allocation.id: full_values(allocation) for allocation in new_allocations}
    operation_id = journal_mutation(db, kind="replace", entity_type="expense_allocation", actor=actor_for_session(session), description=f'Changed monthly allocation for "{transaction.raw_description}"', changes=[MutationChange(allocation_id, before_by_id.get(allocation_id), after_by_id.get(allocation_id)) for allocation_id in sorted(set(before_by_id) | set(after_by_id))])
    record_audit_event(db, "transaction_monthly_allocation", "local-user", "transaction", str(transaction.id), {"months": payload.months, "category_id": payload.category_id, "allocation_start": payload.allocation_start.isoformat()})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.delete("/api/transactions/{transaction_id}/monthly-allocation")
def delete_monthly_allocation(transaction_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transaction = get_live_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    allocations = db.scalars(select(ExpenseAllocation).where(ExpenseAllocation.transaction_id == transaction_id)).all()
    if not allocations:
        raise HTTPException(status_code=404, detail="Monthly allocation not found")
    changes = [MutationChange(allocation.id, full_values(allocation), None) for allocation in allocations]
    db.execute(delete(ExpenseAllocation).where(ExpenseAllocation.transaction_id == transaction_id))
    operation_id = journal_mutation(db, kind="delete", entity_type="expense_allocation", actor=actor_for_session(session), description=f'Removed monthly allocation from "{transaction.raw_description}"', changes=changes)
    record_audit_event(db, "transaction_monthly_allocation_delete", "local-user", "transaction", str(transaction.id), {})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.get("/api/review")
def review_inbox(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    rows = db.scalars(
        live_transaction_select(
            or_(
                Transaction.review_status.in_(["needs_review", "suggested", "possible_duplicate"]),
                and_(Transaction.transaction_type == TransactionType.REFUND.value, Transaction.category_id.is_(None)),
            ),
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


@app.get("/api/duplicates/pending")
def list_pending_duplicates(limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0), tier: Literal["exact", "cross_source", "probable", "mirrored", "import"] | None = None, account_id: int | None = Query(default=None, ge=1), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return pending_duplicate_pairs(db, limit=limit, offset=offset, tier_filter=tier, account_id=account_id)


@app.get("/api/duplicates/summary")
def get_duplicate_queue_summary(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return duplicate_queue_summary(db)


@app.get("/api/duplicates/bulk-preview")
def get_duplicate_bulk_preview(strategy: Literal["keep_existing", "use_new_import"], session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return preview_safe_duplicate_resolution(db, strategy=strategy)


@app.post("/api/duplicates/resolve-safe")
def resolve_safe_duplicates(payload: BulkDuplicateResolutionRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        result = resolve_safe_duplicate_reimports(db, strategy=payload.strategy, preview_token=payload.preview_token, actor=actor_for_session(session))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@app.get("/api/duplicates/historical-refunds-preview")
def get_historical_refund_bulk_preview(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return preview_historical_refund_links(db)


@app.post("/api/duplicates/link-historical-refunds")
def link_historical_refunds(payload: HistoricalRefundBulkRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        result = link_historical_refund_pairs(db, preview_token=payload.preview_token, actor=actor_for_session(session))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@app.post("/api/duplicates/selection-preview")
def get_duplicate_selection_preview(payload: DuplicateSelectionPreviewRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return preview_duplicate_selection(db, transaction_ids=payload.transaction_ids, action=payload.action)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/duplicates/resolve-selection")
def resolve_selected_duplicates(payload: DuplicateSelectionResolutionRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        result = resolve_duplicate_selection(
            db,
            transaction_ids=payload.transaction_ids,
            action=payload.action,
            preview_token=payload.preview_token,
            actor=actor_for_session(session),
        )
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@app.get("/api/duplicates/scan/results")
def ledger_duplicate_scan_results(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return pending_duplicate_pairs(db, limit=25)


@app.post("/api/duplicates/scan")
def scan_duplicates(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    result = scan_ledger_duplicates(db, actor=actor_for_session(session))
    db.commit()
    return {**result, "queue": duplicate_queue_summary(db)}


@app.post("/api/duplicates/resolve-exact")
def resolve_exact_duplicates(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    result = resolve_all_exact_duplicates(db, actor=actor_for_session(session))
    db.commit()
    return result


@app.post("/api/duplicates/{transaction_id}/resolve")
def resolve_pending_duplicate(transaction_id: int, payload: DuplicateResolutionRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        result = resolve_duplicate(db, transaction_id=transaction_id, action=payload.action, actor=actor_for_session(session))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return result


@app.post("/api/rules")
def create_rule(payload: RuleCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    values = payload.model_dump()
    values["category_id"] = normalized_rule_category(db, payload.category_id, payload.suggested_transaction_type)
    rule = CategoryRule(**values)
    db.add(rule)
    db.flush()
    operation_id = journal_mutation(db, kind="create", entity_type="category_rule", actor=actor_for_session(session), description=f'Created rule "{rule.match_text}"', changes=[MutationChange(rule.id, None, full_values(rule))])
    record_audit_event(db, "rule_create", "local-user", "category_rule", str(rule.id), values)
    db.commit()
    return {"id": rule.id, "operation_id": operation_id}


@app.post("/api/rules/{rule_id}/apply")
def apply_rule(rule_id: int, payload: RuleApplyRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    if payload.scope not in {"unreviewed", "all"}:
        raise HTTPException(status_code=400, detail="Rule scope must be unreviewed or all")
    rule = db.get(CategoryRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    query = live_transaction_select()
    if payload.scope == "unreviewed":
        query = query.where(Transaction.review_status.in_(["needs_review", "suggested", "possible_duplicate"]))

    matched = 0
    updated = 0
    changes: list[MutationChange] = []
    for transaction in db.scalars(query).all():
        if not rule_matches_transaction(rule, transaction):
            continue
        matched += 1
        before = changed_values(transaction, ["category_id", "transaction_type", "review_status"])
        if apply_rule_to_transaction(rule, transaction):
            updated += 1
            changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["category_id", "transaction_type", "review_status"])))
            append_payment_reclassification_dismissal(db, transaction, {"transaction_type": rule.suggested_transaction_type}, changes)

    operation_id = journal_mutation(db, kind="bulk_update", entity_type="transaction", actor=actor_for_session(session), description=f'Applied rule "{rule.match_text}" to {updated} transactions', changes=changes) if changes else None

    record_audit_event(db, "rule_apply", "local-user", "category_rule", str(rule.id), {"scope": payload.scope, "matched": matched, "updated": updated})
    db.commit()
    return {"matched": matched, "updated": updated, "operation_id": operation_id}


@app.post("/api/rules/{rule_id}/apply-to/{transaction_id}")
def apply_rule_to_row(rule_id: int, transaction_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    rule = db.get(CategoryRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    transaction = get_live_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if not rule_matches_transaction(rule, transaction):
        raise HTTPException(status_code=400, detail="This rule does not match the selected transaction")
    fields = ["category_id", "transaction_type", "review_status"]
    before = changed_values(transaction, fields)
    changed = apply_rule_to_transaction(rule, transaction)
    changes: list[MutationChange] = []
    if changed:
        changes.append(MutationChange(transaction.id, before, changed_values(transaction, fields), entity_type="transaction"))
        append_payment_reclassification_dismissal(db, transaction, {"transaction_type": rule.suggested_transaction_type}, changes)
    actor = actor_for_session(session)
    operation_id = journal_mutation(
        db,
        kind="update",
        entity_type="mixed" if len({change.entity_type for change in changes}) > 1 else "transaction",
        actor=actor,
        description=f'Applied rule "{rule.match_text}" to one transaction',
        changes=changes,
    ) if changes else None
    record_audit_event(db, "rule_apply_to_transaction", actor, "category_rule", str(rule.id), {"transaction_id": transaction.id, "updated": changed, "operation_id": operation_id})
    db.commit()
    return {"matched": 1, "updated": 1 if changed else 0, "transaction_id": transaction.id, "operation_id": operation_id}


@app.get("/api/rules/{rule_id}/preview")
def preview_rule(rule_id: int, scope: str = "unreviewed", session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    if scope not in {"unreviewed", "all"}:
        raise HTTPException(status_code=400, detail="Rule scope must be unreviewed or all")
    rule = db.get(CategoryRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    query = live_transaction_select()
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
    next_type = updates.get("suggested_transaction_type", rule.suggested_transaction_type)
    next_category_id = updates.get("category_id", rule.category_id)
    updates["category_id"] = normalized_rule_category(db, next_category_id, next_type)
    if "match_text" in updates and not str(updates["match_text"]).strip():
        raise HTTPException(status_code=400, detail="Match text is required")
    before = changed_values(rule, updates.keys())
    for key, value in updates.items():
        setattr(rule, key, value)
    operation_id = journal_mutation(db, kind="update", entity_type="category_rule", actor=actor_for_session(session), description=f'Updated rule "{rule.match_text}"', changes=[MutationChange(rule.id, before, changed_values(rule, updates.keys()))])
    record_audit_event(db, "rule_update", "local-user", "category_rule", str(rule.id), updates)
    db.commit()
    return {**payload_from_rule(rule), "operation_id": operation_id}


@app.delete("/api/rules/{rule_id}")
def delete_rule(rule_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    rule = db.get(CategoryRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    operation_id = journal_mutation(db, kind="delete", entity_type="category_rule", actor=actor_for_session(session), description=f'Deleted rule "{rule.match_text}"', changes=[MutationChange(rule.id, full_values(rule), None)])
    record_audit_event(db, "rule_delete", "local-user", "category_rule", str(rule.id), {"match_text": rule.match_text})
    db.delete(rule)
    db.commit()
    return {"ok": True, "operation_id": operation_id}


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
    operation_id = journal_mutation(db, kind="create", entity_type="transfer_link", actor=actor_for_session(session), description="Created transfer link", changes=[MutationChange(link.id, None, full_values(link))])
    record_audit_event(db, "transfer_link_create", "local-user", "transfer_link", str(link.id), payload.model_dump())
    db.commit()
    return {"id": link.id, "operation_id": operation_id}


@app.get("/api/transfers/unconfirmed")
def get_unconfirmed_transfers(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_unconfirmed_transfers(db)


@app.get("/api/transfers/payments")
def get_payment_verification(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_payment_verification(db)


@app.post("/api/transfers/payments/{transaction_id}/dismiss")
def dismiss_payment_warning(transaction_id: int, payload: PaymentVerificationDismissRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return dismiss_payment_verification(db, transaction_id=transaction_id, reason=payload.reason, actor=actor_for_session(session))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/transfers/payments/{transaction_id}/external")
def settle_external_payment(transaction_id: int, payload: ExternalPaymentRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return settle_payment_from_external(
            db,
            transaction_id=transaction_id,
            external_account_id=payload.external_account_id,
            external_account_name=payload.external_account_name,
            actor=actor_for_session(session),
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


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


@app.get("/api/refunds/suggestions")
def get_refund_suggestions(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_refund_suggestion_groups(db)


@app.get("/api/refunds/expenses/{expense_transaction_id}")
def get_expense_refunds(expense_transaction_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_refund_links(db, confirmed=True, expense_transaction_id=expense_transaction_id)


@app.get("/api/refunds/candidates")
def get_refund_candidates(expense_transaction_id: int, search: str | None = None, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    try:
        return list_manual_refund_candidates(db, expense_transaction_id=expense_transaction_id, search=search)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/refunds/detect")
def detect_refunds(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    return create_refund_suggestions(db, actor=actor_for_session(session))


@app.post("/api/refunds/confirm-selection")
def confirm_refund_selection(payload: RefundSelectionRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    selections = [(row.refund_transaction_id, row.expense_transaction_id) for row in payload.selections]
    try:
        return confirm_refund_selections(db, selections=selections, allow_over_refund=payload.allow_over_refund, actor=actor_for_session(session))
    except OverRefundError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/refunds/reject-candidates")
def reject_refund_candidate_selection(payload: RefundSelectionRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return reject_refund_candidates(db, selections=[(row.refund_transaction_id, row.expense_transaction_id) for row in payload.selections], actor=actor_for_session(session))
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/refunds/no-expense")
def settle_refunds_without_expense(payload: RefundNoExpenseRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return resolve_refunds_without_expense(db, refund_ids=payload.refund_transaction_ids, actor=actor_for_session(session))
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/refund-links")
def create_refund_link(payload: RefundLinkCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return create_manual_refund_link(db, **payload.model_dump(), actor=actor_for_session(session))
    except OverRefundError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/refunds/{link_id}/confirm")
def confirm_refund(link_id: int, payload: RefundConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = db.get(RefundLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Refund candidate not found")
    try:
        return confirm_refund_link(db, link, allow_over_refund=payload.allow_over_refund, actor=actor_for_session(session))
    except OverRefundError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/refunds/{link_id}/reject")
def reject_refund(link_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = db.get(RefundLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Refund candidate not found")
    return reject_refund_link(db, link, actor=actor_for_session(session))


@app.delete("/api/refunds/{link_id}")
def unlink_refund(link_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = db.get(RefundLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Refund link not found")
    return delete_refund_link(db, link, actor=actor_for_session(session))


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


@app.get("/api/snapshots/networth")
def get_net_worth_series(
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    bucket: Literal["day", "week", "month"] = "day",
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    try:
        return net_worth_series(db, from_date=from_date, to_date=to_date, bucket=bucket)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/snapshots/networth/stats")
def get_net_worth_stats(
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    try:
        return net_worth_stats(db, from_date=from_date, to_date=to_date)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/snapshots/networth/contributors")
def get_net_worth_contributors(
    from_date: date = Query(alias="from"),
    to_date: date = Query(alias="to"),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    try:
        return net_worth_contributors(db, from_date=from_date, to_date=to_date)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/snapshots/networth/manual")
def save_manual_net_worth_snapshot(payload: NetWorthSnapshotUpsert, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, payload.account_id)
    if not account or account.status != "active" or account.last_four == UNASSIGNED_ACCOUNT_MARKER:
        raise HTTPException(status_code=400, detail="Choose an active account")
    if account.account_type == "external":
        raise HTTPException(status_code=400, detail="Untracked accounts are excluded from net worth")
    snapshot = db.scalar(select(NetWorthSnapshot).where(NetWorthSnapshot.account_id == payload.account_id, NetWorthSnapshot.snapshot_date == payload.snapshot_date))
    before = full_values(snapshot) if snapshot else None
    snapshot = upsert_net_worth_snapshot(db, account_id=payload.account_id, snapshot_date=payload.snapshot_date, balance_cents=payload.balance_cents, source="manual")
    db.flush()
    operation_id = journal_mutation(
        db,
        kind="update" if before else "create",
        entity_type="net_worth_snapshot",
        actor=actor_for_session(session),
        description=f"Recorded {account.display_name} balance for {payload.snapshot_date.isoformat()}",
        changes=[MutationChange(snapshot.id, before, full_values(snapshot))],
    )
    db.commit()
    return {"ok": True, "snapshot_id": snapshot.id, "operation_id": operation_id}


@app.get("/api/snapshots/networth/manual")
def list_manual_net_worth_snapshots(account_id: int | None = None, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    query = select(NetWorthSnapshot).where(NetWorthSnapshot.source == "manual").order_by(NetWorthSnapshot.snapshot_date.desc(), NetWorthSnapshot.id.desc())
    if account_id is not None:
        query = query.where(NetWorthSnapshot.account_id == account_id)
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    checkpoint_keys = {
        (checkpoint.account_id, checkpoint.statement_date)
        for checkpoint in db.scalars(select(StatementCheckpoint)).all()
    }
    return [
        {
            "id": snapshot.id,
            "account_id": snapshot.account_id,
            "account": accounts[snapshot.account_id].display_name if snapshot.account_id in accounts else "Unknown account",
            "snapshot_date": snapshot.snapshot_date.isoformat(),
            "balance_cents": snapshot.balance_cents,
            "source": snapshot.source,
        }
        for snapshot in db.scalars(query).all()
        if (snapshot.account_id, snapshot.snapshot_date) not in checkpoint_keys
    ]


def _editable_manual_snapshot(db: Session, snapshot_id: int) -> NetWorthSnapshot:
    snapshot = db.get(NetWorthSnapshot, snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail="Net-worth snapshot not found")
    if snapshot.source != "manual":
        raise HTTPException(status_code=400, detail="Imported snapshots cannot be edited")
    checkpoint = db.scalar(select(StatementCheckpoint).where(StatementCheckpoint.account_id == snapshot.account_id, StatementCheckpoint.statement_date == snapshot.snapshot_date))
    if checkpoint:
        raise HTTPException(status_code=400, detail="Statement-backed balances must be changed through reconciliation")
    return snapshot


@app.patch("/api/snapshots/networth/{snapshot_id}")
def update_manual_net_worth_snapshot(snapshot_id: int, payload: NetWorthSnapshotUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    snapshot = _editable_manual_snapshot(db, snapshot_id)
    conflict = db.scalar(select(NetWorthSnapshot).where(NetWorthSnapshot.account_id == snapshot.account_id, NetWorthSnapshot.snapshot_date == payload.snapshot_date, NetWorthSnapshot.id != snapshot.id))
    if conflict:
        raise HTTPException(status_code=409, detail="That account already has a balance on this date")
    before = full_values(snapshot)
    snapshot.snapshot_date = payload.snapshot_date
    snapshot.balance_cents = payload.balance_cents
    db.flush()
    operation_id = journal_mutation(db, kind="update", entity_type="net_worth_snapshot", actor=actor_for_session(session), description=f"Updated manual balance for {payload.snapshot_date.isoformat()}", changes=[MutationChange(snapshot.id, before, full_values(snapshot))])
    record_audit_event(db, "net_worth_snapshot_update", actor_for_session(session), "net_worth_snapshot", str(snapshot.id), {"operation_id": operation_id})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.delete("/api/snapshots/networth/{snapshot_id}")
def delete_manual_net_worth_snapshot(snapshot_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    snapshot = _editable_manual_snapshot(db, snapshot_id)
    before = full_values(snapshot)
    operation_id = journal_mutation(db, kind="delete", entity_type="net_worth_snapshot", actor=actor_for_session(session), description=f"Deleted manual balance for {snapshot.snapshot_date.isoformat()}", changes=[MutationChange(snapshot.id, before, None)])
    record_audit_event(db, "net_worth_snapshot_delete", actor_for_session(session), "net_worth_snapshot", str(snapshot.id), {"operation_id": operation_id})
    db.delete(snapshot)
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.get("/api/investments/lots")
def get_holding_lots(account_id: int | None = None, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    query = select(HoldingLot).order_by(HoldingLot.acquisition_date.asc(), HoldingLot.id.asc())
    if account_id is not None:
        query = query.where(HoldingLot.account_id == account_id)
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    return [
        {
            "id": lot.id,
            "account_id": lot.account_id,
            "symbol": lot.symbol,
            "acquisition_date": lot.acquisition_date.isoformat(),
            "quantity_basis_points": lot.quantity_basis_points,
            "quantity": lot.quantity_basis_points / 10000,
            "cost_basis_cents": lot.cost_basis_cents,
            "note": lot.note,
            "source": lot.source,
            "import_batch_id": lot.import_batch_id,
            "account": accounts[lot.account_id].display_name if lot.account_id in accounts else "Unknown account",
        }
        for lot in db.scalars(query).all()
    ]


@app.post("/api/investments/lots")
def create_holding_lot(payload: HoldingLotCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, payload.account_id)
    if not account or account.status != "active" or account.account_type not in {"brokerage", "retirement"}:
        raise HTTPException(status_code=400, detail="Choose an active brokerage or retirement account")
    symbol = payload.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Symbol is required")
    lot = HoldingLot(
        account_id=account.id,
        symbol=symbol,
        acquisition_date=payload.acquisition_date,
        quantity_basis_points=payload.quantity_basis_points,
        cost_basis_cents=payload.cost_basis_cents,
        note=payload.note.strip() if payload.note and payload.note.strip() else None,
    )
    db.add(lot)
    db.flush()
    operation_id = journal_mutation(db, kind="create", entity_type="holding_lot", actor=actor_for_session(session), description=f"Added {symbol} tax lot", changes=[MutationChange(lot.id, None, full_values(lot))])
    record_audit_event(db, "holding_lot_create", actor_for_session(session), "holding_lot", str(lot.id), {"account_id": account.id, "symbol": symbol, "operation_id": operation_id})
    db.commit()
    return {"ok": True, "lot_id": lot.id, "operation_id": operation_id}


@app.patch("/api/investments/lots/{lot_id}")
def update_holding_lot(lot_id: int, payload: HoldingLotUpdate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    lot = db.get(HoldingLot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Holding lot not found")
    before = full_values(lot)
    lot.acquisition_date = payload.acquisition_date
    lot.quantity_basis_points = payload.quantity_basis_points
    lot.cost_basis_cents = payload.cost_basis_cents
    lot.note = payload.note.strip() if payload.note and payload.note.strip() else None
    db.flush()
    operation_id = journal_mutation(db, kind="update", entity_type="holding_lot", actor=actor_for_session(session), description=f"Updated {lot.symbol} tax lot", changes=[MutationChange(lot.id, before, full_values(lot))])
    record_audit_event(db, "holding_lot_update", actor_for_session(session), "holding_lot", str(lot.id), {"account_id": lot.account_id, "symbol": lot.symbol, "operation_id": operation_id})
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.delete("/api/investments/lots/{lot_id}")
def delete_holding_lot(lot_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    lot = db.get(HoldingLot, lot_id)
    if not lot:
        raise HTTPException(status_code=404, detail="Holding lot not found")
    operation_id = journal_mutation(db, kind="delete", entity_type="holding_lot", actor=actor_for_session(session), description=f"Deleted {lot.symbol} tax lot", changes=[MutationChange(lot.id, full_values(lot), None)])
    record_audit_event(db, "holding_lot_delete", actor_for_session(session), "holding_lot", str(lot.id), {"account_id": lot.account_id, "symbol": lot.symbol, "operation_id": operation_id})
    db.delete(lot)
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@app.get("/api/investments/holdings")
def get_investment_holdings(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    accounts = {account.id: account for account in db.scalars(select(Account)).all()}
    institutions = {institution.id: institution.name for institution in db.scalars(select(Institution)).all()}
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
    lots_by_security: dict[tuple[int, str], list[HoldingLot]] = {}
    for lot in db.scalars(select(HoldingLot).order_by(HoldingLot.acquisition_date.asc(), HoldingLot.id.asc())).all():
        lots_by_security.setdefault((lot.account_id, lot.symbol.upper()), []).append(lot)
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
        security_lots = lots_by_security.get((row.account_id, symbol_key), []) if symbol_key else []
        cost_basis_cents = sum(lot.cost_basis_cents for lot in security_lots) if security_lots else row.cost_basis_cents
        oldest_acquisition_date = security_lots[0].acquisition_date if security_lots else None
        payload.append(
            {
                "id": row.id,
                "account_id": row.account_id,
                "account": accounts[row.account_id].display_name if row.account_id in accounts else "Unknown account",
                "institution": institutions.get(accounts[row.account_id].institution_id) if row.account_id in accounts else None,
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
                "lot_count": len(security_lots),
                "lot_quantity": sum(lot.quantity_basis_points for lot in security_lots) / 10000 if security_lots else None,
                "cost_basis_cents": cost_basis_cents,
                "unrealized_gain_loss_cents": displayed_value_cents - cost_basis_cents if cost_basis_cents is not None else None,
                "oldest_acquisition_date": oldest_acquisition_date.isoformat() if oldest_acquisition_date else None,
                "lot_age_days": (date.today() - oldest_acquisition_date).days if oldest_acquisition_date else None,
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
    before = full_values(metadata) if metadata else None
    if not metadata:
        metadata = SecurityMetadata(symbol=symbol)
        db.add(metadata)
        db.flush()
    metadata.user_description = payload.user_description.strip() if payload.user_description else None
    operation_id = journal_mutation(db, kind="update" if before else "create", entity_type="security_metadata", actor=actor_for_session(session), description=f'Updated holding description for {symbol}', changes=[MutationChange(metadata.id, before, full_values(metadata))])
    record_audit_event(db, "holding_metadata_update", "local-user", "security_metadata", symbol, {"symbol": symbol})
    db.commit()
    return {"ok": True, "operation_id": operation_id}



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
    changes = [MutationChange(holding.id, full_values(holding), None) for holding in holdings]
    scopes = {(holding.account_id, holding.snapshot_date) for holding in holdings}
    for holding in holdings:
        _delete_holding_row(db, holding)
    operation_id = journal_mutation(db, kind="delete", entity_type="holding_snapshot", actor=actor_for_session(session), description=f"Deleted {len(holdings)} holding rows", changes=changes)
    for account_id, snapshot_date in scopes:
        refresh_holding_net_worth_snapshot(db, account_id=account_id, snapshot_date=snapshot_date)
    db.commit()
    return {"ok": True, "deleted": len(holdings), "operation_id": operation_id}

@app.delete("/api/investments/holdings/{holding_id}")
def delete_holding(holding_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    _require_delete_confirmation(payload.confirm_text)
    holding = db.get(HoldingSnapshot, holding_id)
    if not holding:
        raise HTTPException(status_code=404, detail="Holding row not found")
    account_id, snapshot_date = holding.account_id, holding.snapshot_date
    operation_id = journal_mutation(db, kind="delete", entity_type="holding_snapshot", actor=actor_for_session(session), description=f'Deleted holding "{holding.symbol or holding.description or holding.id}"', changes=[MutationChange(holding.id, full_values(holding), None)])
    _delete_holding_row(db, holding)
    refresh_holding_net_worth_snapshot(db, account_id=account_id, snapshot_date=snapshot_date)
    db.commit()
    return {"ok": True, "operation_id": operation_id}


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

@app.get("/api/exports/transactions.csv")
def export_transactions(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
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
