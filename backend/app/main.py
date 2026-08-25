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
from app.core.rate_limit import limiter
from app.database import SessionLocal
from app.routers import auth, shopping, todos, households, expenses, settlements, chores, dashboard, tasks, budgets, recurring_bills, events, calendars, polls, pets, food, notes, files
from app.socket_manager import socket_app, set_event_loop

logger = logging.getLogger("uvicorn.error")

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

_JWT_PLACEHOLDER = "please-change-this-secret-in-production-min-32-chars"


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
    if settings.jwt_secret_key == _JWT_PLACEHOLDER or len(settings.jwt_secret_key) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY is insecure! It must be at least 32 characters and not the .env.example placeholder. "
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
    yield


app = FastAPI(title="Haushalt App API", lifespan=lifespan)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _custom_rate_limit_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
