"""Tests für Refresh-Token-Rotation, Reuse-Detection und Logout.

Epic 12 — Token Persistence & Auth Lifecycle.
Epic 12b — Auth Hardening: Grace Window, Rate Limiting, JWT Check, Cleanup.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.security import ALGORITHM, hash_refresh_token
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
    """Login → refresh → neues Paar, alter Token ist danach ungültig (ohne Grace Window)."""
    login_data = _login(client)
    old_refresh = login_data["refresh_token"]

    # Refresh mit dem Token
    resp = _refresh(client, old_refresh)
    assert resp.status_code == 200
    new_data = resp.json()

    assert "access_token" in new_data
    assert "refresh_token" in new_data
    assert new_data["refresh_token"] != old_refresh

    # Alter Refresh-Token ist jetzt ungültig (Grace Window deaktiviert)
    with patch.object(settings, "refresh_token_reuse_grace_seconds", 0):
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

    # Reuse: versuche refresh mit dem ALTEN Token A (Grace Window deaktiviert)
    with patch.object(settings, "refresh_token_reuse_grace_seconds", 0):
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

    # Refresh schlägt fehl (kein replaced_by_id → kein Grace Window)
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


# ---------------------------------------------------------------------------
# 8) Grace Window erlaubt zweiten Tab Refresh
# ---------------------------------------------------------------------------


def test_grace_window_allows_second_tab_refresh(client, user_a):
    """Login → refresh (Token B) → refresh mit altem Token A innerhalb 30s
    → Sollte NICHT 401 REUSED sein, sondern ein neues Token-Paar (Token C)."""
    login_data = _login(client)
    token_a = login_data["refresh_token"]

    # Refresh → Token B
    resp_b = _refresh(client, token_a)
    assert resp_b.status_code == 200
    token_b = resp_b.json()["refresh_token"]

    # Zweiter Tab: refresh mit altem Token A (innerhalb Grace Window)
    resp_c = _refresh(client, token_a)
    assert resp_c.status_code == 200, f"Expected 200, got {resp_c.status_code}: {resp_c.text}"
    token_c = resp_c.json()["refresh_token"]

    # Token C ist verschieden von A und B
    assert token_c != token_a
    assert token_c != token_b

    # Token B ist jetzt revoked — Prüfung ohne Grace Window
    with patch.object(settings, "refresh_token_reuse_grace_seconds", 0):
        resp_b2 = _refresh(client, token_b)
    assert resp_b2.status_code == 401


# ---------------------------------------------------------------------------
# 9) Grace Window abgelaufen → Reuse-Detection
# ---------------------------------------------------------------------------


def test_grace_window_expired_triggers_reuse_detection(client, user_a):
    """Login → refresh (Token B) → Warte/Patche bis Grace abgelaufen (>30s)
    → Refresh mit altem Token A → 401 REFRESH_TOKEN_REUSED
    → Token B auch revoked."""
    login_data = _login(client)
    token_a = login_data["refresh_token"]

    # Refresh → Token B
    resp_b = _refresh(client, token_a)
    assert resp_b.status_code == 200
    token_b = resp_b.json()["refresh_token"]

    # Grace Window auf 0 Sekunden setzen → sofort abgelaufen
    with patch.object(settings, "refresh_token_reuse_grace_seconds", 0):
        resp_reuse = _refresh(client, token_a)
    assert resp_reuse.status_code == 401
    assert resp_reuse.json()["detail"]["code"] == ErrorCode.REFRESH_TOKEN_REUSED

    # Token B ist jetzt auch revoked (gesamte Kette)
    resp_b2 = _refresh(client, token_b)
    assert resp_b2.status_code == 401


# ---------------------------------------------------------------------------
# 10) Rate Limit auf Login
# ---------------------------------------------------------------------------


def test_rate_limit_login(client, user_a):
    """6 Login-Versuche → 6. gibt 429."""
    from app.core.rate_limit import limiter

    limiter.enabled = True
    try:
        for i in range(5):
            resp = client.post("/api/auth/login", data={
                "username": "alice@example.com",
                "password": "password123",
            })
            # Erste 5 sollten durchkommen (200 oder 401, nicht 429)
            assert resp.status_code != 429, f"Request {i+1} was rate-limited unexpectedly"

        # 6. Versuch → 429
        resp = client.post("/api/auth/login", data={
            "username": "alice@example.com",
            "password": "password123",
        })
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == ErrorCode.RATE_LIMITED
    finally:
        limiter.enabled = False


# ---------------------------------------------------------------------------
# 11) JWT Secret Placeholder → RuntimeError
# ---------------------------------------------------------------------------


def test_jwt_secret_placeholder_raises():
    """Startup-Check: JWT_SECRET_KEY = Placeholder → RuntimeError."""
    from app.main import lifespan, app as real_app

    with patch.object(settings, "jwt_secret_key", "please-change-this-secret-in-production-min-32-chars"):
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY is insecure"):
            async def _run():
                async with lifespan(real_app):
                    pass  # pragma: no cover

            asyncio.run(_run())


def test_jwt_secret_too_short_raises():
    """Startup-Check: JWT_SECRET_KEY < 32 Zeichen → RuntimeError."""
    from app.main import lifespan, app as real_app

    with patch.object(settings, "jwt_secret_key", "short"):
        with pytest.raises(RuntimeError, match="JWT_SECRET_KEY is insecure"):
            async def _run():
                async with lifespan(real_app):
                    pass  # pragma: no cover

            asyncio.run(_run())


# ---------------------------------------------------------------------------
# 12) Lazy Cleanup entfernt alte Tokens
# ---------------------------------------------------------------------------


def test_lazy_cleanup_removes_old_tokens(client, user_a, db):
    """Login → Erstelle manuell expired/revoked Tokens → Refresh → alte Tokens gelöscht."""
    login_data = _login(client)
    refresh_token = login_data["refresh_token"]

    # Manuell abgelaufene und lang-revozierte Tokens erstellen
    expired_rt = RefreshToken(
        user_id=user_a.id,
        token_hash="expired_hash_test_123",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    old_revoked_rt = RefreshToken(
        user_id=user_a.id,
        token_hash="revoked_hash_test_456",
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        revoked_at=datetime.now(timezone.utc) - timedelta(days=8),
    )
    db.add_all([expired_rt, old_revoked_rt])
    db.commit()

    # Prüfe dass die Tokens existieren
    count_before = db.query(RefreshToken).filter_by(user_id=user_a.id).count()
    assert count_before >= 3  # login-token + 2 manuell erstellte

    # Refresh → löst Cleanup aus
    resp = _refresh(client, refresh_token)
    assert resp.status_code == 200

    # Nach Cleanup: expired und lang-revoked Tokens sollten weg sein
    remaining_hashes = [
        rt.token_hash
        for rt in db.query(RefreshToken).filter_by(user_id=user_a.id).all()
    ]
    assert "expired_hash_test_123" not in remaining_hashes
    assert "revoked_hash_test_456" not in remaining_hashes
