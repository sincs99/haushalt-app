import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.error_codes import ErrorCode, error_detail
from app.core.log_redaction import install_tag_token_redaction
from app.core.rate_limit import limiter
from app.core.security_headers import SecurityHeadersMiddleware
from app.database import SessionLocal
from app.routers import (
    auth,
    budgets,
    calendars,
    chores,
    dashboard,
    documents,
    events,
    expenses,
    files,
    food,
    households,
    notes,
    pets,
    polls,
    push,
    recurring_bills,
    settlements,
    shopping,
    tags,
    tasks,
    todos,
)
from app.services.file_cleanup import cleanup_loop
from app.services.push_service import scheduler_loop
from app.socket_manager import set_event_loop, socket_app

logger = logging.getLogger("uvicorn.error")

# Tag-Tokens (NFC/QR) stehen im URL-Pfad → in Access-Logs schwärzen
install_tag_token_redaction()

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

_JWT_PLACEHOLDER = "please-change-this-secret-in-production-min-32-chars"
# Platzhalter-Muster aus .env.example / Doku / alten Compose-Defaults
_JWT_PLACEHOLDER_MARKERS = ("change", "placeholder", "example", "einfuegen")


def is_insecure_jwt_secret(secret: str) -> bool:
    """True für zu kurze oder offensichtlich aus Vorlagen übernommene Secrets."""
    lowered = secret.lower()
    return (
        len(secret) < 32
        or secret == _JWT_PLACEHOLDER
        or any(marker in lowered for marker in _JWT_PLACEHOLDER_MARKERS)
    )


async def _custom_rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Strukturierte JSON-Response statt generischem slowapi-Text."""
    return JSONResponse(
        status_code=429,
        content={"detail": error_detail(ErrorCode.RATE_LIMITED, "Too many requests")},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup-Checks und Event-Loop für sync→async Bridge setzen."""
    # JWT Secret Validierung
    if is_insecure_jwt_secret(settings.jwt_secret_key):
        raise RuntimeError(
            "JWT_SECRET_KEY is insecure! It must be at least 32 characters and not a template placeholder. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )

    # Startup-Log: Konfigurationsübersicht (NIE Passwörter loggen!)
    parsed_db = urlparse(settings.database_url)
    if parsed_db.hostname:
        db_display = f"{parsed_db.hostname}:{parsed_db.port or 5432}/{parsed_db.path.lstrip('/')}"
    else:
        # SQLite oder andere file-basierte URLs
        db_display = settings.database_url.split("://", 1)[-1]

    cors_display = ",".join(_cors_origins) or "(none)"
    token_ttl = f"{settings.access_token_expire_minutes}min"

    logger.info(
        "Casa starting — env=%s, db=%s, cors=%s, token_ttl=%s",
        settings.environment,
        db_display,
        cors_display,
        token_ttl,
    )

    set_event_loop(asyncio.get_running_loop())

    push_task = None
    if settings.push_enabled:
        push_task = asyncio.create_task(scheduler_loop())
    else:
        logger.info("Push notifications disabled (VAPID keys not configured)")

    cleanup_task = asyncio.create_task(cleanup_loop())

    yield

    cleanup_task.cancel()
    if push_task:
        push_task.cancel()


# redirect_slashes=False: Kein 307 bei fehlendem/überzähligem Slash. Hinter dem Proxy
# würde der Redirect sonst mit falschem Schema/Host gebaut und der Browser verwirft
# dabei den Authorization-Header — Pfadfehler sollen als 404 sofort auffallen.
app = FastAPI(title="Haushalt App API", lifespan=lifespan, redirect_slashes=False)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _custom_rate_limit_handler)

# Auth läuft ausschliesslich über den Authorization-Header (keine Cookies),
# daher allow_credentials=False und explizite Methoden-/Header-Listen.
# In Produktion ist die API same-origin (nginx-Proxy) — CORS greift nur im
# Dev-Setup bzw. bei gesetztem VITE_API_URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Accept-Language"],
)
# Zuletzt hinzugefügt = äusserste Middleware → Header auch auf CORS-Preflights
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth.router)
app.include_router(shopping.list_router)
app.include_router(shopping.router)
app.include_router(todos.router)
app.include_router(households.router)
app.include_router(households.general_router)
app.include_router(expenses.router)
app.include_router(settlements.router)
app.include_router(chores.router)
app.include_router(dashboard.router)
app.include_router(tasks.router)
app.include_router(budgets.router)
app.include_router(recurring_bills.router)
app.include_router(events.router)
app.include_router(calendars.router)
app.include_router(polls.router)
app.include_router(pets.router)
app.include_router(food.recipe_router)
app.include_router(food.meal_plan_router)
app.include_router(notes.router)
app.include_router(files.router)
app.include_router(documents.router)
app.include_router(push.router)
app.include_router(tags.router)
app.include_router(tags.scan_router)

# Socket.IO unter /socket.io mounten
app.mount("/socket.io", socket_app)


@app.get("/api/health")
def health():
    """Health-Check mit DB-Konnektivitätsprüfung.

    Kein Auth erforderlich — für Load-Balancer und Monitoring.
    """
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
        return {"status": "ok", "db": True}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "db": False},
        )
