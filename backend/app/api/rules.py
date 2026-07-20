from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..db import get_db
from ..models import CategoryRule, SessionToken, Transaction
from ..schemas import RuleApplyRequest, RuleCreate, RuleUpdate
from ..security import require_csrf
from ..services.mutation_log import MutationChange, changed_values, full_values, journal_mutation
from ..services.transaction_queries import get_live_transaction, live_transaction_select
from .dependencies import actor_for_session, current_session
from .transaction_helpers import append_payment_reclassification_dismissal, normalized_rule_category


router = APIRouter()


@router.post("/api/rules")
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


@router.post("/api/rules/{rule_id}/apply")
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


@router.post("/api/rules/{rule_id}/apply-to/{transaction_id}")
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


@router.get("/api/rules/{rule_id}/preview")
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


@router.patch("/api/rules/{rule_id}")
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


@router.delete("/api/rules/{rule_id}")
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


@router.get("/api/rules")
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
