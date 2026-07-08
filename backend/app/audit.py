import json

from sqlalchemy.orm import Session

from .models import AuditEvent


def record_audit_event(db: Session, event_type: str, actor: str, entity_type: str, entity_id: str, details: dict) -> None:
    db.add(
        AuditEvent(
            event_type=event_type,
            actor=actor,
            entity_type=entity_type,
            entity_id=entity_id,
            details_json=json.dumps(details, default=str),
        )
    )

