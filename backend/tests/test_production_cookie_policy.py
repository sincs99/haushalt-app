import asyncio

import pytest

from app.core.config import settings
from app.main import app, lifespan


def test_production_startup_rejects_insecure_cookie_override(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)

    async def start():
        async with lifespan(app):
            pytest.fail("Insecure production must fail before serving traffic")

    with pytest.raises(RuntimeError, match="secure refresh cookies"):
        asyncio.run(start())


def test_production_startup_rejects_disabled_rate_limits(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    monkeypatch.setattr(settings, "rate_limit_enabled", False)

    async def start():
        async with lifespan(app):
            pytest.fail("Production must not start without rate limits")

    with pytest.raises(RuntimeError, match="RATE_LIMIT_ENABLED"):
        asyncio.run(start())
