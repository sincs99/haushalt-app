"""Tests: Security-Hardening — HTTP-Header, CORS, Rate-Limits, JWT-Claims, Login-Timing.

Siehe docs/security/hardening-review.md.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import ALGORITHM, decode_access_token

ORIGIN = "http://localhost:5173"


# ---------------------------------------------------------------------------
# 1) Security-Header
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    def test_api_response_has_security_headers(self, client):
        resp = client.get("/api/health")
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert resp.headers["referrer-policy"] == "no-referrer"
        assert resp.headers["cross-origin-opener-policy"] == "same-origin"
        assert "camera=()" in resp.headers["permissions-policy"]
        assert resp.headers["content-security-policy"].startswith("default-src 'none'")

    def test_error_response_has_security_headers(self, client):
        """Auch 401/404 tragen die Header (Middleware sitzt ausserhalb der Router)."""
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert "content-security-policy" in resp.headers

    def test_docs_have_no_api_csp(self, client):
        """Swagger-UI lädt Skripte vom CDN — die API-CSP würde sie blockieren."""
        resp = client.get("/docs")
        assert resp.status_code == 200
        assert "content-security-policy" not in resp.headers
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_auth_responses_are_not_cacheable(self, client, user_a):
        resp = client.post(
            "/api/auth/login",
            data={"username": "alice@example.com", "password": "password123"},
        )
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-store"

    def test_non_auth_responses_keep_cache_control(self, client):
        resp = client.get("/api/health")
        assert resp.headers.get("cache-control") != "no-store"

    def test_rate_limit_response_has_security_headers(self, client):
        limiter.enabled = True
        limiter.reset()
        try:
            for _ in range(6):
                resp = client.post(
                    "/api/auth/login",
                    data={"username": "nobody@example.com", "password": "wrong"},
                )
            assert resp.status_code == 429
            assert resp.headers["x-content-type-options"] == "nosniff"
        finally:
            limiter.reset()
            limiter.enabled = False


# ---------------------------------------------------------------------------
# 2) CORS
# ---------------------------------------------------------------------------


class TestCors:
    def _preflight(self, client, origin: str, method: str = "POST", headers: str = "authorization,content-type"):
        return client.options(
            "/api/auth/me",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": headers,
            },
        )

    def test_preflight_allowed_origin(self, client):
        resp = self._preflight(client, ORIGIN)
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == ORIGIN
        # Bearer-Auth → keine Cookies → keine Credentials
        assert "access-control-allow-credentials" not in resp.headers

    def test_preflight_foreign_origin_rejected(self, client):
        resp = self._preflight(client, "https://evil.example")
        assert resp.status_code == 400
        assert "access-control-allow-origin" not in resp.headers

    def test_preflight_unknown_header_rejected(self, client):
        resp = self._preflight(client, ORIGIN, headers="x-custom-header")
        assert resp.status_code == 400

    def test_simple_request_foreign_origin_gets_no_acao(self, client):
        resp = client.get("/api/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in resp.headers


# ---------------------------------------------------------------------------
# 3) Rate-Limits auf allen Auth-/Invite-Endpoints
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route_key",
    [
        "app.routers.auth.login",
        "app.routers.auth.register",
        "app.routers.auth.refresh_endpoint",
        "app.routers.auth.logout_endpoint",
        "app.routers.households.join_household",
    ],
)
def test_sensitive_endpoints_are_rate_limited(route_key):
    assert limiter._route_limits.get(route_key), f"{route_key} hat kein Rate-Limit"


@pytest.fixture()
def _limiter_on():
    limiter.enabled = True
    limiter.reset()
    yield
    limiter.reset()
    limiter.enabled = False


@pytest.mark.usefixtures("_limiter_on")
class TestRateLimitBehaviour:
    def test_join_is_limited_per_minute(self, client, token_b):
        headers = {"Authorization": f"Bearer {token_b}"}
        for i in range(5):
            resp = client.post("/api/households/join", json={"invite_code": f"NOPE{i:04d}"}, headers=headers)
            assert resp.status_code == 404
        resp = client.post("/api/households/join", json={"invite_code": "NOPE9999"}, headers=headers)
        assert resp.status_code == 429
        assert resp.json()["detail"]["code"] == "RATE_LIMITED"

    def test_refresh_is_limited(self, client):
        for _ in range(30):
            resp = client.post("/api/auth/refresh", json={"refresh_token": "invalid"})
            assert resp.status_code == 401
        resp = client.post("/api/auth/refresh", json={"refresh_token": "invalid"})
        assert resp.status_code == 429

    def test_logout_is_limited(self, client):
        for _ in range(30):
            resp = client.post("/api/auth/logout", json={"refresh_token": "invalid"})
            assert resp.status_code == 204
        resp = client.post("/api/auth/logout", json={"refresh_token": "invalid"})
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# 4) JWT-Claims
# ---------------------------------------------------------------------------


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


class TestJwtClaims:
    def test_token_without_exp_rejected(self, client, user_a):
        token = _encode({"sub": str(user_a.id)})
        with pytest.raises(jwt.MissingRequiredClaimError):
            decode_access_token(token)
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_token_without_sub_rejected(self, client):
        token = _encode({"exp": datetime.now(timezone.utc) + timedelta(minutes=5)})
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_alg_none_rejected(self, client, user_a):
        token = jwt.encode(
            {"sub": str(user_a.id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            key=None,
            algorithm="none",
        )
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 5) Login: kein Timing-Orakel für unbekannte E-Mails
# ---------------------------------------------------------------------------


def test_login_unknown_email_still_verifies_password(client):
    with patch("app.routers.auth.verify_password", return_value=False) as mock_verify:
        resp = client.post(
            "/api/auth/login",
            data={"username": "ghost@example.com", "password": "whatever123"},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"
    mock_verify.assert_called_once()


# ---------------------------------------------------------------------------
# 6) Upload: Pillow dekodiert nur JPEG/PNG/WEBP
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pil_format", ["GIF", "BMP", "TIFF"])
def test_upload_other_image_format_disguised_as_png_rejected(client, household_a, token_a, pil_format):
    """Ein gültiges Bild in einem nicht erlaubten Format wird trotz image/png abgelehnt."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="blue").save(buf, format=pil_format)
    buf.seek(0)
    with patch("app.routers.files._storage") as mock_storage:
        resp = client.post(
            f"/api/households/{household_a.id}/files/",
            headers={"Authorization": f"Bearer {token_a}"},
            files={"file": ("evil.png", buf, "image/png")},
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_TYPE_NOT_ALLOWED"
    mock_storage.save.assert_not_called()
