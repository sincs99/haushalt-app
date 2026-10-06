"""Tests: Refresh-Token als HttpOnly-Cookie (H-01) und CSRF-Schutz.

Der Web-Client weist sich mit ``X-Requested-With: casa`` aus und erhält den
Refresh-Token nur als Cookie ``casa_rt``; Clients ohne Header (Swagger, native)
bekommen ihn wie bisher im Body. Refresh-Rotation, Grace-Window und
Reuse-Detection müssen über den Cookie-Pfad genauso funktionieren.
"""
from http.cookies import SimpleCookie
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.routers.auth import (
    CSRF_HEADER_NAME,
    CSRF_HEADER_VALUE,
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
)

WEB = {CSRF_HEADER_NAME: CSRF_HEADER_VALUE}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cookie(resp) -> SimpleCookie | None:
    """Parst den (einzigen) Set-Cookie-Header der Response."""
    raw = resp.headers.get("set-cookie")
    if raw is None:
        return None
    jar = SimpleCookie()
    jar.load(raw)
    return jar


def _refresh_morsel(resp):
    jar = _cookie(resp)
    assert jar is not None, "kein Set-Cookie-Header"
    assert REFRESH_COOKIE_NAME in jar, resp.headers.get("set-cookie")
    return jar[REFRESH_COOKIE_NAME]


def _assert_cleared(resp):
    morsel = _refresh_morsel(resp)
    assert morsel.value == ""
    assert morsel["max-age"] == "0"
    assert morsel["path"] == REFRESH_COOKIE_PATH


def _web_login(client, email="alice@example.com", password="password123"):
    resp = client.post(
        "/api/auth/login",
        data={"username": email, "password": password},
        headers=WEB,
    )
    assert resp.status_code == 200, resp.text
    return resp


def _set_cookie(client, value: str) -> None:
    """Simuliert den Cookie-Jar des Browsers (z. B. alten Wert aus zweitem Tab)."""
    client.cookies.set(REFRESH_COOKIE_NAME, value, path=REFRESH_COOKIE_PATH)


def _web_refresh(client, body: dict | None = None):
    return client.post("/api/auth/refresh", json=body if body is not None else {}, headers=WEB)


# ---------------------------------------------------------------------------
# 1) Login / Register setzen den Cookie
# ---------------------------------------------------------------------------


class TestCookieDelivery:
    def test_web_login_sets_httponly_cookie_and_omits_body_token(self, client, user_a):
        resp = _web_login(client)
        data = resp.json()

        assert data["access_token"]
        assert data["refresh_token"] is None, "Refresh-Token darf im Web-Build nicht im Body stehen"

        morsel = _refresh_morsel(resp)
        assert len(morsel.value) >= 32
        assert morsel["httponly"]
        assert morsel["path"] == REFRESH_COOKIE_PATH
        assert morsel["samesite"].lower() == "strict"
        assert int(morsel["max-age"]) == settings.refresh_token_expire_days * 24 * 3600
        # development (Tests): kein Secure, damit http://localhost funktioniert
        assert not morsel["secure"]

    def test_web_register_sets_cookie(self, client):
        resp = client.post(
            "/api/auth/register",
            json={
                "email": "cookie@example.com",
                "password": "securepass123",
                "display_name": "Cookie",
                "household_name": "Keks-WG",
            },
            headers=WEB,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["refresh_token"] is None
        assert _refresh_morsel(resp)["httponly"]

    def test_login_without_header_keeps_body_token_and_sets_no_cookie(self, client, user_a):
        """Abwärtskompatibel: Swagger-UI / native Clients ohne Cookie-Jar."""
        resp = client.post(
            "/api/auth/login", data={"username": "alice@example.com", "password": "password123"}
        )
        assert resp.status_code == 200
        assert resp.json()["refresh_token"]
        assert "set-cookie" not in resp.headers

    def test_cookie_is_secure_in_production(self, client, user_a):
        with patch.object(settings, "environment", "production"):
            resp = _web_login(client)
        assert _refresh_morsel(resp)["secure"]

    def test_secure_flag_can_be_overridden(self, client, user_a):
        with patch.object(settings, "environment", "production"), patch.object(
            settings, "auth_cookie_secure", False
        ):
            resp = _web_login(client)
        assert not _refresh_morsel(resp)["secure"]

        with patch.object(settings, "auth_cookie_secure", True):
            resp = _web_login(client)
        assert _refresh_morsel(resp)["secure"]

    def test_failed_login_sets_no_cookie(self, client, user_a):
        resp = client.post(
            "/api/auth/login", data={"username": "alice@example.com", "password": "wrong"}, headers=WEB
        )
        assert resp.status_code == 401
        assert "set-cookie" not in resp.headers


# ---------------------------------------------------------------------------
# 2) Refresh über den Cookie
# ---------------------------------------------------------------------------


class TestCookieRefresh:
    def test_refresh_with_cookie_rotates_and_sets_new_cookie(self, client, user_a):
        old_value = _refresh_morsel(_web_login(client)).value

        resp = _web_refresh(client)
        assert resp.status_code == 200, resp.text
        assert resp.json()["access_token"]
        assert resp.json()["refresh_token"] is None

        new_value = _refresh_morsel(resp).value
        assert new_value != old_value
        assert client.cookies.get(REFRESH_COOKIE_NAME) == new_value

        # Alter Wert ist rotiert (Grace-Window aus) → 401
        _set_cookie(client, old_value)
        with patch.object(settings, "refresh_token_reuse_grace_seconds", 0):
            resp2 = _web_refresh(client)
        assert resp2.status_code == 401

    def test_refresh_with_empty_body_uses_cookie(self, client, user_a):
        _web_login(client)
        resp = client.post("/api/auth/refresh", headers=WEB)  # gar kein Body
        assert resp.status_code == 200, resp.text

    def test_refresh_cookie_without_csrf_header_is_rejected_and_token_untouched(self, client, user_a):
        value = _refresh_morsel(_web_login(client)).value

        resp = client.post("/api/auth/refresh", json={})  # Cookie im Jar, aber kein Header
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == ErrorCode.CSRF_HEADER_MISSING
        assert "set-cookie" not in resp.headers

        # Token wurde nicht rotiert/revoked → funktioniert weiterhin
        assert client.cookies.get(REFRESH_COOKIE_NAME) == value
        assert _web_refresh(client).status_code == 200

    def test_wrong_csrf_header_value_is_rejected(self, client, user_a):
        _web_login(client)
        resp = client.post("/api/auth/refresh", json={}, headers={CSRF_HEADER_NAME: "XMLHttpRequest"})
        assert resp.status_code == 403

    def test_refresh_without_any_token_is_401(self, client, user_a):
        resp = _web_refresh(client)
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == ErrorCode.REFRESH_TOKEN_INVALID
        assert "set-cookie" not in resp.headers

    def test_invalid_cookie_is_cleared(self, client, user_a):
        _set_cookie(client, "not-a-real-token")
        resp = _web_refresh(client)
        assert resp.status_code == 401
        assert resp.json()["detail"]["code"] == ErrorCode.REFRESH_TOKEN_INVALID
        _assert_cleared(resp)

    def test_body_refresh_still_works_without_cookie(self, client, user_a):
        """Native Clients: Token im Body, Antwort im Body, kein Cookie."""
        login = client.post(
            "/api/auth/login", data={"username": "alice@example.com", "password": "password123"}
        )
        resp = client.post("/api/auth/refresh", json={"refresh_token": login.json()["refresh_token"]})
        assert resp.status_code == 200
        assert resp.json()["refresh_token"]
        assert "set-cookie" not in resp.headers

    def test_legacy_body_token_with_header_migrates_to_cookie(self, client, user_a):
        """Einmalige Migration: alter localStorage-Token im Body + Web-Header → Cookie."""
        login = client.post(
            "/api/auth/login", data={"username": "alice@example.com", "password": "password123"}
        )
        legacy = login.json()["refresh_token"]

        resp = client.post("/api/auth/refresh", json={"refresh_token": legacy}, headers=WEB)
        assert resp.status_code == 200, resp.text
        assert resp.json()["refresh_token"] is None
        morsel = _refresh_morsel(resp)
        assert morsel["httponly"] and morsel.value != legacy

        # Danach läuft Refresh allein über den Cookie
        assert _web_refresh(client).status_code == 200

    def test_body_token_takes_precedence_over_cookie(self, client, user_a, user_b):
        """Body hat Vorrang: Bobs Token im Body rotiert Bobs Session, nicht Alices Cookie."""
        alice_cookie = _refresh_morsel(_web_login(client)).value
        bob_login = client.post(
            "/api/auth/login", data={"username": "bob@example.com", "password": "password456"}
        )
        bob_token = bob_login.json()["refresh_token"]

        resp = client.post("/api/auth/refresh", json={"refresh_token": bob_token}, headers=WEB)
        assert resp.status_code == 200
        # Alices Cookie-Token ist unberührt und weiterhin gültig
        _set_cookie(client, alice_cookie)
        with patch.object(settings, "refresh_token_reuse_grace_seconds", 0):
            assert _web_refresh(client).status_code == 200


# ---------------------------------------------------------------------------
# 3) Rotation, Grace-Window, Reuse-Detection über Cookies
# ---------------------------------------------------------------------------


class TestCookieRotationSafety:
    def test_grace_window_allows_second_tab(self, client, user_a):
        token_a = _refresh_morsel(_web_login(client)).value

        resp_b = _web_refresh(client)
        assert resp_b.status_code == 200
        token_b = _refresh_morsel(resp_b).value

        # Zweiter Tab schickt noch den alten Cookie-Wert (innerhalb Grace-Window)
        _set_cookie(client, token_a)
        resp_c = _web_refresh(client)
        assert resp_c.status_code == 200, resp_c.text
        token_c = _refresh_morsel(resp_c).value
        assert token_c not in (token_a, token_b)

        _set_cookie(client, token_b)
        with patch.object(settings, "refresh_token_reuse_grace_seconds", 0):
            assert _web_refresh(client).status_code == 401

    def test_reuse_detection_revokes_all_and_clears_cookie(self, client, user_a):
        """Gestohlener (bereits rotierter) Cookie → 401 REUSED, alle Sessions des Users weg."""
        token_a = _refresh_morsel(_web_login(client)).value
        resp_b = _web_refresh(client)
        token_b = _refresh_morsel(resp_b).value

        _set_cookie(client, token_a)
        with patch.object(settings, "refresh_token_reuse_grace_seconds", 0):
            resp_reuse = _web_refresh(client)
        assert resp_reuse.status_code == 401
        assert resp_reuse.json()["detail"]["code"] == ErrorCode.REFRESH_TOKEN_REUSED
        _assert_cleared(resp_reuse)

        _set_cookie(client, token_b)
        resp_b2 = _web_refresh(client)
        assert resp_b2.status_code == 401
        _assert_cleared(resp_b2)


# ---------------------------------------------------------------------------
# 4) Logout
# ---------------------------------------------------------------------------


class TestCookieLogout:
    def test_logout_revokes_cookie_token_and_clears_cookie(self, client, user_a):
        value = _refresh_morsel(_web_login(client)).value

        resp = client.post("/api/auth/logout", json={}, headers=WEB)
        assert resp.status_code == 204
        _assert_cleared(resp)
        assert not client.cookies.get(REFRESH_COOKIE_NAME)

        # Serverseitig revoked → Refresh mit dem alten Wert schlägt fehl
        _set_cookie(client, value)
        assert _web_refresh(client).status_code == 401

    def test_logout_without_body_uses_cookie(self, client, user_a):
        _web_login(client)
        resp = client.post("/api/auth/logout", headers=WEB)
        assert resp.status_code == 204
        _assert_cleared(resp)

    def test_logout_cookie_without_csrf_header_is_rejected(self, client, user_a):
        _web_login(client)
        resp = client.post("/api/auth/logout", json={})
        assert resp.status_code == 403
        assert "set-cookie" not in resp.headers
        # Session lebt weiter
        assert _web_refresh(client).status_code == 200

    def test_logout_without_cookie_is_idempotent(self, client, user_a):
        resp = client.post("/api/auth/logout", json={}, headers=WEB)
        assert resp.status_code == 204
        _assert_cleared(resp)  # Web-Client bekommt den Lösch-Cookie trotzdem (harmlos)

    def test_body_logout_without_header_still_works(self, client, user_a):
        login = client.post(
            "/api/auth/login", data={"username": "alice@example.com", "password": "password123"}
        )
        token = login.json()["refresh_token"]
        resp = client.post("/api/auth/logout", json={"refresh_token": token})
        assert resp.status_code == 204
        assert "set-cookie" not in resp.headers
        assert client.post("/api/auth/refresh", json={"refresh_token": token}).status_code == 401


# ---------------------------------------------------------------------------
# 5) Access-Token bleibt im Body / Authorization-Header
# ---------------------------------------------------------------------------


def test_access_token_from_cookie_flow_authenticates(client, user_a):
    access = _web_login(client).json()["access_token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == "alice@example.com"


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/auth/refresh", "/api/auth/logout"])
def test_auth_cookie_responses_are_no_store(client, user_a, path):
    """Cookie-Responses dürfen nicht gecacht werden (Security-Header-Middleware)."""
    if path == "/api/auth/login":
        resp = _web_login(client)
    else:
        _web_login(client)
        resp = client.post(path, json={}, headers=WEB)
    assert resp.headers["cache-control"] == "no-store"
