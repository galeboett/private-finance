from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..audit import record_audit_event
from ..config import settings
from ..db import get_db
from ..models import AppUser, Category, SessionToken
from ..schemas import LoginRequest, PasswordChangeRequest, ReauthenticationRequest, SetupRequest
from ..security import (
    clear_login_failures,
    create_session,
    enforce_login_rate_limit,
    ensure_setup_state,
    hash_password,
    password_needs_rehash,
    purge_expired_sessions,
    reauthenticate_session,
    record_login_failure,
    require_csrf,
    set_session_cookie,
    verify_password,
)
from ..services.snapshots import net_worth_unanchored_accounts
from .dependencies import current_session


router = APIRouter()


@router.get("/api/health")
def health(db: Session = Depends(get_db)):
    return {"ok": True, "configured": ensure_setup_state(db)}


@router.post("/api/setup")
def setup(request: SetupRequest, db: Session = Depends(get_db)):
    if ensure_setup_state(db):
        raise HTTPException(status_code=400, detail="Application already set up")
    user = AppUser(password_hash=hash_password(request.password))
    db.add(user)
    db.commit()
    record_audit_event(db, "setup", "system", "app_user", str(user.id), {"message": "Initial password created"})
    db.commit()
    return {"ok": True}


@router.post("/api/login")
def login(payload: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    client_key = request.client.host if request.client else "localhost"
    enforce_login_rate_limit(client_key)
    user = db.scalar(select(AppUser).limit(1))
    if not user or not verify_password(payload.password, user.password_hash):
        record_login_failure(client_key)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    clear_login_failures(client_key)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    purge_expired_sessions(db)
    session = create_session(db, user.id)
    db.commit()
    set_session_cookie(response, request, session)
    record_audit_event(db, "login", "local-user", "session", str(session.id), {"message": "Login successful"})
    db.commit()
    return {"ok": True, "csrf_token": session.csrf_token}


@router.post("/api/logout")
def logout(request: Request, response: Response, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    db.execute(delete(SessionToken).where(SessionToken.id == session.id))
    record_audit_event(db, "logout", "local-user", "session", str(session.id), {"message": "Logout"})
    db.commit()
    response.delete_cookie(settings.session_cookie_name)
    return {"ok": True}


@router.post("/api/password")
def change_password(payload: PasswordChangeRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    user = db.get(AppUser, session.user_id)
    if not user or not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    user.password_version += 1
    session.reauthenticated_at = datetime.utcnow()
    db.execute(delete(SessionToken).where(SessionToken.user_id == user.id, SessionToken.id != session.id))
    record_audit_event(db, "password_change", "local-user", "app_user", str(user.id), {"password_version": user.password_version})
    db.commit()
    return {"ok": True}


@router.post("/api/reauthenticate")
def reauthenticate(payload: ReauthenticationRequest, request: Request, session: SessionToken = Depends(current_session), db: Session = Depends(get_db)):
    require_csrf(request, session)
    reauthenticate_session(db, session, payload.password)
    record_audit_event(db, "reauthenticate", "local-user", "session", str(session.id), {"message": "Sensitive action authorized"})
    db.commit()
    return {"ok": True, "valid_for_seconds": settings.reauthentication_minutes * 60}


@router.get("/api/bootstrap")
def bootstrap_state(db: Session = Depends(get_db)):
    return {
        "configured": ensure_setup_state(db),
        "categories": [
            {"id": category.id, "key": category.key, "label": category.label, "parent_id": category.parent_id}
            for category in db.scalars(select(Category).order_by(Category.label.asc())).all()
        ],
        "net_worth_notice": net_worth_unanchored_accounts(db),
    }


@router.get("/api/me")
def me(session: SessionToken = Depends(current_session)):
    return {"ok": True, "csrf_token": session.csrf_token}
