"""Tests für Refresh-Token-Rotation, Reuse-Detection und Logout.

Epic 12 — Token Persistence & Auth Lifecycle.
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.security import ALGORITHM
from app.models import RefreshToken


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client, email: str = "alice@example.com", password: str = "password123") -> dict:
    """Führt Login durch und gibt die Response-JSON zurück."""
    resp = client.post("/api/auth/login", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _refresh(client, refresh_token: str):
    """Ruft den Refresh-Endpoint auf und gibt die raw Response zurück."""
    return client.post("/api/auth/refresh", json={"refresh_token": refresh_token})


def _logout(client, refresh_token: str):
    """Ruft den Logout-Endpoint auf und gibt die raw Response zurück."""
    return client.post("/api/auth/logout", json={"refresh_token": refresh_token})


# ---------------------------------------------------------------------------
# 1) Login gibt beide Tokens zurück
# ---------------------------------------------------------------------------


def test_login_returns_both_tokens(client, user_a):
    """POST /api/auth/login → response hat access_token, refresh_token, expires_in."""
    data = _login(client)

    assert "access_token" in data
    assert "refresh_token" in data
    assert "expires_in" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == settings.access_token_expire_minutes * 60


# ---------------------------------------------------------------------------
# 2) Refresh rotiert Tokens
# ---------------------------------------------------------------------------


def test_refresh_rotates_tokens(client, user_a):
    """Login → refresh → neues Paar, alter Token ist danach ungültig."""
    login_data = _login(client)
    old_refresh = login_data["refresh_token"]

    # Refresh mit dem Token
    resp = _refresh(client, old_refresh)
    assert resp.status_code == 200
    new_data = resp.json()

    assert "access_token" in new_data
    assert "refresh_token" in new_data
    assert new_data["refresh_token"] != old_refresh

    # Alter Refresh-Token ist jetzt ungültig
    resp2 = _refresh(client, old_refresh)
    assert resp2.status_code == 401


# ---------------------------------------------------------------------------
# 3) Reuse-Detection revoked die gesamte Kette
# ---------------------------------------------------------------------------


def test_reuse_detection_revokes_chain(client, user_a):
    """Login → refresh (Token B) → refresh mit altem Token A → 401 REUSED.
    Danach ist auch Token B revoked."""
    login_data = _login(client)
    token_a = login_data["refresh_token"]

    # Refresh → Token B
    resp_b = _refresh(client, token_a)
    assert resp_b.status_code == 200
    token_b = resp_b.json()["refresh_token"]

    # Reuse: versuche refresh mit dem ALTEN Token A
    resp_reuse = _refresh(client, token_a)
    assert resp_reuse.status_code == 401
    assert resp_reuse.json()["detail"]["code"] == ErrorCode.REFRESH_TOKEN_REUSED

    # Token B ist jetzt auch revoked (gesamte Kette)
    resp_b2 = _refresh(client, token_b)
    assert resp_b2.status_code == 401


# ---------------------------------------------------------------------------
# 4) Logout revoked den Token
# ---------------------------------------------------------------------------


def test_logout_revokes_token(client, user_a):
    """Login → logout → refresh mit dem Token → 401."""
    login_data = _login(client)
    refresh_token = login_data["refresh_token"]

    # Logout
    resp = _logout(client, refresh_token)
    assert resp.status_code == 204

    # Refresh schlägt fehl
    resp2 = _refresh(client, refresh_token)
    assert resp2.status_code == 401


# ---------------------------------------------------------------------------
# 5) Logout ist idempotent
# ---------------------------------------------------------------------------


def test_logout_idempotent(client, user_a):
    """Login → logout → nochmal logout mit demselben Token → 204."""
    login_data = _login(client)
    refresh_token = login_data["refresh_token"]

    resp1 = _logout(client, refresh_token)
    assert resp1.status_code == 204

    resp2 = _logout(client, refresh_token)
    assert resp2.status_code == 204


# ---------------------------------------------------------------------------
# 6) Abgelaufener Access-Token → 401
# ---------------------------------------------------------------------------


def test_expired_access_token_returns_401(client, user_a, household_a):
    """Access-Token mit Expiry in der Vergangenheit → 401 auf geschütztem Endpoint."""
    expired_payload = {
        "sub": str(user_a.id),
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }
    expired_token = jwt.encode(
        expired_payload, settings.jwt_secret_key, algorithm=ALGORITHM
    )

    resp = client.get(
        f"/api/households/{household_a.id}/shopping-items/",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 7) Register gibt beide Tokens zurück
# ---------------------------------------------------------------------------


def test_register_returns_both_tokens(client):
    """POST /api/auth/register → response hat access_token, refresh_token, expires_in."""
    resp = client.post("/api/auth/register", json={
        "email": "newuser@example.com",
        "password": "securepass123",
        "display_name": "New User",
        "household_name": "Neuer Haushalt",
    })
    assert resp.status_code == 200
    data = resp.json()

    assert "access_token" in data
    assert "refresh_token" in data
    assert "expires_in" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == settings.access_token_expire_minutes * 60
