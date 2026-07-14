from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, StatementCheckpoint, Transaction
from .mutation_log import MutationChange, full_values, journal_mutation


def record_imported_checkpoints(db: Session, transactions: Iterable[Transaction]) -> list[MutationChange]:
    latest_by_scope: dict[tuple[int, date], Transaction] = {}
    for transaction in transactions:
        if transaction.running_balance_cents is None:
            continue
        scope = (transaction.account_id, transaction.transaction_date)
        current = latest_by_scope.get(scope)
        if current is None or (transaction.id or 0) > (current.id or 0):
            latest_by_scope[scope] = transaction
    changes: list[MutationChange] = []
    for (account_id, statement_date), transaction in latest_by_scope.items():
        checkpoint = db.scalar(select(StatementCheckpoint).where(StatementCheckpoint.account_id == account_id, StatementCheckpoint.statement_date == statement_date))
        if checkpoint and checkpoint.source == "manual":
            continue
        before = full_values(checkpoint) if checkpoint else None
        if checkpoint is None:
            checkpoint = StatementCheckpoint(account_id=account_id, statement_date=statement_date, statement_balance_cents=transaction.running_balance_cents, source="import")
            db.add(checkpoint)
            db.flush()
        else:
            checkpoint.statement_balance_cents = transaction.running_balance_cents
            checkpoint.source = "import"
            db.flush()
        after = full_values(checkpoint)
        if before != after:
            changes.append(MutationChange(checkpoint.id, before, after, entity_type="statement_checkpoint"))
    return changes


def backfill_statement_checkpoints(db: Session) -> int:
    rows = db.scalars(
        select(Transaction).where(
            Transaction.deleted_at.is_(None),
            Transaction.status == "active",
            Transaction.running_balance_cents.is_not(None),
        ).order_by(Transaction.account_id, Transaction.transaction_date, Transaction.id)
    ).all()
    latest_by_scope: dict[tuple[int, date], Transaction] = {}
    for transaction in rows:
        latest_by_scope[(transaction.account_id, transaction.transaction_date)] = transaction
    created = 0
    for (account_id, statement_date), transaction in latest_by_scope.items():
        existing = db.scalar(select(StatementCheckpoint.id).where(StatementCheckpoint.account_id == account_id, StatementCheckpoint.statement_date == statement_date))
        if existing is None:
            db.add(StatementCheckpoint(account_id=account_id, statement_date=statement_date, statement_balance_cents=transaction.running_balance_cents, source="import"))
            created += 1
    return created


def save_manual_checkpoint(db: Session, *, account: Account, statement_date: date, statement_balance_cents: int, actor: str) -> dict[str, Any]:
    checkpoint = db.scalar(select(StatementCheckpoint).where(StatementCheckpoint.account_id == account.id, StatementCheckpoint.statement_date == statement_date))
    before = full_values(checkpoint) if checkpoint else None
    if checkpoint is None:
        checkpoint = StatementCheckpoint(account_id=account.id, statement_date=statement_date, statement_balance_cents=statement_balance_cents, source="manual")
        db.add(checkpoint)
        db.flush()
    else:
        checkpoint.statement_balance_cents = statement_balance_cents
        checkpoint.source = "manual"
        db.flush()
    operation_id = journal_mutation(
        db,
        kind="update" if before else "create",
        entity_type="statement_checkpoint",
        actor=actor,
        description=f"Saved statement balance for {account.display_name} on {statement_date.isoformat()}",
        changes=[MutationChange(checkpoint.id, before, full_values(checkpoint))],
    )
    return {"checkpoint_id": checkpoint.id, "operation_id": operation_id}


def reconciliation_status(db: Session, account: Account) -> dict[str, Any]:
    checkpoints = db.scalars(
        select(StatementCheckpoint).where(StatementCheckpoint.account_id == account.id).order_by(StatementCheckpoint.statement_date, StatementCheckpoint.id)
    ).all()
    statuses: list[dict[str, Any]] = []
    previous: StatementCheckpoint | None = None
    last_reconciled_date: date | None = None
    for checkpoint in checkpoints:
        if previous:
            computed = previous.statement_balance_cents + _activity_sum(db, account.id, previous.statement_date + timedelta(days=1), checkpoint.statement_date)
            investigate_from = previous.statement_date + timedelta(days=1)
        else:
            anchor = db.scalar(
                select(Transaction).where(
                    Transaction.account_id == account.id,
                    Transaction.transaction_date <= checkpoint.statement_date,
                    Transaction.running_balance_cents.is_not(None),
                    Transaction.deleted_at.is_(None),
                    Transaction.status == "active",
                ).order_by(Transaction.transaction_date.desc(), Transaction.id.desc()).limit(1)
            )
            if anchor:
                computed = anchor.running_balance_cents
                if anchor.transaction_date < checkpoint.statement_date:
                    computed += _activity_sum(db, account.id, anchor.transaction_date + timedelta(days=1), checkpoint.statement_date)
                investigate_from = anchor.transaction_date
            else:
                computed = _activity_sum(db, account.id, None, checkpoint.statement_date)
                first_date = db.scalar(select(func.min(Transaction.transaction_date)).where(Transaction.account_id == account.id, Transaction.deleted_at.is_(None), Transaction.status == "active"))
                investigate_from = first_date or checkpoint.statement_date
        delta = computed - checkpoint.statement_balance_cents
        if delta == 0:
            last_reconciled_date = checkpoint.statement_date
        statuses.append({
            "checkpoint_id": checkpoint.id,
            "statement_date": checkpoint.statement_date.isoformat(),
            "statement_balance_cents": checkpoint.statement_balance_cents,
            "computed_balance_cents": computed,
            "delta_cents": delta,
            "reconciled": delta == 0,
            "source": checkpoint.source,
            "investigate_from": investigate_from.isoformat(),
            "investigate_to": checkpoint.statement_date.isoformat(),
        })
        previous = checkpoint
    latest = statuses[-1] if statuses else None
    return {
        "account_id": account.id,
        "account_name": account.display_name,
        "account_type": account.account_type,
        "latest": latest,
        "reconciled_through": last_reconciled_date.isoformat() if last_reconciled_date else None,
        "checkpoint_count": len(statuses),
    }


def list_reconciliation_statuses(db: Session) -> list[dict[str, Any]]:
    accounts = db.scalars(select(Account).where(Account.status == "active").order_by(Account.display_name, Account.id)).all()
    return [reconciliation_status(db, account) for account in accounts]


def _activity_sum(db: Session, account_id: int, start_date: date | None, end_date: date) -> int:
    query = select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.account_id == account_id,
        Transaction.transaction_date <= end_date,
        Transaction.deleted_at.is_(None),
        Transaction.status == "active",
    )
    if start_date is not None:
        query = query.where(Transaction.transaction_date >= start_date)
    return int(db.scalar(query) or 0)
