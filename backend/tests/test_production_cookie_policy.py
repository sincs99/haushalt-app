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
