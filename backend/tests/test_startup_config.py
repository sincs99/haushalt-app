"""
Tests für die Startup-Validierung der Konfiguration.

Stellt sicher, dass Platzhalter-Secrets aus Vorlagen (.env.example, Doku,
alte Compose-Defaults) den App-Start verhindern.
"""

import pytest

from app.main import is_insecure_jwt_secret


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
