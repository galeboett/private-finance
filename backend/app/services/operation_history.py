from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, HoldingSnapshot, NetWorthSnapshot, Operation, OperationChange, Transaction
from .mutation_log import MutationChange, journal_mutation


ENTITY_MODELS = {
    "transaction": Transaction,
    "account": Account,
    "holding_snapshot": HoldingSnapshot,
}


class OperationConflict(ValueError):
    def __init__(self, entity_ids: list[str]):
        super().__init__("One or more rows were changed by a later operation")
        self.entity_ids = entity_ids


def list_operations(db: Session, *, limit: int = 50, entity_type: str | None = None, actor: str | None = None) -> list[dict[str, Any]]:
    change_counts = (
        select(OperationChange.operation_id, func.count(OperationChange.id).label("change_count"))
        .group_by(OperationChange.operation_id)
        .subquery()
    )
    query = (
        select(Operation, change_counts.c.change_count)
        .join(change_counts, change_counts.c.operation_id == Operation.id)
        .order_by(Operation.created_at.desc())
        .limit(limit)
    )
    if entity_type:
        query = query.where(Operation.entity_type == entity_type)
    if actor:
        query = query.where(Operation.actor == actor)
    return [_operation_summary(operation, count) for operation, count in db.execute(query).all()]


def operation_detail(db: Session, operation_id: str) -> dict[str, Any] | None:
    operation = db.get(Operation, operation_id)
    if not operation:
        return None
    changes = db.scalars(
        select(OperationChange)
        .where(OperationChange.operation_id == operation.id)
        .order_by(OperationChange.id)
    ).all()
    payload = _operation_summary(operation, len(changes))
    payload["changes"] = [
        {
            "id": change.id,
            "entity_id": change.entity_id,
            "before": _decode_image(change.before_json),
            "after": _decode_image(change.after_json),
        }
        for change in changes
    ]
    return payload


def undo_operation(db: Session, *, operation_id: str, actor: str, unconflicted_only: bool = False) -> dict[str, Any]:
    operation = db.get(Operation, operation_id)
    if not operation:
        raise LookupError("Operation not found")
    if operation.undone_by:
        raise ValueError("This operation has already been undone")
    model = ENTITY_MODELS.get(operation.entity_type)
    if model is None:
        raise ValueError(f'Undo is not supported for entity type "{operation.entity_type}"')

    changes = db.scalars(
        select(OperationChange)
        .where(OperationChange.operation_id == operation.id)
        .order_by(OperationChange.id)
    ).all()
    conflicts = _later_conflicts(db, operation, changes)
    if conflicts and not unconflicted_only:
        raise OperationConflict(conflicts)
    applicable = [change for change in changes if change.entity_id not in conflicts]
    if not applicable:
        raise OperationConflict(conflicts)

    undo_changes: list[MutationChange] = []
    snapshot_scopes: set[tuple[int, date]] = set()
    for change in applicable:
        before = _decode_image(change.before_json)
        after = _decode_image(change.after_json)
        entity = db.get(model, _primary_key(model, change.entity_id))
        if isinstance(entity, (Transaction, HoldingSnapshot)):
            snapshot_scopes.add((entity.account_id, entity.transaction_date if isinstance(entity, Transaction) else entity.snapshot_date))
        elif model is HoldingSnapshot:
            scope_image = before or after or {}
            if scope_image.get("account_id") and scope_image.get("snapshot_date"):
                snapshot_scopes.add((int(scope_image["account_id"]), date.fromisoformat(scope_image["snapshot_date"])))
        current = _capture_image(entity, after or before)
        _apply_image(db, model, entity, before)
        undo_changes.append(MutationChange(change.entity_id, current, before))

    if model in {Transaction, HoldingSnapshot}:
        _sync_import_snapshots(db, model, snapshot_scopes)

    undo_id = journal_mutation(
        db,
        kind="undo",
        entity_type=operation.entity_type,
        actor=actor,
        description=f"Undid: {operation.description}",
        changes=undo_changes,
        undo_of=operation.id,
    )
    operation.undone_by = undo_id
    return {"ok": True, "operation_id": undo_id, "undone": len(applicable), "conflicts": conflicts}


def _operation_summary(operation: Operation, change_count: int) -> dict[str, Any]:
    return {
        "id": operation.id,
        "kind": operation.kind,
        "entity_type": operation.entity_type,
        "actor": operation.actor,
        "description": operation.description,
        "created_at": operation.created_at.isoformat(),
        "change_count": change_count,
        "undone_by": operation.undone_by,
        "undo_of": operation.undo_of,
        "can_undo": operation.undone_by is None,
    }


def _later_conflicts(db: Session, operation: Operation, changes: list[OperationChange]) -> list[str]:
    entity_ids = [change.entity_id for change in changes]
    if not entity_ids:
        return []
    rows = db.execute(
        select(OperationChange.entity_id)
        .join(Operation, Operation.id == OperationChange.operation_id)
        .where(
            Operation.entity_type == operation.entity_type,
            Operation.created_at > operation.created_at,
            OperationChange.entity_id.in_(entity_ids),
        )
        .distinct()
    ).all()
    return sorted({row[0] for row in rows})


def _decode_image(value: str | None) -> dict[str, Any] | None:
    return json.loads(value) if value else None


def _capture_image(entity: Any | None, template: dict[str, Any] | None) -> dict[str, Any] | None:
    if entity is None:
        return None
    fields = (template or {}).keys()
    return {field: getattr(entity, field) for field in fields}


def _apply_image(db: Session, model: type, entity: Any | None, target: dict[str, Any] | None) -> None:
    if target is None:
        if entity is None:
            return
        if model is Transaction:
            entity.deleted_at = datetime.now(UTC).replace(tzinfo=None)
        else:
            db.delete(entity)
        return
    if entity is None:
        required = {column.name for column in model.__table__.columns if not column.nullable and column.default is None and not column.autoincrement}
        if not required.issubset(target):
            raise OperationConflict([str(target.get("id", "unknown"))])
        entity = model()
        db.add(entity)
    for field, value in target.items():
        setattr(entity, field, _coerce_value(model, field, value))


def _coerce_value(model: type, field: str, value: Any) -> Any:
    if value is None:
        return None
    column = model.__table__.columns.get(field)
    if column is None:
        return value
    python_type = column.type.python_type
    if python_type is date and not isinstance(value, date):
        return date.fromisoformat(value)
    if python_type is datetime and not isinstance(value, datetime):
        return datetime.fromisoformat(value)
    return value


def _primary_key(model: type, entity_id: str) -> Any:
    column = next(iter(model.__table__.primary_key.columns))
    return int(entity_id) if column.type.python_type is int else entity_id


def _sync_import_snapshots(db: Session, model: type, scopes: set[tuple[int, date]]) -> None:
    db.flush()
    for account_id, snapshot_date in scopes:
        snapshot = db.scalar(select(NetWorthSnapshot).where(NetWorthSnapshot.account_id == account_id, NetWorthSnapshot.snapshot_date == snapshot_date))
        if snapshot and snapshot.source != "import":
            continue
        if model is HoldingSnapshot:
            total = db.scalar(
                select(func.sum(HoldingSnapshot.market_value_cents)).where(
                    HoldingSnapshot.account_id == account_id,
                    HoldingSnapshot.snapshot_date == snapshot_date,
                )
            )
            if total is None:
                if snapshot:
                    db.delete(snapshot)
            elif snapshot:
                snapshot.balance_cents = total
            else:
                db.add(NetWorthSnapshot(account_id=account_id, snapshot_date=snapshot_date, balance_cents=total, source="import"))
            continue
        latest = db.scalar(
            select(Transaction)
            .where(
                Transaction.account_id == account_id,
                Transaction.transaction_date == snapshot_date,
                Transaction.running_balance_cents.is_not(None),
                Transaction.deleted_at.is_(None),
                Transaction.status == "active",
            )
            .order_by(Transaction.id.desc())
            .limit(1)
        )
        if latest is None:
            if snapshot:
                db.delete(snapshot)
        elif snapshot:
            snapshot.balance_cents = latest.running_balance_cents
        else:
            db.add(NetWorthSnapshot(account_id=account_id, snapshot_date=snapshot_date, balance_cents=latest.running_balance_cents, source="import"))
