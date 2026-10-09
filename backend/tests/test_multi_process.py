"""Tests: Mehrprozess-Betrieb — Rate-Limit-Storage, Socket.IO-Kontrollkanal, Sentry-Init."""
import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

from app import socket_manager
from app.core.config import settings
from app.core.rate_limit import limiter


def test_rate_limiter_uses_memory_storage_by_default():
    assert settings.rate_limit_storage_uri == "memory://"
    assert type(limiter._storage).__name__ == "MemoryStorage"


def test_client_manager_only_with_queue(monkeypatch):
    monkeypatch.setattr(settings, "socketio_message_queue", "")
    assert socket_manager._build_client_manager() is None
    assert socket_manager._control_enabled() is False
    monkeypatch.setattr(settings, "socketio_message_queue", "redis://localhost:6379/1")
    manager = socket_manager._build_client_manager()
    assert type(manager).__name__ == "AsyncRedisManager"
    assert socket_manager._control_enabled() is True


def test_publish_control_is_noop_without_queue(monkeypatch):
    monkeypatch.setattr(settings, "socketio_message_queue", "")
    with patch("redis.asyncio.from_url") as from_url:
        asyncio.run(socket_manager._publish_control({"method": "disconnect_user", "user_id": "x"}))
    from_url.assert_not_called()


def test_publish_control_sends_json_with_host(monkeypatch):
    monkeypatch.setattr(settings, "socketio_message_queue", "redis://localhost:6379/1")
    client = AsyncMock()
    with patch("redis.asyncio.from_url", return_value=client):
        asyncio.run(socket_manager.disconnect_user(uuid.UUID(int=1), "logout"))
    channel, payload = client.publish.await_args.args
    assert channel == socket_manager.CONTROL_CHANNEL
    data = json.loads(payload)
    assert data["method"] == "disconnect_user"
    assert data["reason"] == "logout"
    assert data["host"] == socket_manager.HOST_ID
    client.aclose.assert_awaited()


def test_control_message_from_own_host_is_ignored():
    with patch.object(socket_manager, "_disconnect_user_local", new=AsyncMock()) as local:
        asyncio.run(socket_manager.handle_control_message(
            {"method": "disconnect_user", "user_id": str(uuid.uuid4()), "reason": "logout", "host": socket_manager.HOST_ID}
        ))
    local.assert_not_awaited()


def test_control_message_from_other_host_runs_locally():
    user_id = uuid.uuid4()
    household_id = uuid.uuid4()

    async def scenario():
        await socket_manager.handle_control_message(
            {"method": "disconnect_user", "user_id": str(user_id), "reason": "revoked", "host": "other"}
        )
        await socket_manager.handle_control_message(
            {"method": "evict_user", "user_id": str(user_id), "household_id": str(household_id), "host": "other"}
        )
        await socket_manager.handle_control_message({"method": "evict_user", "user_id": "nope", "host": "other"})

    with patch.object(socket_manager, "_disconnect_user_local", new=AsyncMock()) as disc, patch.object(
        socket_manager, "_evict_user_local", new=AsyncMock()
    ) as evict:
        asyncio.run(scenario())
    disc.assert_awaited_once_with(user_id, "revoked")
    evict.assert_awaited_once_with(household_id, user_id)


def test_sentry_init_only_with_dsn(monkeypatch):
    from app import main

    monkeypatch.setattr(settings, "sentry_dsn", "")
    assert main.init_sentry() is False
    monkeypatch.setattr(settings, "sentry_dsn", "https://key@example.ingest.sentry.io/1")
    with patch("sentry_sdk.init") as init:
        assert main.init_sentry() is True
    assert init.call_args.kwargs["send_default_pii"] is False
    assert init.call_args.kwargs["environment"] == settings.environment
