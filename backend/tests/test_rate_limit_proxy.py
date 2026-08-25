"""Tests: Rate-Limiter erkennt separate Clients anhand der IP (X-Forwarded-For).

In Produktion übersetzt uvicorn mit ``--proxy-headers`` den
``X-Forwarded-For``-Header in ``request.client.host``.  Im Test
simulieren wir dieses Verhalten, indem wir die ``key_func`` auf den
internen ``Limit``-Objekten in ``limiter._route_limits`` austauschen.
Slowapi speichert Limits dort — nicht auf der Funktion selbst.
"""

import pytest
from starlette.requests import Request

from app.core.rate_limit import limiter

_LOGIN_ROUTE_KEY = "app.routers.auth.login"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _key_from_forwarded_for(request: Request) -> str:
    """Simuliert --proxy-headers: liest Client-IP aus X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_limiter_with_proxy_key():
    """Aktiviert den Limiter lokal und patcht key_func in _route_limits.

    Slowapi speichert Limit-Regeln in ``limiter._route_limits[name]``
    als ``slowapi.wrappers.Limit``-Objekte mit mutierbarem ``key_func``.
    """
    limiter.enabled = True

    # In-Memory-Storage zurücksetzen (verhindert Überlauf zwischen Tests)
    limiter.reset()

    # key_func auf den Login-Limits ersetzen
    login_limits = limiter._route_limits.get(_LOGIN_ROUTE_KEY, [])
    original_key_funcs = []
    for lim in login_limits:
        original_key_funcs.append(lim.key_func)
        lim.key_func = _key_from_forwarded_for

    yield

    # Wiederherstellen
    for i, lim in enumerate(login_limits):
        lim.key_func = original_key_funcs[i]

    limiter.enabled = False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRateLimitProxy:
    """Verschiedene IPs (via X-Forwarded-For) erhalten separate Rate-Limit-Buckets."""

    def test_different_ips_get_separate_buckets(self, client):
        """6. Request von IP A → 429, gleichzeitig IP B → kein 429."""
        # Client A: 5 Requests (Login-Limit ist 5/minute)
        for i in range(5):
            resp = client.post(
                "/api/auth/login",
                data={"username": "nobody@example.com", "password": "wrong"},
                headers={"X-Forwarded-For": "10.0.0.1"},
            )
            assert resp.status_code != 429, (
                f"Request {i + 1} von Client A sollte nicht limitiert sein"
            )

        # Client A: 6. Request → muss 429 sein
        resp_a6 = client.post(
            "/api/auth/login",
            data={"username": "nobody@example.com", "password": "wrong"},
            headers={"X-Forwarded-For": "10.0.0.1"},
        )
        assert resp_a6.status_code == 429, (
            "6. Request von Client A (10.0.0.1) muss Rate-Limited sein (429)"
        )

        # Client B: andere IP → eigener Bucket, NICHT limitiert
        resp_b = client.post(
            "/api/auth/login",
            data={"username": "nobody@example.com", "password": "wrong"},
            headers={"X-Forwarded-For": "10.0.0.2"},
        )
        assert resp_b.status_code != 429, (
            "Client B (10.0.0.2) hat eigenen Bucket und darf nicht limitiert sein"
        )

    def test_rate_limit_returns_structured_error(self, client):
        """429-Response enthält strukturierten Error-Code RATE_LIMITED."""
        # 5 Requests aufbrauchen
        for _ in range(5):
            client.post(
                "/api/auth/login",
                data={"username": "nobody@example.com", "password": "wrong"},
                headers={"X-Forwarded-For": "10.0.0.99"},
            )

        # 6. Request → 429 mit strukturiertem Body
        resp = client.post(
            "/api/auth/login",
            data={"username": "nobody@example.com", "password": "wrong"},
            headers={"X-Forwarded-For": "10.0.0.99"},
        )
        assert resp.status_code == 429
        body = resp.json()
        assert "detail" in body
        assert body["detail"]["code"] == "RATE_LIMITED"
