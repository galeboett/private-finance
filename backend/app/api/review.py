from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..db import get_db
from ..models import RefundLink, SessionToken, Transaction, TransferLink
from ..schemas import BulkDuplicateResolutionRequest, DuplicateResolutionRequest, DuplicateSelectionPreviewRequest, DuplicateSelectionResolutionRequest, ExternalPaymentRequest, HistoricalRefundBulkRequest, PaymentVerificationDismissRequest, RefundConfirmRequest, RefundLinkCreate, RefundNoExpenseRequest, RefundSelectionRequest, TransactionType, TransferLinkCreate
from ..security import require_csrf
from ..services.duplicate_scan import scan_ledger_duplicates
from ..services.duplicates import duplicate_queue_summary, link_historical_refund_pairs, pending_duplicate_pairs, preview_duplicate_selection, preview_historical_refund_links, preview_safe_duplicate_resolution, resolve_all_exact_duplicates, resolve_duplicate, resolve_duplicate_selection, resolve_safe_duplicate_reimports
from ..services.mutation_log import MutationChange, full_values, journal_mutation
from ..services.refunds import OverRefundError, confirm_refund_link, confirm_refund_selections, create_manual_refund_link, create_refund_suggestions, delete_refund_link, list_manual_refund_candidates, list_refund_links, list_refund_suggestion_groups, reject_refund_candidates, reject_refund_link, resolve_refunds_without_expense
from ..services.transaction_queries import live_transaction_select
from ..services.transfers import confirm_transfer_link, create_transfer_suggestions, dismiss_payment_verification, list_payment_verification, list_unconfirmed_transfers, reject_transfer_link, settle_payment_from_external
from .dependencies import actor_for_session, current_session


router = APIRouter()


@router.get("/api/review")
def review_inbox(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    rows = db.scalars(
        live_transaction_select(
            or_(
                Transaction.review_status.in_(["needs_review", "suggested", "possible_duplicate"]),
                and_(Transaction.transaction_type == TransactionType.REFUND.value, Transaction.category_id.is_(None)),
            ),
        )
    ).all()
    return [{"id": row.id, "description": row.raw_description, "amount_cents": row.amount_cents, "transaction_type": row.transaction_type, "review_status": row.review_status, "date": row.transaction_date.isoformat(), "duplicate_of_transaction_id": row.duplicate_of_transaction_id} for row in rows]


@router.get("/api/duplicates/pending")
def list_pending_duplicates(limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0), tier: Literal["exact", "cross_source", "probable", "mirrored", "import"] | None = None, account_id: int | None = Query(default=None, ge=1), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return pending_duplicate_pairs(db, limit=limit, offset=offset, tier_filter=tier, account_id=account_id)


@router.get("/api/duplicates/summary")
def get_duplicate_queue_summary(account_id: int | None = Query(default=None, ge=1), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return duplicate_queue_summary(db, account_id=account_id)


@router.get("/api/duplicates/bulk-preview")
def get_duplicate_bulk_preview(strategy: Literal["keep_existing", "use_new_import"], session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return preview_safe_duplicate_resolution(db, strategy=strategy)


@router.post("/api/duplicates/resolve-safe")
def resolve_safe_duplicates(payload: BulkDuplicateResolutionRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        result = resolve_safe_duplicate_reimports(db, strategy=payload.strategy, preview_token=payload.preview_token, actor=actor_for_session(session))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.get("/api/duplicates/historical-refunds-preview")
def get_historical_refund_bulk_preview(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return preview_historical_refund_links(db)


@router.post("/api/duplicates/link-historical-refunds")
def link_historical_refunds(payload: HistoricalRefundBulkRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        result = link_historical_refund_pairs(db, preview_token=payload.preview_token, actor=actor_for_session(session))
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.post("/api/duplicates/selection-preview")
def get_duplicate_selection_preview(payload: DuplicateSelectionPreviewRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return preview_duplicate_selection(db, transaction_ids=payload.transaction_ids, action=payload.action, authoritative_batch_id=payload.authoritative_batch_id)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/duplicates/resolve-selection")
def resolve_selected_duplicates(payload: DuplicateSelectionResolutionRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        result = resolve_duplicate_selection(db, transaction_ids=payload.transaction_ids, action=payload.action, preview_token=payload.preview_token, actor=actor_for_session(session), authoritative_batch_id=payload.authoritative_batch_id)
    except (LookupError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.get("/api/duplicates/scan/results")
def ledger_duplicate_scan_results(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return pending_duplicate_pairs(db, limit=25)


@router.post("/api/duplicates/scan")
def scan_duplicates(request: Request, account_id: int | None = Query(default=None, ge=1), session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    result = scan_ledger_duplicates(db, actor=actor_for_session(session), account_id=account_id)
    db.commit()
    return {**result, "queue": duplicate_queue_summary(db, account_id=account_id)}


@router.post("/api/duplicates/resolve-exact")
def resolve_exact_duplicates(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    result = resolve_all_exact_duplicates(db, actor=actor_for_session(session))
    db.commit()
    return result


@router.post("/api/duplicates/{transaction_id}/resolve")
def resolve_pending_duplicate(transaction_id: int, payload: DuplicateResolutionRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        result = resolve_duplicate(db, transaction_id=transaction_id, action=payload.action, actor=actor_for_session(session))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    db.commit()
    return result


@router.post("/api/transfer-links")
def create_transfer_link(payload: TransferLinkCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = TransferLink(**payload.model_dump())
    db.add(link)
    db.flush()
    operation_id = journal_mutation(db, kind="create", entity_type="transfer_link", actor=actor_for_session(session), description="Created transfer link", changes=[MutationChange(link.id, None, full_values(link))])
    record_audit_event(db, "transfer_link_create", "local-user", "transfer_link", str(link.id), payload.model_dump())
    db.commit()
    return {"id": link.id, "operation_id": operation_id}


@router.get("/api/transfers/unconfirmed")
def get_unconfirmed_transfers(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_unconfirmed_transfers(db)


@router.get("/api/transfers/payments")
def get_payment_verification(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_payment_verification(db)


@router.post("/api/transfers/payments/{transaction_id}/dismiss")
def dismiss_payment_warning(transaction_id: int, payload: PaymentVerificationDismissRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return dismiss_payment_verification(db, transaction_id=transaction_id, reason=payload.reason, actor=actor_for_session(session))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/transfers/payments/{transaction_id}/external")
def settle_external_payment(transaction_id: int, payload: ExternalPaymentRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return settle_payment_from_external(db, transaction_id=transaction_id, external_account_id=payload.external_account_id, external_account_name=payload.external_account_name, actor=actor_for_session(session))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/transfers/detect")
def detect_transfers(request: Request, window_days: int = 5, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    if window_days < 1 or window_days > 30:
        raise HTTPException(status_code=400, detail="Transfer matching window must be between 1 and 30 days")
    return create_transfer_suggestions(db, window_days=window_days)


@router.post("/api/transfers/{link_id}/confirm")
def confirm_transfer(link_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = db.get(TransferLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Transfer candidate not found")
    try:
        return confirm_transfer_link(db, link)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/transfers/{link_id}/reject")
def reject_transfer(link_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = db.get(TransferLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Transfer candidate not found")
    return reject_transfer_link(db, link)


@router.get("/api/refunds/suggestions")
def get_refund_suggestions(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_refund_suggestion_groups(db)


@router.get("/api/refunds/expenses/{expense_transaction_id}")
def get_expense_refunds(expense_transaction_id: int, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_refund_links(db, confirmed=True, expense_transaction_id=expense_transaction_id)


@router.get("/api/refunds/candidates")
def get_refund_candidates(expense_transaction_id: int, search: str | None = None, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    try:
        return list_manual_refund_candidates(db, expense_transaction_id=expense_transaction_id, search=search)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/refunds/detect")
def detect_refunds(request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    return create_refund_suggestions(db, actor=actor_for_session(session))


@router.post("/api/refunds/confirm-selection")
def confirm_refund_selection(payload: RefundSelectionRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    selections = [(row.refund_transaction_id, row.expense_transaction_id) for row in payload.selections]
    try:
        return confirm_refund_selections(db, selections=selections, allow_over_refund=payload.allow_over_refund, actor=actor_for_session(session))
    except OverRefundError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/refunds/reject-candidates")
def reject_refund_candidate_selection(payload: RefundSelectionRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return reject_refund_candidates(db, selections=[(row.refund_transaction_id, row.expense_transaction_id) for row in payload.selections], actor=actor_for_session(session))
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/refunds/no-expense")
def settle_refunds_without_expense(payload: RefundNoExpenseRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return resolve_refunds_without_expense(db, refund_ids=payload.refund_transaction_ids, actor=actor_for_session(session))
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/refund-links")
def create_refund_link(payload: RefundLinkCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    try:
        return create_manual_refund_link(db, **payload.model_dump(), actor=actor_for_session(session))
    except OverRefundError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/refunds/{link_id}/confirm")
def confirm_refund(link_id: int, payload: RefundConfirmRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = db.get(RefundLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Refund candidate not found")
    try:
        return confirm_refund_link(db, link, allow_over_refund=payload.allow_over_refund, actor=actor_for_session(session))
    except OverRefundError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/refunds/{link_id}/reject")
def reject_refund(link_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = db.get(RefundLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Refund candidate not found")
    return reject_refund_link(db, link, actor=actor_for_session(session))


@router.delete("/api/refunds/{link_id}")
def unlink_refund(link_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    link = db.get(RefundLink, link_id)
    if not link:
        raise HTTPException(status_code=404, detail="Refund link not found")
    return delete_refund_link(db, link, actor=actor_for_session(session))
