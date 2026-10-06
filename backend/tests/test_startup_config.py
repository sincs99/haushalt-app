"""
Tests für die Startup-Validierung der Konfiguration.

Stellt sicher, dass Platzhalter-Secrets aus Vorlagen (.env.example, Doku,
alte Compose-Defaults) den App-Start verhindern.
"""

import asyncio
from unittest.mock import patch

import pytest

from app.main import has_wildcard_cors_origin, is_insecure_jwt_secret


@pytest.mark.parametrize(
    "secret",
    [
        "please-change-this-secret-in-production-min-32-chars",  # .env.example
        "please-change-this-secret-in-production",  # früherer docker-compose.yml-Default
        "mindestens-32-zeichen-langer-zufallsstring-hier-einfuegen",  # Windows-Doku
        "CHANGEME-CHANGEME-CHANGEME-CHANGEME",
        "short",
    ],
)
def test_insecure_jwt_secrets_rejected(secret):
    assert is_insecure_jwt_secret(secret)


@pytest.mark.parametrize(
    "secret",
    [
        "test-secret-key-only-for-tests-min32",  # conftest
        "3vQm9Zk1rR7pX2wLcN8sT4yB6hJ0dF5gA_-eUiOqWzVx",  # token_urlsafe(32)
    ],
)
def test_random_jwt_secrets_accepted(secret):
    assert not is_insecure_jwt_secret(secret)


@pytest.mark.parametrize("origins", [["*"], ["http://localhost:5173", "*"], ["https://*.example.com"]])
def test_wildcard_cors_origins_detected(origins):
    assert has_wildcard_cors_origin(origins)


def test_explicit_cors_origins_accepted():
    assert not has_wildcard_cors_origin(["http://localhost:5173", "https://casa.example.com"])


def test_wildcard_cors_origin_prevents_startup():
    """allow_credentials=True (Refresh-Cookie) + '*' würde jeden Origin spiegeln → Start abbrechen."""
    from app.main import app as real_app
    from app.main import lifespan

    with patch("app.main._cors_origins", ["*"]):
        with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
            async def _run():
                async with lifespan(real_app):
                    pass  # pragma: no cover

            asyncio.run(_run())
