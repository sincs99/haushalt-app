import asyncio
import logging
import uuid

import socketio
from jwt import PyJWTError as JWTError

from app.core.security import decode_access_token
from app.database import SessionLocal
from app.models import User, HouseholdMember

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

    db = SessionLocal()
    try:
        user_id_str = decode_access_token(auth["token"])
        user = db.get(User, uuid.UUID(user_id_str))
        if user is None:
            logger.warning("Socket connect rejected – user not found (sid=%s)", sid)
            return False

        await sio.save_session(sid, {"user_id": str(user.id)})
        logger.info("Socket connected (sid=%s, user=%s)", sid, user.id)
    except (JWTError, KeyError, ValueError) as exc:
        logger.warning("Socket connect rejected – token error (sid=%s): %s", sid, exc)
        return False
    finally:
        db.close()


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

    household_id_str = (data or {}).get("household_id")
    if not household_id_str:
        await sio.emit("error", {"message": "household_id is required"}, to=sid)
        return

    db = SessionLocal()
    try:
        household_id = uuid.UUID(household_id_str)
        user_id = uuid.UUID(user_id_str)

        membership = (
            db.query(HouseholdMember)
            .filter_by(household_id=household_id, user_id=user_id)
            .first()
        )

        if membership is None:
            await sio.emit(
                "error",
                {"message": "Not a member of this household"},
                to=sid,
            )
            return

        await sio.enter_room(sid, f"household_{household_id}")
        logger.info(
            "User %s joined room household_%s (sid=%s)", user_id, household_id, sid
        )
    except ValueError:
        await sio.emit("error", {"message": "Invalid household_id"}, to=sid)
    finally:
        db.close()


@sio.event
async def leave_household(sid, data):
    """Client verlässt den Room eines Haushalts."""
    household_id_str = (data or {}).get("household_id")
    if not household_id_str:
        return
    try:
        household_id = uuid.UUID(household_id_str)
        await sio.leave_room(sid, f"household_{household_id}")
        logger.info("Client left room household_%s (sid=%s)", household_id, sid)
    except ValueError:
        pass


@sio.event
async def disconnect(sid):
    logger.info("Socket disconnected (sid=%s)", sid)


# ---------------------------------------------------------------------------
# Helper für REST-Endpoints
# ---------------------------------------------------------------------------

async def emit_to_household(household_id: uuid.UUID, event_name: str, data: dict):
    """Emittiert ein Event an alle Clients im Household-Room."""
    await sio.emit(event_name, data, room=f"household_{household_id}")


def emit_to_household_sync(household_id: uuid.UUID, event_name: str, data: dict):
    """Synchroner Wrapper — aufgerufen aus sync FastAPI-Endpoints.

    Nutzt run_coroutine_threadsafe, da sync Endpoints in einem Thread laufen.
    """
    if _event_loop is not None and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(
            sio.emit(event_name, data, room=f"household_{household_id}"),
            _event_loop,
        )
    else:
        logger.warning(
            "emit_to_household_sync: Event-Loop not available, event '%s' for household %s dropped",
            event_name,
            household_id,
        )
