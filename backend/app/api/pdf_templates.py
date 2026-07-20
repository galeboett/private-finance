from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..db import get_db
from ..models import SessionToken
from ..schemas import PdfInspectRequest, PdfTemplateCreate
from ..security import require_csrf
from ..services.pdf_teaching import delete_pdf_template, inspect_pdf_batch, list_pdf_templates, teach_pdf_template
from .dependencies import actor_for_session, current_session


router = APIRouter()


@router.post("/api/imports/pdf/inspect")
def inspect_pdf(payload: PdfInspectRequest, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    try:
        return inspect_pdf_batch(db, payload.staged_batch_id, payload.page)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/pdf-templates")
def create_pdf_template(payload: PdfTemplateCreate, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    actor = actor_for_session(session)
    try:
        template, operation_id = teach_pdf_template(db, payload, actor)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    record_audit_event(db, "pdf_template_teach", actor, "pdf_extraction_template", str(template["id"]), {"field": template["field"], "operation_id": operation_id})
    db.commit()
    return {"template": template, "operation_id": operation_id}


@router.get("/api/pdf-templates")
def get_pdf_templates(session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    return list_pdf_templates(db)


@router.delete("/api/pdf-templates/{template_id}")
def remove_pdf_template(template_id: int, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    actor = actor_for_session(session)
    try:
        operation_id = delete_pdf_template(db, template_id, actor)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    record_audit_event(db, "pdf_template_delete", actor, "pdf_extraction_template", str(template_id), {"operation_id": operation_id})
    db.commit()
    return {"ok": True, "operation_id": operation_id}
