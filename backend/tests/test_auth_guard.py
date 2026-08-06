"""
Auth-Guard Tests: Prüft, dass unauthentifizierte oder ungültige Requests
korrekt mit 401 Unauthorized abgelehnt werden.
"""

import uuid
from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.config import settings
from app.core.security import ALGORITHM


# ---------------------------------------------------------------------------
# 1) Kein Token → 401
# ---------------------------------------------------------------------------


def test_request_without_token_returns_401(client):
    """Request ohne Authorization-Header muss 401 zurückgeben."""
    fake_household_id = uuid.uuid4()
    resp = client.get(f"/api/households/{fake_household_id}/shopping-items/")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2) Ungültiger Token → 401
# ---------------------------------------------------------------------------


def test_request_with_invalid_token_returns_401(client):
    """Request mit komplett ungültigem Token muss 401 zurückgeben."""
    fake_household_id = uuid.uuid4()
    resp = client.get(
        f"/api/households/{fake_household_id}/shopping-items/",
        headers={"Authorization": "Bearer invalid_token_xyz"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3) Abgelaufener Token → 401
# ---------------------------------------------------------------------------


def test_request_with_expired_token_returns_401(client):
    """Request mit abgelaufenem Token muss 401 zurückgeben."""
    fake_household_id = uuid.uuid4()
    fake_user_id = str(uuid.uuid4())

    # Token mit exp in der Vergangenheit erzeugen
    expired_payload = {
        "sub": fake_user_id,
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    expired_token = jwt.encode(
        expired_payload, settings.jwt_secret_key, algorithm=ALGORITHM
    )

    resp = client.get(
        f"/api/households/{fake_household_id}/shopping-items/",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401
