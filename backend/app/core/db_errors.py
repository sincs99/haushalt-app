"""Globales Mapping von DB-Konflikten auf HTTP 409 (F0-2, Safety-Net für CASA-24).

Viele Endpunkte prüfen erst und schreiben dann (Check-then-Insert). Laufen zwei
Requests gleichzeitig, greift am Ende der Unique-/FK-Constraint oder PostgreSQL
bricht eine Transaktion wegen Deadlock/Serialisierung ab. Ohne Handler wird das
ein generischer 500er. Hier wird daraus ``409 CONFLICT_RETRY`` — der Client kann
den Vorgang einfach wiederholen.

Das ist nur das Netz: Endpunkte mit bekannter Race-Bedingung sollen weiterhin
gezielt sperren (``app.services.locking``) bzw. den Konflikt fachlich beantworten
(z. B. ``BILL_ALREADY_BOOKED``). Die Request-Session wird in ``get_db`` zurückgerollt.
"""

import logging

from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import StaleDataError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.error_codes import ErrorCode, error_detail

logger = logging.getLogger("uvicorn.error")

# SQLSTATEs, bei denen ein Wiederholen sinnvoll ist
RETRYABLE_PGCODES = {
    "40001",  # serialization_failure
    "40P01",  # deadlock_detected
    "55P03",  # lock_not_available (lock_timeout / NOWAIT)
}


def is_retryable_db_error(exc: OperationalError) -> bool:
    return getattr(exc.orig, "pgcode", None) in RETRYABLE_PGCODES


def _conflict_response() -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "detail": error_detail(
                ErrorCode.CONFLICT_RETRY,
                "The data was changed concurrently. Please try again.",
            )
        },
    )


async def _integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    # Kein SQL/Parameter ins Log (können Nutzerdaten enthalten) — Constraint-Text genügt
    logger.warning(
        "DB integrity conflict on %s %s: %s",
        request.method,
        request.url.path,
        str(exc.orig).splitlines()[0] if exc.orig else type(exc).__name__,
    )
    return _conflict_response()


async def _stale_data_handler(request: Request, exc: StaleDataError) -> JSONResponse:
    logger.warning("Stale row on %s %s: %s", request.method, request.url.path, exc)
    return _conflict_response()


async def _operational_error_handler(request: Request, exc: OperationalError) -> JSONResponse:
    if is_retryable_db_error(exc):
        logger.warning(
            "Retryable DB error (%s) on %s %s",
            getattr(exc.orig, "pgcode", None),
            request.method,
            request.url.path,
        )
        return _conflict_response()
    # Alles andere (Verbindung weg, Timeout …) bleibt ein Serverfehler
    logger.error(
        "DB operational error on %s %s", request.method, request.url.path, exc_info=exc
    )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


def install_db_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(IntegrityError, _integrity_error_handler)
    app.add_exception_handler(StaleDataError, _stale_data_handler)
    app.add_exception_handler(OperationalError, _operational_error_handler)
