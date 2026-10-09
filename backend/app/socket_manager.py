import asyncio
import json
import logging
import time
import uuid

import socketio
from jwt import PyJWTError as JWTError
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.security import decode_access_token_with_expiry
from app.database import SessionLocal
from app.models import HouseholdMember, User

logger = logging.getLogger(__name__)


def _build_client_manager():
    """Redis-Message-Queue, damit Events alle Worker/Container erreichen (leer = ein Prozess)."""
    url = settings.socketio_message_queue.strip()
    if not url:
        return None
    return socketio.AsyncRedisManager(url)


# cors_allowed_origins=[] deaktiviert Engine.IO-CORS bewusst —
# CORS wird von FastAPIs CORSMiddleware gehandhabt (wirkt auch auf den /socket.io-Mount).
sio = socketio.AsyncServer(
    async_mode="asgi", cors_allowed_origins=[], client_manager=_build_client_manager()
)
socket_app = socketio.ASGIApp(sio)

# ---------------------------------------------------------------------------
# Kontrollkanal für mehrere Prozesse
#
# Die Socket.IO-Message-Queue verteilt ``emit`` an alle Prozesse. Teilnehmerlisten
# (``get_participants``) kennt aber jeder Prozess nur für seine eigenen Verbindungen.
# «Alle Verbindungen eines Users trennen» (Logout, Sperre) und «User aus dem
# Haushalts-Room werfen» laufen deshalb zusätzlich über einen eigenen Redis-Kanal:
# jeder Prozess führt den Befehl für seine lokalen Verbindungen aus.
# ---------------------------------------------------------------------------

CONTROL_CHANNEL = "casa:socket-control"
HOST_ID = uuid.uuid4().hex
_control_task: asyncio.Task | None = None


def _control_enabled() -> bool:
    return bool(settings.socketio_message_queue.strip())


async def _publish_control(message: dict) -> None:
    if not _control_enabled():
        return
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.socketio_message_queue.strip())
        try:
            await client.publish(CONTROL_CHANNEL, json.dumps({**message, "host": HOST_ID}))
        finally:
            await client.aclose()
    except Exception:
        logger.warning("Socket control publish failed (%s)", message.get("method"), exc_info=True)


async def handle_control_message(message: dict) -> None:
    """Führt einen Kontroll-Befehl eines anderen Prozesses lokal aus."""
    if message.get("host") == HOST_ID:
        return
    method = message.get("method")
    try:
        user_id = uuid.UUID(str(message.get("user_id")))
    except ValueError:
        return
    if method == "disconnect_user":
        await _disconnect_user_local(user_id, str(message.get("reason") or "revoked"))
    elif method == "evict_user":
        try:
            household_id = uuid.UUID(str(message.get("household_id")))
        except ValueError:
            return
        await _evict_user_local(household_id, user_id)


async def control_listener() -> None:
    """Hintergrund-Task (main.py lifespan): hört auf dem Kontrollkanal."""
    import redis.asyncio as aioredis

    while True:
        try:
            client = aioredis.from_url(settings.socketio_message_queue.strip())
            pubsub = client.pubsub()
            await pubsub.subscribe(CONTROL_CHANNEL)
            logger.info("Socket control listener subscribed (%s)", CONTROL_CHANNEL)
            async for raw in pubsub.listen():
                if raw.get("type") != "message":
                    continue
                try:
                    await handle_control_message(json.loads(raw["data"]))
                except Exception:
                    logger.warning("Socket control message failed", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Socket control listener lost Redis — retrying in 5s", exc_info=True)
            await asyncio.sleep(5)


def start_control_listener() -> None:
    global _control_task
    if _control_enabled() and _control_task is None:
        _control_task = asyncio.create_task(control_listener())


def stop_control_listener() -> None:
    global _control_task
    if _control_task is not None:
        _control_task.cancel()
        _control_task = None

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
    _cancel_expiry(sid)
    try:
        await sio.emit(SESSION_ENDED_EVENT, {"reason": reason}, to=sid)
        await sio.disconnect(sid)
    except Exception:
        logger.warning("Socket end_session failed (sid=%s, reason=%s)", sid, reason, exc_info=True)
        return
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

    # --- DB-Zugriff im Threadpool, damit der Event-Loop nicht blockiert ---
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
    await sio.emit(event_name, data, room=room)
    if evict_user_id is not None:
        await _evict_user_local(household_id, evict_user_id)
        await _publish_control(
            {"method": "evict_user", "household_id": str(household_id), "user_id": str(evict_user_id)}
        )


async def _evict_user_local(household_id: uuid.UUID, user_id: uuid.UUID) -> None:
    room = _household_room(household_id)
    for sid, _ in list(sio.manager.get_participants("/", _user_room(user_id))):
        await sio.leave_room(sid, room)
    logger.info("Evicted user %s from room %s", user_id, room)


def emit_to_household_sync(
    household_id: uuid.UUID, event_name: str, data: dict, evict_user_id: uuid.UUID | None = None
):
    """Synchroner Wrapper — aufgerufen aus sync FastAPI-Endpoints.

    Nutzt run_coroutine_threadsafe, da sync Endpoints in einem Thread laufen.
    Emit und Eviction laufen in einer Coroutine, damit die Reihenfolge garantiert ist.
    """
    if _event_loop is not None and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            emit_to_household(household_id, event_name, data, evict_user_id),
            _event_loop,
        )
    else:
        logger.warning(
            "emit_to_household_sync: Event-Loop not available, event '%s' for household %s dropped",
            event_name,
            household_id,
        )


async def _disconnect_user_local(user_id: uuid.UUID, reason: str) -> None:
    for sid, _ in list(sio.manager.get_participants("/", _user_room(user_id))):
        await end_session(sid, reason)


async def disconnect_user(user_id: uuid.UUID, reason: str):
    """Trennt alle Socket-Verbindungen eines Users (z.B. nach Logout) — in allen Prozessen."""
    await _disconnect_user_local(user_id, reason)
    await _publish_control({"method": "disconnect_user", "user_id": str(user_id), "reason": reason})


def disconnect_user_sync(user_id: uuid.UUID, reason: str):
    """Synchroner Wrapper für disconnect_user — aufgerufen aus sync FastAPI-Endpoints."""
    if _event_loop is not None and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(disconnect_user(user_id, reason), _event_loop)
    else:
        logger.warning(
            "disconnect_user_sync: Event-Loop not available, sockets of user %s not disconnected",
            user_id,
        )
