"""
Tests für die Lebensdauer von Socket-Verbindungen.

Stellt sicher, dass:
- eine Verbindung serverseitig getrennt wird, wenn ihr Access-Token abläuft
- `reauth` mit frischem Token desselben Users die Verbindung verlängert
- nach Ablauf kein Raumbeitritt mehr möglich ist
- Logout und Reuse-Detection alle Verbindungen des Users trennen (nur dieses Users)
"""

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest

from app import socket_manager
from app.core.config import settings
from app.core.security import ALGORITHM
from app.socket_manager import disconnect_user, emit_to_household_sync, sio


def _token(user_id, expires_in: float) -> str:
    exp = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.jwt_secret_key, algorithm=ALGORITHM)


class FakeServer:
    """Ersetzt die Teile von `sio`, die eine echte Engine.IO-Verbindung brauchen.

    Räume laufen über den echten Manager; Sessions, emit und disconnect werden
    aufgezeichnet. disconnect ruft wie der echte Server den disconnect-Handler auf.
    """

    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.calls: list[tuple] = []

    async def save_session(self, sid, session, namespace=None):
        self.sessions[sid] = dict(session)

    async def get_session(self, sid, namespace=None):
        return dict(self.sessions.get(sid, {}))

    async def emit(self, event, data=None, to=None, room=None, **kw):
        self.calls.append(("emit", event, data, to or room))

    async def disconnect(self, sid, namespace=None, **kw):
        self.calls.append(("disconnect", sid))
        await socket_manager.disconnect(sid)
        await sio.manager.disconnect(sid, "/")

    def ended(self, sid):
        """Grund, mit dem die Verbindung beendet wurde (None = noch offen)."""
        reasons = [c[2]["reason"] for c in self.calls if c[0] == "emit" and c[1] == "session_ended" and c[3] == sid]
        disconnected = ("disconnect", sid) in self.calls
        assert bool(reasons) == disconnected, "session_ended und disconnect gehören zusammen"
        return reasons[0] if reasons else None


@pytest.fixture()
def fake_sio():
    fake = FakeServer()
    with (
        patch.object(sio, "save_session", fake.save_session),
        patch.object(sio, "get_session", fake.get_session),
        patch.object(sio, "emit", fake.emit),
        patch.object(sio, "disconnect", fake.disconnect),
    ):
        yield fake


class _ShiftedClock:
    """Lässt den Socket-Manager die Zeit um `offset` Sekunden voraus sehen.

    JWT-`exp` hat Sekundenauflösung; statt Sekunden zu warten, sieht der Server ein
    60-Sekunden-Token so, als liefe es in `60 - offset` Sekunden ab.
    """

    def __init__(self, offset: float):
        self.offset = offset

    def time(self) -> float:
        return time.time() + self.offset


def _expiring_soon(seconds: float = 0.2):
    """Patch: 60-Sekunden-Tokens laufen aus Sicht des Servers in `seconds` ab."""
    return patch.object(socket_manager, "time", _ShiftedClock(60 - seconds))


async def _open(user_id, token) -> str:
    """Simuliert einen connect mit Token; liefert die sid (oder None bei Ablehnung)."""
    sid = await sio.manager.connect(f"eio-{uuid.uuid4()}", "/")
    with patch("app.socket_manager._load_user_id", return_value=str(user_id)):
        result = await socket_manager.connect(sid, {}, {"token": token})
    if result is False:
        await sio.manager.disconnect(sid, "/")
        return None
    return sid


async def _cleanup(*sids):
    for sid in sids:
        socket_manager._cancel_expiry(sid)
        if sio.manager.is_connected(sid, "/"):
            await sio.manager.disconnect(sid, "/")


# ---------------------------------------------------------------------------
# Token-Ablauf
# ---------------------------------------------------------------------------


def test_connection_is_closed_when_token_expires(fake_sio):
    user = uuid.uuid4()

    async def scenario():
        sid = await _open(user, _token(user, 60))
        assert sid is not None
        assert fake_sio.ended(sid) is None
        await asyncio.sleep(0.4)
        reason = fake_sio.ended(sid)
        await _cleanup(sid)
        return sid, reason

    with _expiring_soon():
        sid, reason = asyncio.run(scenario())
    assert reason == "expired"
    assert sid not in socket_manager._expiry_timers


def test_expired_token_is_rejected_on_connect(fake_sio):
    user = uuid.uuid4()
    assert asyncio.run(_open(user, _token(user, -5))) is None


def test_reauth_extends_connection(fake_sio):
    user = uuid.uuid4()

    async def scenario():
        sid = await _open(user, _token(user, 60))
        ack = await socket_manager.reauth(sid, {"token": _token(user, 3600)})
        await asyncio.sleep(0.4)
        reason = fake_sio.ended(sid)
        exp = fake_sio.sessions[sid]["exp"]
        await _cleanup(sid)
        return ack, reason, exp

    with _expiring_soon():
        ack, reason, exp = asyncio.run(scenario())
    assert ack == {"ok": True}
    assert reason is None
    assert exp > time.time() + 3000


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"token": "kaputt"},
        {"token": "OTHER_USER"},
        {"token": "EXPIRED"},
    ],
)
def test_reauth_rejects_invalid_tokens_and_keeps_expiry(fake_sio, payload):
    user = uuid.uuid4()
    if payload and payload.get("token") == "OTHER_USER":
        payload = {"token": _token(uuid.uuid4(), 60)}
    elif payload and payload.get("token") == "EXPIRED":
        payload = {"token": _token(user, -5)}

    async def scenario():
        sid = await _open(user, _token(user, 60))
        ack = await socket_manager.reauth(sid, payload)
        await asyncio.sleep(0.4)
        reason = fake_sio.ended(sid)
        await _cleanup(sid)
        return ack, reason

    with _expiring_soon():
        ack, reason = asyncio.run(scenario())
    assert ack == {"ok": False}
    assert reason == "expired"


def test_join_household_after_expiry_ends_session(fake_sio):
    """Auch ohne Timer (z.B. verzögert): abgelaufene Session darf keinem Raum beitreten."""
    user, household = uuid.uuid4(), uuid.uuid4()

    async def scenario():
        sid = await _open(user, _token(user, 60))
        socket_manager._cancel_expiry(sid)
        fake_sio.sessions[sid]["exp"] = time.time() - 1
        with patch("app.socket_manager._is_household_member", return_value=True):
            await socket_manager.join_household(sid, {"household_id": str(household)})
        rooms = sio.manager.get_rooms(sid, "/") if sio.manager.is_connected(sid, "/") else []
        reason = fake_sio.ended(sid)
        await _cleanup(sid)
        return rooms, reason

    rooms, reason = asyncio.run(scenario())
    assert f"household_{household}" not in rooms
    assert reason == "expired"


def test_disconnect_cancels_expiry_timer(fake_sio):
    user = uuid.uuid4()

    async def scenario():
        sid = await _open(user, _token(user, 60))
        assert sid in socket_manager._expiry_timers
        await socket_manager.disconnect(sid)
        await _cleanup(sid)
        return sid

    sid = asyncio.run(scenario())
    assert sid not in socket_manager._expiry_timers


@pytest.mark.parametrize("reason", ["expired", "logout", "revoked"])
def test_end_session_disconnects_when_notification_fails(fake_sio, reason):
    async def scenario():
        user = uuid.uuid4()
        sid = await _open(user, _token(user, 60))

        async def fail_emit(*_args, **_kwargs):
            raise RuntimeError("synthetic notification failure")

        try:
            with patch.object(sio, "emit", fail_emit):
                await socket_manager.end_session(sid, reason)
            assert not sio.manager.is_connected(sid, "/")
            assert sid not in socket_manager._expiry_timers
        finally:
            await _cleanup(sid)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Logout / Widerruf
# ---------------------------------------------------------------------------


def test_disconnect_user_ends_all_connections_of_that_user_only(fake_sio):
    user, other = uuid.uuid4(), uuid.uuid4()

    async def scenario():
        phone = await _open(user, _token(user, 60))
        laptop = await _open(user, _token(user, 60))
        stranger = await _open(other, _token(other, 60))
        await disconnect_user(user, "logout")
        result = {name: fake_sio.ended(sid) for name, sid in (("phone", phone), ("laptop", laptop), ("stranger", stranger))}
        await _cleanup(phone, laptop, stranger)
        return result

    assert asyncio.run(scenario()) == {"phone": "logout", "laptop": "logout", "stranger": None}


def _login(client):
    resp = client.post("/api/auth/login", data={"username": "alice@example.com", "password": "password123"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_logout_disconnects_user_sockets(client, user_a):
    tokens = _login(client)
    with patch("app.routers.auth.disconnect_user_sync") as mock_disconnect:
        resp = client.post("/api/auth/logout", json={"refresh_token": tokens["refresh_token"]})
        assert resp.status_code == 204
        mock_disconnect.assert_called_once_with(user_a.id, "logout")

        # Zweiter Logout mit demselben (schon widerrufenen) Token löst nichts mehr aus
        mock_disconnect.reset_mock()
        client.post("/api/auth/logout", json={"refresh_token": tokens["refresh_token"]})
        client.post("/api/auth/logout", json={"refresh_token": "unbekannt"})
        mock_disconnect.assert_not_called()


def test_refresh_token_reuse_disconnects_user_sockets(client, user_a):
    tokens = _login(client)
    assert client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 200
    with (
        patch.object(settings, "refresh_token_reuse_grace_seconds", 0),
        patch("app.routers.auth.disconnect_user_sync") as mock_disconnect,
    ):
        resp = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 401
    mock_disconnect.assert_called_once_with(user_a.id, "revoked")


def test_disconnect_user_sync_runs_on_event_loop():
    """Der Sync-Wrapper übergibt die Arbeit an den Event-Loop des Servers."""
    user = uuid.uuid4()
    called = []

    async def fake_disconnect_user(user_id, reason):
        called.append((user_id, reason))

    async def scenario():
        loop = asyncio.get_running_loop()
        with (
            patch.object(socket_manager, "_event_loop", loop),
            patch("app.socket_manager.disconnect_user", fake_disconnect_user),
        ):
            # Aufruf aus einem Worker-Thread, wie bei sync FastAPI-Endpoints
            await asyncio.to_thread(socket_manager.disconnect_user_sync, user, "logout")
            await asyncio.sleep(0.05)

    asyncio.run(scenario())
    assert called == [(user, "logout")]


def test_eviction_fences_delayed_positive_membership_result_and_allows_fresh_join(fake_sio):
    user, household = uuid.uuid4(), uuid.uuid4()

    async def scenario():
        sid = await _open(user, _token(user, 60))
        queried, resume = asyncio.Event(), asyncio.Event()

        async def stale_positive(*_args):
            queried.set()
            await resume.wait()
            return True

        try:
            with patch.object(socket_manager, "run_in_threadpool", stale_positive):
                pending = asyncio.create_task(socket_manager.join_household(sid, {"household_id": str(household)}))
                await asyncio.wait_for(queried.wait(), 2)
                await socket_manager.emit_to_household(household, "household_member_removed", {}, evict_user_id=user)
                resume.set()
                await asyncio.wait_for(pending, 2)
            assert f"household_{household}" not in sio.manager.get_rooms(sid, "/")
            # A real later rejoin gets a NEW DB check and may join successfully.
            with patch.object(socket_manager, "_is_household_member", return_value=True):
                await socket_manager.join_household(sid, {"household_id": str(household)})
            assert f"household_{household}" in sio.manager.get_rooms(sid, "/")
        finally:
            resume.set()
            await _cleanup(sid)

    asyncio.run(scenario())


def test_eviction_waits_for_pending_room_entry_before_completing(fake_sio):
    user, household = uuid.uuid4(), uuid.uuid4()

    async def scenario():
        sid = await _open(user, _token(user, 60))
        entering, resume = asyncio.Event(), asyncio.Event()
        original_enter = sio.enter_room

        async def delayed_enter(room_sid, room, **kwargs):
            if room == f"household_{household}":
                entering.set()
                await resume.wait()
            await original_enter(room_sid, room, **kwargs)

        try:
            with patch.object(sio, "enter_room", delayed_enter), patch.object(socket_manager, "_is_household_member", return_value=True):
                joining = asyncio.create_task(socket_manager.join_household(sid, {"household_id": str(household)}))
                await asyncio.wait_for(entering.wait(), 2)
                evicting = asyncio.create_task(socket_manager.emit_to_household(household, "removed", {}, evict_user_id=user))
                await asyncio.sleep(0)  # Let eviction attempt to acquire the fence.
                assert not evicting.done()
                resume.set()
                await asyncio.wait_for(asyncio.gather(joining, evicting), 2)
            assert f"household_{household}" not in sio.manager.get_rooms(sid, "/")
        finally:
            resume.set()
            await _cleanup(sid)

    asyncio.run(scenario())


def test_eviction_removes_existing_member_even_when_notification_fails(fake_sio):
    user, household = uuid.uuid4(), uuid.uuid4()

    async def scenario():
        sid = await _open(user, _token(user, 60))
        await sio.enter_room(sid, f"household_{household}")

        async def fail_emit(*_args, **_kwargs):
            raise RuntimeError("synthetic notification failure")

        try:
            with patch.object(sio, "emit", fail_emit):
                await socket_manager.emit_to_household(household, "removed", {}, evict_user_id=user)
            assert f"household_{household}" not in sio.manager.get_rooms(sid, "/")
        finally:
            await _cleanup(sid)

    asyncio.run(scenario())


@pytest.mark.parametrize("disconnect_fails", [False, True])
def test_eviction_processes_other_sids_after_leave_failure(fake_sio, disconnect_fails):
    user, household = uuid.uuid4(), uuid.uuid4()

    async def scenario():
        first = await _open(user, _token(user, 60))
        second = await _open(user, _token(user, 60))
        for sid in (first, second):
            await sio.enter_room(sid, f"household_{household}")
        original_leave = sio.leave_room

        async def fail_first_leave(sid, room, **kwargs):
            if sid == first:
                raise RuntimeError("synthetic leave failure")
            await original_leave(sid, room, **kwargs)

        async def disconnect(sid, **kwargs):
            if disconnect_fails:
                raise RuntimeError("synthetic disconnect failure")
            await fake_sio.disconnect(sid, **kwargs)

        try:
            with patch.object(sio, "leave_room", fail_first_leave), patch.object(sio, "disconnect", disconnect):
                if disconnect_fails:
                    with pytest.raises(RuntimeError, match="Could not evict"):
                        await socket_manager.emit_to_household(household, "removed", {}, evict_user_id=user)
                    assert first in socket_manager._expiry_timers
                else:
                    await socket_manager.emit_to_household(household, "removed", {}, evict_user_id=user)
                    assert not sio.manager.is_connected(first, "/")
            assert f"household_{household}" not in sio.manager.get_rooms(second, "/")
        finally:
            await _cleanup(first, second)

    asyncio.run(scenario())


def test_sync_membership_removal_waits_for_eviction_completion():
    user, household = uuid.uuid4(), uuid.uuid4()

    async def scenario():
        entered, resume = asyncio.Event(), asyncio.Event()

        async def controlled_eviction(*_args, **_kwargs):
            entered.set()
            await resume.wait()

        with patch.object(socket_manager, "_event_loop", asyncio.get_running_loop()), patch.object(socket_manager, "emit_to_household", controlled_eviction):
            worker = asyncio.create_task(asyncio.to_thread(emit_to_household_sync, household, "removed", {}, user))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                assert not worker.done()
            finally:
                resume.set()
            await asyncio.wait_for(worker, 2)

    asyncio.run(scenario())
