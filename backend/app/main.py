import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.routers import auth, shopping, todos, households, expenses, settlements, chores
from app.socket_manager import socket_app, set_event_loop

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Event-Loop für sync→async Bridge (emit_to_household_sync) setzen."""
    set_event_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title="Haushalt App API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(shopping.router)
app.include_router(todos.router)
app.include_router(households.router)
app.include_router(households.general_router)
app.include_router(expenses.router)
app.include_router(settlements.router)
app.include_router(chores.router)

# Socket.IO unter /socket.io mounten
app.mount("/socket.io", socket_app)


@app.get("/api/health")
def health():
    return {"status": "ok"}
