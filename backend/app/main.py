from __future__ import annotations

import csv
import io
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
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
from .models import Account, AppUser, Category, CategoryRule, ExpenseAllocation, HoldingSnapshot, ImportBatch, ImportPreset, Institution, NetWorthSnapshot, SecurityMetadata, SecurityPrice, SessionToken, StagingRow, Transaction, TransactionSplit, TransferLink
from .money import cents_to_decimal_string, escape_csv_formula
from .schemas import AccountCreate, AccountUpdate, BulkDeleteRequest, BulkIdsRequest, BulkRuleCreateRequest, BulkTransactionUpdateRequest, CategoryCreate, CategoryUpdate, DeleteConfirmRequest, HoldingMetadataUpdate, ImportPresetCreate, LoginRequest, MonthlyAllocationRequest, NetWorthSnapshotUpsert, OperationBulkUpdateRequest, PasswordChangeRequest, ReviewStatus, RuleApplyRequest, RuleCreate, RuleUpdate, SetupRequest, SplitSetRequest, TransactionFilter, TransactionReviewUpdate, TransactionType, TransferLinkCreate, UndoOperationRequest
from .security import clear_login_failures, create_session, enforce_login_rate_limit, ensure_setup_state, get_session_from_request, hash_password, password_needs_rehash, purge_expired_sessions, record_login_failure, require_csrf, set_session_cookie, verify_password
from .services.accounts import cleanup_imported_accounts
from .services.aggregation import aggregate_by_account, aggregate_by_category, aggregate_timeseries
from .services.backups import BackupError, create_backup, list_backups, resolve_backup_destination, resolve_restore_source, restore_backup
from .services.importers import annotate_import_interpretation, apply_import_sign_convention, commit_categorized_history, commit_import, commit_reviewed_categorized_history, decode_text, detect_preset_from_content, preview_import, review_categorized_history, suggest_account_for_import
from .services.import_inbox import confirm_pending_import, discard_pending_import, inbox_directory, pending_import_batches, scan_import_inbox, stage_uploaded_import
from .services.history_cleanup import apply_categorized_history_sign_cleanup, preview_categorized_history_sign_cleanup
from .services.mutation_log import MutationChange, changed_values, full_values, journal_mutation
from .services.operation_history import OperationConflict, list_operations, operation_detail, undo_operation
from .services.reporting import cash_flow_summary, category_totals, dashboard_summary, latest_investment_allocation, latest_net_worth_by_account
from .services.snapshots import net_worth_contributors, net_worth_series, net_worth_stats, refresh_holding_net_worth_snapshot, upsert_net_worth_snapshot
from .services.transaction_filters import parse_csv_ints, parse_csv_values, transaction_filter_conditions
from .services.transaction_queries import get_live_transaction, live_transaction_filters, live_transaction_select
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

UNASSIGNED_ACCOUNT_MARKER = "SYSTEM"


def actor_for_session(session: SessionToken) -> str:
    return f"user:{session.user_id}"


def normalize_transaction_labels(value: object) -> str | None:
    labels = []
    for raw in str(value or "").split(","):
        label = " ".join(raw.strip().casefold().replace("|", "").split())
        if label and label not in labels:
            labels.append(label)
    return f"|{'|'.join(labels)}|" if labels else None


def transaction_labels(value: str | None) -> list[str]:
    return [label for label in (value or "").strip("|").split("|") if label]


def transaction_filter_dependency(
    accounts: str | None = None,
    categories: str | None = None,
    tags: str | None = None,
    months: str | None = None,
    years: str | None = None,
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    date_basis: Literal["transaction", "reporting"] = Query(default="transaction", alias="dateBasis"),
    amount_min: int | None = Query(default=None, alias="amountMin", ge=0),
    amount_max: int | None = Query(default=None, alias="amountMax", ge=0),
    direction: Literal["inflow", "outflow"] | None = None,
    types: str | None = None,
    search: str | None = None,
    view: Literal["live", "trash"] = "live",
    review_status: ReviewStatus | None = None,
) -> TransactionFilter:
    try:
        transaction_types = [TransactionType(value) for value in parse_csv_values(types)]
    except ValueError as error:
        raise HTTPException(status_code=422, detail=f'Unknown transaction type "{error.args[0]}"') from error
    return TransactionFilter(
        accounts=parse_csv_ints(accounts),
        categories=parse_csv_values(categories),
        tags=parse_csv_values(tags),
        months=parse_csv_values(months),
        years=parse_csv_values(years),
        date_from=date_from,
        date_to=date_to,
        date_basis=date_basis,
        amount_min=amount_min,
        amount_max=amount_max,
        direction=direction,
        transaction_types=transaction_types,
        search=search,
        view=view,
        review_status=review_status,
    )


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
    updates = payload.patch.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Provide at least one field to update")
    if "account_id" in updates:
        account = db.get(Account, updates["account_id"])
        if not account or account.last_four == UNASSIGNED_ACCOUNT_MARKER:
            raise HTTPException(status_code=400, detail="Choose a valid account")
    if "category_id" in updates and updates["category_id"] is not None and not db.get(Category, updates["category_id"]):
        raise HTTPException(status_code=400, detail="Category not found")
    changes: list[MutationChange] = []
    for transaction in transactions:
        before = changed_values(transaction, updates.keys())
        for key, value in updates.items():
            setattr(transaction, key, value)
        changes.append(MutationChange(transaction.id, before, changed_values(transaction, updates.keys())))
    operation_id = journal_mutation(db, kind="bulk_update", entity_type="transaction", actor=actor_for_session(session), description=f"Updated {len(transactions)} transactions", changes=changes)
    db.commit()
    return {"ok": True, "updated": len(transactions), "operation_id": operation_id}


@app.post("/api/operations/bulk-create-rules")
def operation_bulk_create_rules(payload: BulkRuleCreateRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    category_ids = {rule.category_id for rule in payload.rules}
    if len(db.scalars(select(Category.id).where(Category.id.in_(category_ids))).all()) != len(category_ids):
        raise HTTPException(status_code=400, detail="One or more categories were not found")
    rules = [CategoryRule(**rule.model_dump()) for rule in payload.rules]
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
    operation_id = journal_mutation(db, kind="create", entity_type="account", actor=actor_for_session(session), description=f'Created account "{account.display_name}"', changes=[MutationChange(account.id, None, full_values(account))])
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
        latest_running_balance = db.scalar(
            live_transaction_select(Transaction.account_id == account.id, Transaction.running_balance_cents.is_not(None))
            .order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
            .limit(1)
        )
        latest_holding_date = db.scalar(select(func.max(HoldingSnapshot.snapshot_date)).where(HoldingSnapshot.account_id == account.id))
        if account.account_type in {"brokerage", "retirement"} and latest_holding_date:
            sidebar_balance_cents = db.scalar(
                select(func.coalesce(func.sum(HoldingSnapshot.market_value_cents), 0)).where(
                    HoldingSnapshot.account_id == account.id, HoldingSnapshot.snapshot_date == latest_holding_date
                )
            )
            sidebar_balance_kind = "investment_snapshot"
            sidebar_balance_as_of = latest_holding_date.isoformat()
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
            "sidebar_balance_cents": sidebar_balance_cents or 0,
            "sidebar_balance_kind": sidebar_balance_kind,
            "sidebar_balance_as_of": sidebar_balance_as_of,
        })
    return result


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
    before = changed_values(account, changed_fields)
    if "institution_name" in updates:
        institution = upsert_institution(db, updates.pop("institution_name"))
        account.institution_id = institution.id if institution else None
    for key, value in updates.items():
        setattr(account, key, value)
    operation_id = journal_mutation(db, kind="update", entity_type="account", actor=actor_for_session(session), description=f'Updated account "{account.display_name}"', changes=[MutationChange(account.id, before, changed_values(account, changed_fields))])
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
    batches = db.scalars(select(ImportBatch).where(ImportBatch.account_id == account.id)).all()
    staging_rows = db.scalars(select(StagingRow).where(StagingRow.account_id == account.id)).all()
    holdings = db.scalars(select(HoldingSnapshot).where(HoldingSnapshot.account_id == account.id)).all()
    changes: list[MutationChange] = [MutationChange(account.id, full_values(account), None, entity_type="account")]
    changes.extend(MutationChange(preset.id, full_values(preset), None, entity_type="import_preset") for preset in presets)
    changes.extend(MutationChange(batch.id, full_values(batch), None, entity_type="import_batch") for batch in batches)
    changes.extend(MutationChange(row.id, full_values(row), None, entity_type="staging_row") for row in staging_rows)
    changes.extend(MutationChange(holding.id, full_values(holding), None, entity_type="holding_snapshot") for holding in holdings)
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
    db.execute(delete(ImportBatch).where(ImportBatch.account_id == account.id))
    db.execute(delete(ImportPreset).where(ImportPreset.account_id == account.id))
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
        "match_confidence": suggestion.match_confidence,
        "reason": suggestion.reason,
        "proposed_account": suggestion.proposed_account,
        "warnings": suggestion.warnings,
    }


@app.post("/api/imports/preview")
async def imports_preview(account_id: int, sign_convention: Literal["preset", "reverse"] = "preset", file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    content = await file.read()
    if len(content) > settings.import_file_size_limit_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")
    try:
        preset_type = detect_preset_from_content(decode_text(content), file.filename or "import.csv")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not preset_type:
        raise HTTPException(status_code=400, detail="Could not detect import preset")
    try:
        preview = annotate_import_interpretation(apply_import_sign_convention(preview_import(content, preset_type), sign_convention), account)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"preset_type": preset_type, "sign_convention": sign_convention, "rows": preview.rows[:25], "warnings": preview.warnings}


@app.post("/api/imports/commit")
async def imports_commit(request: Request, account_id: int, preset_id: int | None = None, snapshot_date: str | None = None, sign_convention: Literal["preset", "reverse"] = "preset", file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
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
        result = commit_import(db, account, preset, file.filename or "import.csv", content, actor=actor_for_session(session), snapshot_date=parsed_snapshot_date, sign_convention=sign_convention)
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
async def stage_manual_import(request: Request, account_id: int, sign_convention: Literal["preset", "reverse"] = "preset", file: UploadFile = File(...), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    content = await file.read()
    try:
        result = stage_uploaded_import(db, account=account, filename=file.filename or "import.csv", content=content, sign_convention=sign_convention)
    except (UnicodeDecodeError, ValueError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return {**result, "pending": pending_import_batches(db)}


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
            before = changed_values(transaction, ["transaction_type"])
            transaction.transaction_type = transaction_type.value
            journal_changes.append(MutationChange(transaction.id, before, changed_values(transaction, ["transaction_type"])))
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
    updates = payload.model_dump(exclude_unset=True)
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
    before = changed_values(transaction, updates.keys())
    for key, value in updates.items():
        setattr(transaction, key, value)
    actor = actor_for_session(session)
    operation_id = journal_mutation(
        db,
        kind="update",
        entity_type="transaction",
        actor=actor,
        description=f'Updated transaction "{transaction.raw_description}"',
        changes=[MutationChange(transaction.id, before, changed_values(transaction, updates.keys()))],
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
    operation_id = journal_mutation(db, kind="create", entity_type="category_rule", actor=actor_for_session(session), description=f'Created rule "{rule.match_text}"', changes=[MutationChange(rule.id, None, full_values(rule))])
    record_audit_event(db, "rule_create", "local-user", "category_rule", str(rule.id), payload.model_dump())
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

    operation_id = journal_mutation(db, kind="bulk_update", entity_type="transaction", actor=actor_for_session(session), description=f'Applied rule "{rule.match_text}" to {updated} transactions', changes=changes) if changes else None

    record_audit_event(db, "rule_apply", "local-user", "category_rule", str(rule.id), {"scope": payload.scope, "matched": matched, "updated": updated})
    db.commit()
    return {"matched": matched, "updated": updated, "operation_id": operation_id}


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
    if "category_id" in updates and not db.get(Category, updates["category_id"]):
        raise HTTPException(status_code=400, detail="Category not found")
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


@app.get("/api/aggregate/by-category")
def get_aggregate_by_category(
    filters: TransactionFilter = Depends(transaction_filter_dependency),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    return aggregate_by_category(db, filters)


@app.get("/api/aggregate/by-account")
def get_aggregate_by_account(
    filters: TransactionFilter = Depends(transaction_filter_dependency),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    return aggregate_by_account(db, filters)


@app.get("/api/aggregate/timeseries")
def get_aggregate_timeseries(
    bucket: Literal["day", "week", "month"] = "month",
    filters: TransactionFilter = Depends(transaction_filter_dependency),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    return aggregate_timeseries(db, filters, bucket)


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
    HoldingSnapshot,
    NetWorthSnapshot,
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
    HoldingSnapshot: "holding_snapshot",
    NetWorthSnapshot: "net_worth_snapshot",
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
