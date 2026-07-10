from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AppUser, SessionToken


password_hasher = PasswordHasher()
_login_attempts: dict[str, tuple[int, datetime]] = {}


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bool(password_hasher.verify(password_hash, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def enforce_login_rate_limit(client_key: str) -> None:
    current = _login_attempts.get(client_key)
    if not current:
        return
    attempts, last_attempt = current
    if attempts >= settings.login_attempt_limit and (datetime.utcnow() - last_attempt).total_seconds() < settings.login_backoff_seconds:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")


def record_login_failure(client_key: str) -> None:
    attempts, _ = _login_attempts.get(client_key, (0, datetime.utcnow()))
    _login_attempts[client_key] = (attempts + 1, datetime.utcnow())


def clear_login_failures(client_key: str) -> None:
    _login_attempts.pop(client_key, None)


def create_session(db: Session, user_id: int) -> SessionToken:
    now = datetime.utcnow()
    session = SessionToken(
        user_id=user_id,
        session_token=secrets.token_urlsafe(32),
        csrf_token=secrets.token_urlsafe(24),
        last_seen_at=now,
        expires_at=now + timedelta(minutes=settings.idle_timeout_minutes),
    )
    db.add(session)
    db.flush()
    return session


def set_session_cookie(response: Response, session: SessionToken) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session.session_token,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=settings.idle_timeout_minutes * 60,
    )


def get_session_from_request(db: Session, request: Request) -> SessionToken:
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    session = db.scalar(select(SessionToken).where(SessionToken.session_token == token))
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    now = datetime.utcnow()
    if session.expires_at < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    if session.created_at + timedelta(hours=settings.absolute_session_hours) < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    session.last_seen_at = now
    session.expires_at = now + timedelta(minutes=settings.idle_timeout_minutes)
    return session


def purge_expired_sessions(db: Session) -> int:
    now = datetime.utcnow()
    absolute_cutoff = now - timedelta(hours=settings.absolute_session_hours)
    stale = db.scalars(
        select(SessionToken).where((SessionToken.expires_at < now) | (SessionToken.created_at < absolute_cutoff))
    ).all()
    for row in stale:
        db.delete(row)
    return len(stale)


def require_csrf(request: Request, session: SessionToken) -> None:
    supplied = request.headers.get(settings.csrf_header_name)
    if supplied != session.csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")


def ensure_setup_state(db: Session) -> bool:
    return db.scalar(select(AppUser.id).limit(1)) is not None

