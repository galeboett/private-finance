from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..db import get_db
from ..models import (
    Account,
    AccountIdentifier,
    HoldingLot,
    HoldingSnapshot,
    ImportBatch,
    ImportPreset,
    ImportSignProfile,
    NetWorthSnapshot,
    SessionToken,
    StagingRow,
    StatementCheckpoint,
    Transaction,
)
from ..schemas import AccountCreate, AccountIdentifierCreate, AccountUpdate, BulkDeleteRequest, DeleteConfirmRequest, StatementCheckpointCreate
from ..security import require_csrf
from ..services.account_identifiers import record_account_identifier
from ..services.accounts import UNASSIGNED_ACCOUNT_MARKER, cleanup_imported_accounts, upsert_institution_by_name
from ..services.mutation_log import MutationChange, changed_values, full_values, journal_mutation
from ..services.reconciliation import list_reconciliation_statuses, reconciliation_status, save_manual_checkpoint
from ..services.snapshots import account_is_anchored, current_account_value
from ..services.transaction_queries import live_transaction_filters, live_transaction_select
from .dependencies import actor_for_session, current_session, require_delete_confirmation


router = APIRouter()


@router.post("/api/accounts")
def create_account(payload: AccountCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    institution = upsert_institution_by_name(db, payload.institution_name)
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


@router.get("/api/accounts")
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


@router.get("/api/accounts/{account_id}/identifiers")
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


@router.post("/api/accounts/{account_id}/identifiers")
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
        identifier = record_account_identifier(db, account, payload.last_four, make_current=payload.make_current, source=payload.source)
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
    record_audit_event(db, "account_identifier_create", "local-user", "account", str(account.id), {"last_four": identifier.identifier_value, "make_current": payload.make_current, "source": payload.source})
    db.commit()
    return {"ok": True, "account_id": account.id, "last_four": account.last_four, "operation_id": operation_id}


@router.get("/api/reconciliation")
def get_reconciliation_statuses(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_reconciliation_statuses(db)


@router.post("/api/accounts/{account_id}/statement-checkpoints")
def create_statement_checkpoint(account_id: int, payload: StatementCheckpointCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    account = db.get(Account, account_id)
    if not account or account.status != "active":
        raise HTTPException(status_code=404, detail="Active account not found")
    saved = save_manual_checkpoint(db, account=account, statement_date=payload.statement_date, statement_balance_cents=payload.statement_balance_cents, actor=actor_for_session(session))
    db.commit()
    return {**saved, "reconciliation": reconciliation_status(db, account)}


@router.post("/api/accounts/cleanup-imported")
def cleanup_accounts_from_import_labels(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    return cleanup_imported_accounts(db)


@router.patch("/api/accounts/{account_id}")
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
        institution = upsert_institution_by_name(db, updates.pop("institution_name"))
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
        for identifier in db.scalars(select(AccountIdentifier).where(AccountIdentifier.account_id == account.id, AccountIdentifier.is_current.is_(True))).all():
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


@router.post("/api/accounts/{account_id}/archive")
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
    if transactions:
        unassigned_account = Account(display_name=f"Needs account ({account.display_name})", account_type="other", currency=account.currency, status="archived", last_four=UNASSIGNED_ACCOUNT_MARKER)
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
    record_audit_event(db, "account_delete", "local-user", "account", str(account.id), {"display_name": account.display_name, "account_type": account.account_type, "preserved_transactions": len(transactions)})
    db.delete(account)
    return changes


@router.delete("/api/accounts/bulk-delete")
def bulk_delete_accounts(payload: BulkDeleteRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    require_delete_confirmation(payload.confirm_text)
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


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    require_delete_confirmation(payload.confirm_text)
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    changes = _delete_account_tree(db, account)
    operation_id = journal_mutation(db, kind="delete", entity_type="mixed", actor=actor_for_session(session), description=f'Deleted account "{account.display_name}"', changes=changes)
    db.commit()
    return {"ok": True, "operation_id": operation_id}
