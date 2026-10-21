import asyncio
import logging
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass, field
from weakref import WeakValueDictionary

import socketio
from jwt import PyJWTError as JWTError
from starlette.concurrency import run_in_threadpool

from app.core.security import decode_access_token_with_expiry
from app.database import SessionLocal
from app.models import HouseholdMember, User

logger = logging.getLogger(__name__)

# cors_allowed_origins=[] deaktiviert Engine.IO-CORS bewusst —
# CORS wird von FastAPIs CORSMiddleware gehandhabt (wirkt auch auf den /socket.io-Mount).
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=[])
socket_app = socketio.ASGIApp(sio)

# Wird beim App-Start gesetzt (main.py), damit sync Endpoints emit aufrufen können
_event_loop = None


def set_event_loop(loop):
    global _event_loop
    _event_loop = loop


# ---------------------------------------------------------------------------
# Synchrone DB-Hilfsfunktionen (geben nur Primitives zurück, keine ORM-Objekte)
# ---------------------------------------------------------------------------


def _load_user_id(uid: uuid.UUID) -> str | None:
    """Lädt die User-ID als String — Session wird sofort geschlossen."""
    with SessionLocal() as db:
        user = db.get(User, uid)
        return str(user.id) if user else None


def _is_household_member(household_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Prüft Haushaltsmitgliedschaft — Session wird sofort geschlossen."""
    with SessionLocal() as db:
        return (
            db.query(HouseholdMember)
            .filter_by(household_id=household_id, user_id=user_id)
            .first()
            is not None
        )


def _user_room(user_id) -> str:
    return f"user_{user_id}"


def _household_room(household_id) -> str:
    return f"household_{household_id}"


# ---------------------------------------------------------------------------
# Sitzungs-Ablauf
#
# Eine Socket-Verbindung lebt so lange wie das Access-Token, mit dem sie
# authentifiziert wurde. Der Ablauf (`exp`) steht in der Socket-Session; ein Timer
# pro Verbindung beendet sie zu diesem Zeitpunkt. Der Client verlängert die
# Verbindung nach jedem Token-Refresh mit dem Event `reauth`. Vor dem Trennen
# bekommt der Client `session_ended` mit dem Grund ("expired", "logout",
# "revoked"), damit er entscheiden kann, ob er mit frischem Token neu verbindet.
# ---------------------------------------------------------------------------

SESSION_ENDED_EVENT = "session_ended"

_expiry_timers: dict[str, asyncio.TimerHandle] = {}
# Referenzen auf laufende Trenn-Tasks, damit sie nicht vorzeitig vom GC entsorgt werden
_background_tasks: set[asyncio.Task] = set()


@dataclass
class _MembershipFence:
    generation: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Single-worker Socket.IO deployment: only the event loop touches these fences.
# Active joins/evictions hold strong references; idle keys do not accumulate.
_membership_fences: WeakValueDictionary[tuple[uuid.UUID, uuid.UUID], _MembershipFence] = WeakValueDictionary()


def _membership_fence(household_id: uuid.UUID, user_id: uuid.UUID) -> _MembershipFence:
    key = (household_id, user_id)
    fence = _membership_fences.get(key)
    if fence is None:
        fence = _MembershipFence()
        _membership_fences[key] = fence
    return fence


def _schedule_expiry(sid: str, exp: float) -> None:
    _cancel_expiry(sid)
    delay = max(0.0, exp - time.time())
    _expiry_timers[sid] = asyncio.get_running_loop().call_later(delay, _on_expiry, sid)


def _cancel_expiry(sid: str) -> None:
    handle = _expiry_timers.pop(sid, None)
    if handle is not None:
        handle.cancel()


def _on_expiry(sid: str) -> None:
    _expiry_timers.pop(sid, None)
    task = asyncio.ensure_future(end_session(sid, "expired"))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _session_expired(session: dict) -> bool:
    exp = session.get("exp")
    return exp is None or exp <= time.time()


async def end_session(sid: str, reason: str) -> None:
    """Teilt dem Client den Grund mit und trennt die Verbindung serverseitig."""
    try:
        await sio.emit(SESSION_ENDED_EVENT, {"reason": reason}, to=sid)
    except Exception:
        logger.warning("Socket end notification failed (sid=%s); disconnecting", sid, exc_info=True)
    try:
        await sio.disconnect(sid)
    except Exception:
        logger.warning("Socket end_session failed (sid=%s, reason=%s)", sid, reason, exc_info=True)
        return
    _cancel_expiry(sid)
    logger.info("Socket session ended (sid=%s, reason=%s)", sid, reason)


# ---------------------------------------------------------------------------
# Socket.IO Events
# ---------------------------------------------------------------------------

@sio.event
async def connect(sid, environ, auth):
    """JWT-Authentifizierung beim Verbindungsaufbau.

    Der Client sendet auth={"token": "<jwt>"}.
    Bei ungültigem Token wird die Verbindung abgelehnt (return False).
    """
    if not auth or "token" not in auth:
        logger.warning("Socket connect rejected – no auth token (sid=%s)", sid)
        return False

    # --- Token dekodieren (kein DB-Zugriff nötig) ---
    try:
        user_id_str, exp = decode_access_token_with_expiry(auth["token"])
        uid = uuid.UUID(user_id_str)
    except (JWTError, KeyError, ValueError) as exc:
        logger.warning("Socket connect rejected – token error (sid=%s): %s", sid, exc)
        return False

    # --- DB-Zugriff im Threadpool, damit der Event-Loop nicht blockiert ---
    try:
        user_id = await run_in_threadpool(_load_user_id, uid)
    except Exception:
        logger.error("Socket connect – DB error (sid=%s)", sid, exc_info=True)
        return False

    if user_id is None:
        logger.warning("Socket connect rejected – user not found (sid=%s)", sid)
        return False

    await sio.save_session(sid, {"user_id": user_id, "exp": exp})
    # Persönlicher Raum: erlaubt, alle Verbindungen eines Users serverseitig zu
    # erreichen (z.B. um sie bei Entfernung aus einem Haushalt aus dessen Raum zu
    # werfen oder sie beim Logout zu trennen)
    await sio.enter_room(sid, _user_room(user_id))
    _schedule_expiry(sid, exp)
    logger.info("Socket connected (sid=%s, user=%s)", sid, user_id)


@sio.event
async def reauth(sid, data):
    """Verlängert die Verbindung mit einem frischen Access-Token.

    data: {"token": "<jwt>"} — muss zum selben User gehören wie beim connect.
    Antwort (Ack): {"ok": bool}. Bei Fehlschlag bleibt der bisherige Ablauf bestehen.
    """
    token = (data or {}).get("token") if isinstance(data, dict) else None
    if not token:
        return {"ok": False}
    try:
        user_id_str, exp = decode_access_token_with_expiry(token)
        uid = uuid.UUID(user_id_str)
    except (JWTError, ValueError) as exc:
        logger.warning("Socket reauth rejected – token error (sid=%s): %s", sid, exc)
        return {"ok": False}

    session = await sio.get_session(sid)
    if session.get("user_id") != str(uid):
        logger.warning("Socket reauth rejected – user mismatch (sid=%s)", sid)
        return {"ok": False}

    session["exp"] = exp
    await sio.save_session(sid, session)
    _schedule_expiry(sid, exp)
    return {"ok": True}


@sio.event
async def join_household(sid, data):
    """Client tritt dem Room eines Haushalts bei.

    data: {"household_id": "<uuid>"}
    Membership wird via DB geprüft (gleiche Logik wie verify_household_access).
    """
    session = await sio.get_session(sid)
    user_id_str = session.get("user_id")
    if not user_id_str:
        await sio.emit("error", {"message": "Not authenticated"}, to=sid)
        return
    # Zusätzlich zum Timer: kein Raumbeitritt mit abgelaufenem Token
    if _session_expired(session):
        await end_session(sid, "expired")
        return

    household_id_str = (data or {}).get("household_id")
    if not household_id_str:
        await sio.emit("error", {"message": "household_id is required"}, to=sid)
        return

    # --- UUID-Parsing vor DB-Zugriff ---
    try:
        household_id = uuid.UUID(household_id_str)
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        await sio.emit("error", {"message": "Invalid household_id"}, to=sid)
        return

    # Capture before awaiting the DB. An eviction invalidates this result even
    # if the user leaves and rejoins while this old check is in flight.
    fence = _membership_fence(household_id, user_id)
    generation = fence.generation
    try:
        is_member = await run_in_threadpool(
            _is_household_member, household_id, user_id
        )
    except Exception:
        logger.error(
            "join_household – DB error (sid=%s, household=%s)",
            sid,
            household_id,
            exc_info=True,
        )
        await sio.emit("error", {"message": "Internal server error"}, to=sid)
        return

    if not is_member:
        await sio.emit(
            "error",
            {"message": "Not a member of this household"},
            to=sid,
        )
        return

    async with fence.lock:
        if generation != fence.generation:
            await sio.emit("error", {"message": "Membership changed; retry room join"}, to=sid)
            return
        # The token may have expired or the socket disconnected during the DB read.
        if not sio.manager.is_connected(sid, "/"):
            return
        session = await sio.get_session(sid)
        if _session_expired(session):
            await end_session(sid, "expired")
            return
        # Eviction shares this lock: it cannot finish while enter_room is pending.
        await sio.enter_room(sid, _household_room(household_id))
    logger.info(
        "User %s joined room household_%s (sid=%s)", user_id, household_id, sid
    )


@sio.event
async def leave_household(sid, data):
    """Client verlässt den Room eines Haushalts."""
    household_id_str = (data or {}).get("household_id")
    if not household_id_str:
        return
    try:
        household_id = uuid.UUID(household_id_str)
        await sio.leave_room(sid, _household_room(household_id))
        logger.info("Client left room household_%s (sid=%s)", household_id, sid)
    except ValueError:
        pass


@sio.event
async def disconnect(sid):
    _cancel_expiry(sid)
    logger.info("Socket disconnected (sid=%s)", sid)


# ---------------------------------------------------------------------------
# Helper für REST-Endpoints
# ---------------------------------------------------------------------------

async def emit_to_household(
    household_id: uuid.UUID, event_name: str, data: dict, evict_user_id: uuid.UUID | None = None
):
    """Emittiert ein Event an alle Clients im Household-Room.

    Mit evict_user_id werden danach alle Verbindungen dieses Users aus dem Room
    entfernt — er bekommt das Event (z.B. household_member_removed) also noch,
    aber keine weiteren Daten des Haushalts. Ohne das würde ein entferntes Mitglied
    mit einem manipulierten Client weiter alle Echtzeit-Events empfangen.
    """
    room = _household_room(household_id)
    if evict_user_id is not None:
        fence = _membership_fence(uuid.UUID(str(household_id)), uuid.UUID(str(evict_user_id)))
        # Increment before any await so every pending positive DB result is stale.
        fence.generation += 1
        async with fence.lock:
            try:
                await sio.emit(event_name, data, room=room)
            except Exception:
                # Notification delivery must never prevent authorization removal.
                logger.exception("Membership notification failed for room %s; continuing eviction", room)
            failed_sids: list[str] = []
            for sid, _ in list(sio.manager.get_participants("/", _user_room(evict_user_id))):
                try:
                    await sio.leave_room(sid, room)
                except Exception:
                    logger.exception("Room eviction failed for sid=%s; disconnecting", sid)
                    # Do not use end_session: its notification can itself fail.
                    try:
                        await sio.disconnect(sid)
                        _cancel_expiry(sid)
                    except Exception:
                        # Preserve the expiry timer if transport cleanup fails.
                        failed_sids.append(sid)
                        logger.exception("Fallback disconnect failed for sid=%s", sid)
            if failed_sids:
                # All other SIDs have still been processed. Surface incomplete
                # revocation to the waiting REST endpoint instead of claiming success.
                raise RuntimeError(f"Could not evict {len(failed_sids)} socket connection(s)")
        logger.info("Evicted user %s from room %s", evict_user_id, room)
    else:
        await sio.emit(event_name, data, room=room)


def _log_household_event_failure(future: Future) -> None:
    try:
        future.result()
    except Exception:
        logger.exception("Scheduled household event/eviction failed")


def emit_to_household_sync(
    household_id: uuid.UUID, event_name: str, data: dict, evict_user_id: uuid.UUID | None = None
):
    """Synchroner Wrapper — aufgerufen aus sync FastAPI-Endpoints.

    Nutzt run_coroutine_threadsafe, da sync Endpoints in einem Thread laufen.
    Membership removal waits for eviction before reporting HTTP success. Other
    events remain asynchronous. This sync helper must not wait on its own loop.
    """
    if _event_loop is not None and _event_loop.is_running():
        if evict_user_id is not None:
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if running_loop is _event_loop:
                raise RuntimeError("Await emit_to_household for eviction on the event-loop thread")
        future = asyncio.run_coroutine_threadsafe(
            emit_to_household(household_id, event_name, data, evict_user_id),
            _event_loop,
        )
        future.add_done_callback(_log_household_event_failure)
        if evict_user_id is not None:
            # Do not cancel on timeout: the queued revocation must still finish.
            # A stuck loop cannot make the REST endpoint falsely report success.
            future.result(timeout=5)
    else:
        if evict_user_id is not None:
            raise RuntimeError("Socket event loop unavailable for membership eviction")
        logger.warning(
            "emit_to_household_sync: Event-Loop not available, event '%s' for household %s dropped",
            event_name,
            household_id,
        )


async def disconnect_user(user_id: uuid.UUID, reason: str):
    """Trennt alle Socket-Verbindungen eines Users (z.B. nach Logout)."""
    for sid, _ in list(sio.manager.get_participants("/", _user_room(user_id))):
        await end_session(sid, reason)


def disconnect_user_sync(user_id: uuid.UUID, reason: str):
    """Synchroner Wrapper für disconnect_user — aufgerufen aus sync FastAPI-Endpoints."""
    if _event_loop is not None and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(disconnect_user(user_id, reason), _event_loop)
    else:
        logger.warning(
            "disconnect_user_sync: Event-Loop not available, sockets of user %s not disconnected",
            user_id,
        )
