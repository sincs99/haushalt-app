import asyncio
import logging
import time
import uuid

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

    # Mitgliedschaft neu prüfen (CASA-48): Wurde der User inzwischen aus einem Haushalt
    # entfernt, dessen Raum diese Verbindung noch hält (z.B. Eviction verpasst), endet
    # der Empfang hier spätestens.
    for room in list(sio.manager.get_rooms(sid, "/")):
        if not isinstance(room, str) or not room.startswith("household_"):
            continue
        try:
            household_id = uuid.UUID(room.removeprefix("household_"))
            is_member = await run_in_threadpool(_is_household_member, household_id, uid)
        except Exception:
            logger.warning("Socket reauth – membership check failed (sid=%s, room=%s)", sid, room, exc_info=True)
            continue
        if not is_member:
            await sio.leave_room(sid, room)
            await sio.emit("error", _not_member_error(household_id), to=sid)
            logger.info("Socket reauth – left room %s, no longer a member (sid=%s)", room, sid)
    return {"ok": True}


def _not_member_error(household_id: uuid.UUID) -> dict:
    """Payload des ``error``-Events, wenn der User nicht (mehr) Mitglied ist.

    ``code`` wie bei REST (403 NOT_HOUSEHOLD_MEMBER): der Client lädt /me neu und
    behandelt den Haushalt als verlassen (CASA-49).
    """
    return {
        "message": "Not a member of this household",
        "code": "NOT_HOUSEHOLD_MEMBER",
        "household_id": str(household_id),
    }


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
        await sio.emit("error", _not_member_error(household_id), to=sid)
        return

    await sio.enter_room(sid, _household_room(household_id))

    # Erneut prüfen (CASA-48): Zwischen Prüfung und enter_room kann eine Entfernung
    # samt Eviction gelaufen sein — die Eviction hätte diese sid dann noch nicht im
    # Raum gefunden. Nach dem Beitritt ist jede spätere Eviction wirksam.
    try:
        still_member = await run_in_threadpool(_is_household_member, household_id, user_id)
    except Exception:
        logger.error("join_household – DB error on re-check (sid=%s)", sid, exc_info=True)
        still_member = False
    if not still_member:
        await sio.leave_room(sid, _household_room(household_id))
        await sio.emit("error", _not_member_error(household_id), to=sid)
        return

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
        for sid, _ in list(sio.manager.get_participants("/", _user_room(evict_user_id))):
            await sio.leave_room(sid, room)
        logger.info("Evicted user %s from room %s", evict_user_id, room)


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
