from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy.orm import Session

from ..models import Operation, OperationChange


@dataclass(frozen=True)
class MutationChange:
    entity_id: str | int
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    entity_type: str | None = None


def changed_values(entity: Any, fields: Iterable[str]) -> dict[str, Any]:
    """Capture only the primary key and columns changed by one logical operation."""
    return {"id": entity.id, **{field: getattr(entity, field) for field in fields}}


def full_values(entity: Any) -> dict[str, Any]:
    """Capture the reversible persisted state of one entity, excluding timestamps."""
    return {
        column.name: getattr(entity, column.name)
        for column in entity.__table__.columns
        if column.name not in {"created_at", "updated_at"}
    }


def journal_mutation(
    db: Session,
    *,
    kind: str,
    entity_type: str,
    actor: str,
    description: str,
    changes: Iterable[MutationChange],
    undo_of: str | None = None,
) -> str:
    """Append a journal entry to the caller's current database transaction.

    This function deliberately never commits. The mutation and its journal entry
    therefore succeed or roll back together through the caller's SQLAlchemy session.
    """
    materialized_changes = list(changes)
    if not materialized_changes:
        raise ValueError("A journaled mutation must contain at least one change")

    operation_id = str(uuid4())
    db.add(
        Operation(
            id=operation_id,
            kind=kind,
            entity_type=entity_type,
            actor=actor,
            description=description,
            undo_of=undo_of,
        )
    )
    for change in materialized_changes:
        db.add(
            OperationChange(
                operation_id=operation_id,
                entity_type=change.entity_type or entity_type,
                entity_id=str(change.entity_id),
                before_json=_encode_image(change.before),
                after_json=_encode_image(change.after),
            )
        )
    return operation_id


def _encode_image(image: dict[str, Any] | None) -> str | None:
    if image is None:
        return None
    return json.dumps(image, default=_json_default, sort_keys=True, separators=(",", ":"))


def _json_default(value: Any):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Unsupported mutation value: {type(value).__name__}")
