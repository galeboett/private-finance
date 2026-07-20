from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.middleware import LocalhostSecurityMiddleware
from app.models import SessionToken
from app.security import require_recent_reauthentication


def test_sensitive_action_requires_password_within_five_minutes():
    recent = SessionToken(reauthenticated_at=datetime.utcnow())
    require_recent_reauthentication(recent)

    stale = SessionToken(reauthenticated_at=datetime.utcnow() - timedelta(minutes=6))
    with pytest.raises(HTTPException) as error:
        require_recent_reauthentication(stale)
    assert error.value.status_code == 403


def test_security_headers_are_added_to_responses():
    app = FastAPI()
    app.add_middleware(LocalhostSecurityMiddleware)

    @app.get("/ok")
    def ok():
        return {"ok": True}

    response = TestClient(app).get("/ok", headers={"host": "localhost"})
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
