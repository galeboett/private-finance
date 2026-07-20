from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..db import get_db
from ..models import (
    Account,
    Category,
    DuplicatePairDecision,
    ExpenseAllocation,
    PaymentVerificationDismissal,
    RefundLink,
    RefundPairDecision,
    RefundReviewResolution,
    SessionToken,
    Transaction,
    TransactionSplit,
    TransferLink,
)
from ..money import cents_to_decimal_string
from ..schemas import (
    BulkDeleteRequest,
    BulkIdsRequest,
    BulkTransactionUpdateRequest,
    DeleteConfirmRequest,
    ManualTransactionCreate,
    MonthlyAllocationRequest,
    ReviewStatus,
    SplitSetRequest,
    TransactionFilter,
    TransactionReviewUpdate,
    TransactionType,
)
from ..security import require_csrf
from ..services.accounts import UNASSIGNED_ACCOUNT_MARKER, upsert_institution_by_name
from ..services.mutation_log import MutationChange, changed_values, full_values, journal_mutation
from ..services.transaction_filters import transaction_filter_conditions
from ..services.transaction_queries import get_live_transaction, live_transaction_select
from .dependencies import (
    actor_for_session,
    current_session,
    require_delete_confirmation,
    transaction_filter_dependency,
)
from .transaction_helpers import (
    CATEGORYLESS_TRANSACTION_TYPES,
    append_payment_reclassification_dismissal,
    normalize_transaction_updates,
    validate_transaction_confirmation,
)


router = APIRouter()


def normalize_transaction_labels(value: object) -> str | None:
    labels = []
    for raw in str(value or "").split(","):
        label = " ".join(raw.strip().casefold().replace("|", "").split())
        if label and label not in labels:
            labels.append(label)
    return f"|{'|'.join(labels)}|" if labels else None


def transaction_labels(value: str | None) -> list[str]:
    return [label for label in (value or "").strip("|").split("|") if label]


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


@router.post("/api/transactions/manual")
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


@router.get("/api/transactions")
def list_transactions(
    account_id: int | None = None,
    cursor: str | None = None,
    page_size: int = Query(default=200, alias="limit", ge=1, le=200),
    filters: TransactionFilter = Depends(transaction_filter_dependency),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    if account_id is not None and account_id not in filters.accounts:
        filters = filters.model_copy(update={"accounts": [*filters.accounts, account_id]})
    query = select(Transaction).where(*transaction_filter_conditions(filters)).order_by(Transaction.transaction_date.desc(), Transaction.id.desc())
    if cursor:
        try:
            cursor_date_raw, cursor_id_raw = cursor.rsplit(":", 1)
            cursor_date = date.fromisoformat(cursor_date_raw)
            cursor_id = int(cursor_id_raw)
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=400, detail="Invalid transaction cursor") from error
        query = query.where(
            or_(
                Transaction.transaction_date < cursor_date,
                and_(Transaction.transaction_date == cursor_date, Transaction.id < cursor_id),
            )
        )
    fetched_rows = list(db.scalars(query.limit(page_size + 1)).all())
    has_more = len(fetched_rows) > page_size
    rows = fetched_rows[:page_size]
    page_ids = [row.id for row in rows]
    account_ids = {row.account_id for row in rows}
    accounts = {
        account.id: account
        for account in db.scalars(select(Account).where(Account.id.in_(account_ids))).all()
    } if account_ids else {}
    allocations_by_transaction: dict[int, list[ExpenseAllocation]] = {}
    allocation_query = (
        select(ExpenseAllocation)
        .where(ExpenseAllocation.transaction_id.in_(page_ids))
        .order_by(ExpenseAllocation.allocation_date, ExpenseAllocation.id)
    )
    for allocation in db.scalars(allocation_query).all() if page_ids else []:
        allocations_by_transaction.setdefault(allocation.transaction_id, []).append(allocation)
    splits_by_transaction: dict[int, list[TransactionSplit]] = {}
    split_query = (
        select(TransactionSplit)
        .where(TransactionSplit.transaction_id.in_(page_ids))
        .order_by(TransactionSplit.id)
    )
    for split in db.scalars(split_query).all() if page_ids else []:
        splits_by_transaction.setdefault(split.transaction_id, []).append(split)
    refund_link_query = select(RefundLink).where(
        RefundLink.confirmed.is_(True),
        or_(
            RefundLink.expense_transaction_id.in_(page_ids),
            RefundLink.refund_transaction_id.in_(page_ids),
        ),
    )
    confirmed_refund_links = db.scalars(refund_link_query).all() if page_ids else []
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
    items = [
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
    next_cursor = None
    if has_more and rows:
        last_row = rows[-1]
        next_cursor = f"{last_row.transaction_date.isoformat()}:{last_row.id}"
    return {"items": items, "next_cursor": next_cursor}


@router.get("/api/transactions/ids")
def list_transaction_ids(
    account_id: int | None = None,
    filters: TransactionFilter = Depends(transaction_filter_dependency),
    session: SessionToken = Depends(current_session),
    db: Session = Depends(get_db),
):
    if account_id is not None and account_id not in filters.accounts:
        filters = filters.model_copy(update={"accounts": [*filters.accounts, account_id]})
    return list(db.scalars(select(Transaction.id).where(*transaction_filter_conditions(filters)).order_by(Transaction.id)).all())


@router.patch("/api/transactions/bulk-update")
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
        institution = upsert_institution_by_name(db, name)
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


@router.delete("/api/transactions/bulk-delete")
def bulk_delete_transactions(payload: BulkDeleteRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    require_delete_confirmation(payload.confirm_text)
    transactions = db.scalars(live_transaction_select(Transaction.id.in_(payload.ids))).all()
    if len(transactions) != len(set(payload.ids)):
        raise HTTPException(status_code=404, detail="One or more transactions were not found")
    operation_id = _soft_delete_transactions(db, transactions, actor_for_session(session))
    db.commit()
    return {"ok": True, "deleted": len(transactions), "operation_id": operation_id}


@router.post("/api/transactions/{transaction_id}/restore")
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


@router.post("/api/transactions/bulk-restore")
def restore_transactions(payload: BulkIdsRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    transactions = db.scalars(select(Transaction).where(Transaction.id.in_(payload.ids), Transaction.deleted_at.is_not(None))).all()
    if len(transactions) != len(set(payload.ids)):
        raise HTTPException(status_code=404, detail="One or more deleted transactions were not found")
    actor = actor_for_session(session)
    operation_id = _restore_transactions(db, transactions, actor)
    db.commit()
    return {"ok": True, "restored": len(transactions), "operation_id": operation_id}


@router.delete("/api/transactions/bulk-permanent-delete")
def permanently_delete_transactions(payload: BulkDeleteRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    require_delete_confirmation(payload.confirm_text)
    transactions = db.scalars(select(Transaction).where(Transaction.id.in_(payload.ids), Transaction.deleted_at.is_not(None))).all()
    if len(transactions) != len(set(payload.ids)):
        raise HTTPException(status_code=404, detail="One or more deleted transactions were not found")
    for transaction in transactions:
        _delete_transaction_row(db, transaction)
    db.commit()
    return {"ok": True, "deleted": len(transactions)}


@router.delete("/api/transactions/{transaction_id}/permanent")
def permanently_delete_transaction(transaction_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    require_delete_confirmation(payload.confirm_text)
    transaction = db.get(Transaction, transaction_id)
    if not transaction or transaction.deleted_at is None:
        raise HTTPException(status_code=404, detail="Deleted transaction not found")
    _delete_transaction_row(db, transaction)
    db.commit()
    return {"ok": True}


@router.patch("/api/transactions/{transaction_id}")
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


@router.post("/api/transactions/{transaction_id}/void")
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


@router.delete("/api/transactions/{transaction_id}")
def delete_transaction(transaction_id: int, payload: DeleteConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    require_delete_confirmation(payload.confirm_text)
    transaction = get_live_transaction(db, transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    operation_id = _soft_delete_transaction(db, transaction, actor_for_session(session))
    db.commit()
    return {"ok": True, "operation_id": operation_id}


@router.post("/api/transactions/{transaction_id}/splits")
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


@router.get("/api/transactions/{transaction_id}/splits")
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


@router.post("/api/transactions/{transaction_id}/monthly-allocation")
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


@router.delete("/api/transactions/{transaction_id}/monthly-allocation")
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
