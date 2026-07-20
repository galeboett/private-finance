from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..db import get_db
from ..models import Account, Category, CategoryRule, SessionToken, Transaction
from ..schemas import BulkRuleCreateRequest, OperationBulkUpdateRequest, UndoOperationRequest
from ..security import require_csrf
from ..services.accounts import UNASSIGNED_ACCOUNT_MARKER
from ..services.mutation_log import MutationChange, changed_values, full_values, journal_mutation
from ..services.operation_history import OperationConflict, list_operations, operation_detail, undo_operation
from ..services.transaction_queries import live_transaction_select
from .dependencies import actor_for_session, current_session
from .transaction_helpers import (
    append_payment_reclassification_dismissal,
    normalize_transaction_updates,
    normalized_rule_category,
    validate_transaction_confirmation,
)


router = APIRouter()


@router.get("/api/operations")
def get_operations(
    limit: int = Query(default=50, ge=1, le=200),
    entity_type: str | None = None,
    actor: str | None = None,
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    return list_operations(db, limit=limit, entity_type=entity_type, actor=actor)


@router.get("/api/operations/{operation_id}")
def get_operation(operation_id: str, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    result = operation_detail(db, operation_id)
    if not result:
        raise HTTPException(status_code=404, detail="Operation not found")
    return result


@router.post("/api/operations/{operation_id}/undo")
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


@router.post("/api/operations/bulk-update")
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


@router.post("/api/operations/bulk-create-rules")
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
