from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..db import get_db
from ..models import Category, CategoryRule, ExpenseAllocation, SessionToken, Transaction, TransactionSplit
from ..schemas import CategoryCreate, CategoryUpdate
from ..security import require_csrf
from ..services.mutation_log import MutationChange, changed_values, full_values, journal_mutation
from .dependencies import actor_for_session, current_session


router = APIRouter()


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
        reference_counts = category_reference_counts(db, category.id)
        changes.append(MutationChange(category.id, full_values(category), None, entity_type="category"))
        changes.extend(category_reference_changes(db, category.id, replacement.id))
        reassign_category_references(db, category.id, replacement.id)
        record_audit_event(db, "category_merge", actor, "category", str(replacement.id), {"source_category_id": category.id, "source_label": category.label, "target_label": replacement.label, **reference_counts})
        db.delete(category)
        merged += 1
        reassigned += sum(reference_counts.values())
    operation_id = journal_mutation(db, kind="merge", entity_type="mixed", actor=actor, description=f"Merged {merged} duplicate categories", changes=changes) if changes else None
    db.commit()
    return {"merged": merged, "reassigned": reassigned, "operation_id": operation_id}


@router.post("/api/categories")
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


@router.post("/api/categories/cleanup-duplicates")
def cleanup_categories_from_import_labels(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    return cleanup_duplicate_categories(db)


@router.patch("/api/categories/{category_id}")
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


@router.delete("/api/categories/{category_id}")
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
    reference_counts = category_reference_counts(db, category_id)
    if sum(reference_counts.values()) and replacement is None:
        raise HTTPException(status_code=400, detail="This category is in use. Choose a replacement category to merge it safely.")
    target_category_id = replacement.id if replacement else None
    changes: list[MutationChange] = [MutationChange(category.id, full_values(category), None, entity_type="category")]
    changes.extend(category_reference_changes(db, category_id, target_category_id))
    if replacement:
        reassign_category_references(db, category_id, replacement.id)
    else:
        db.execute(update(Category).where(Category.parent_id == category_id).values(parent_id=None))
    record_audit_event(db, "category_delete", "local-user", "category", str(category.id), {"label": category.label, "reassigned_to": replacement.id if replacement else None, **reference_counts})
    db.delete(category)
    operation_id = journal_mutation(db, kind="delete", entity_type="mixed" if len(changes) > 1 else "category", actor=actor_for_session(session), description=f'Deleted category "{category.label}"', changes=changes)
    db.commit()
    return {"ok": True, "reassigned": sum(reference_counts.values()), "operation_id": operation_id}


def category_reference_counts(db: Session, category_id: int) -> dict[str, int]:
    return {
        "transactions": db.scalar(select(func.count(Transaction.id)).where(Transaction.category_id == category_id)) or 0,
        "splits": db.scalar(select(func.count(TransactionSplit.id)).where(TransactionSplit.category_id == category_id)) or 0,
        "allocations": db.scalar(select(func.count(ExpenseAllocation.id)).where(ExpenseAllocation.category_id == category_id)) or 0,
        "rules": db.scalar(select(func.count(CategoryRule.id)).where(CategoryRule.category_id == category_id)) or 0,
    }


def category_reference_changes(db: Session, category_id: int, replacement_id: int | None) -> list[MutationChange]:
    reference_groups = [
        ("transaction", db.scalars(select(Transaction).where(Transaction.category_id == category_id)).all(), "category_id"),
        ("transaction_split", db.scalars(select(TransactionSplit).where(TransactionSplit.category_id == category_id)).all(), "category_id"),
        ("expense_allocation", db.scalars(select(ExpenseAllocation).where(ExpenseAllocation.category_id == category_id)).all(), "category_id"),
        ("category_rule", db.scalars(select(CategoryRule).where(CategoryRule.category_id == category_id)).all(), "category_id"),
        ("category", db.scalars(select(Category).where(Category.parent_id == category_id)).all(), "parent_id"),
    ]
    return [
        MutationChange(row.id, changed_values(row, [field]), {"id": row.id, field: replacement_id}, entity_type=entity_type)
        for entity_type, rows, field in reference_groups
        for row in rows
    ]


def reassign_category_references(db: Session, category_id: int, replacement_id: int) -> None:
    db.execute(update(Transaction).where(Transaction.category_id == category_id).values(category_id=replacement_id))
    db.execute(update(TransactionSplit).where(TransactionSplit.category_id == category_id).values(category_id=replacement_id))
    db.execute(update(ExpenseAllocation).where(ExpenseAllocation.category_id == category_id).values(category_id=replacement_id))
    db.execute(update(CategoryRule).where(CategoryRule.category_id == category_id).values(category_id=replacement_id))
    db.execute(update(Category).where(Category.parent_id == category_id).values(parent_id=replacement_id))
