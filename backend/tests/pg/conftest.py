"""
PostgreSQL-Testlane (Marker ``pg``).

Läuft nur, wenn ``TEST_PG_URL`` gesetzt ist (Admin-URL eines PG-Servers, z. B.
``postgresql://audit:audit@localhost:5432/postgres``) — sonst werden alle Tests in
diesem Verzeichnis übersprungen, der normale SQLite-Lauf bleibt unverändert.

Pro Testlauf (Paket-Scope) wird eine frische Datenbank angelegt, mit dem echten
``alembic upgrade head`` migriert und ``app.database.SessionLocal`` darauf umgebogen.
Der ``client`` nutzt die ECHTE ``get_db``-Dependency (eine Session pro Request,
kein geteiltes Session-Override wie im SQLite-Lauf) — nur so werden Races,
Locks und Constraint-Verletzungen beobachtbar.

Details und Beispiele: README.md in diesem Verzeichnis.
"""

import importlib
import os
import pkgutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from tests.pg import harness

PG_ADMIN_URL = os.environ.get("TEST_PG_URL")
_PG_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config, items):
    """Marker ``pg`` auf alle Tests dieses Verzeichnisses; ohne TEST_PG_URL überspringen."""
    skip = pytest.mark.skip(reason="TEST_PG_URL nicht gesetzt (PostgreSQL-Lane)")
    for item in items:
        if _PG_DIR in Path(item.fspath).resolve().parents:
            item.add_marker(pytest.mark.pg)
            if not PG_ADMIN_URL:
                item.add_marker(skip)


# ---------------------------------------------------------------------------
# Datenbank (eine pro Testlauf)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="package")
def pg_url():
    """URL der frisch migrierten Test-DB; bindet SessionLocal für die Dauer des Pakets um."""
    if not PG_ADMIN_URL:
        pytest.skip("TEST_PG_URL nicht gesetzt")

    import app.database as database

    url = harness.create_database(PG_ADMIN_URL)
    try:
        harness.run_alembic(url, "upgrade", "head")
        # Gleiche Pool-Parameter wie in Produktion (app/database.py)
        engine = create_engine(
            url, pool_size=20, max_overflow=10, pool_timeout=10, pool_pre_ping=True
        )
        old_engine, old_bind = database.engine, database.SessionLocal.kw.get("bind")
        database.engine = engine
        database.SessionLocal.configure(bind=engine)
        try:
            yield url
        finally:
            database.SessionLocal.configure(bind=old_bind)
            database.engine = old_engine
            engine.dispose()
    finally:
        if not os.environ.get("TEST_PG_KEEP_DB"):
            harness.drop_database(PG_ADMIN_URL, url)


@pytest.fixture(scope="package")
def pg_admin_url():
    """Admin-URL (für Tests, die eigene Wegwerf-DBs anlegen, z. B. Migrationstests)."""
    if not PG_ADMIN_URL:
        pytest.skip("TEST_PG_URL nicht gesetzt")
    return PG_ADMIN_URL


@pytest.fixture()
def db(pg_url):
    """Echte Session gegen die PG-Test-DB (überschreibt die SQLite-``db``-Fixture)."""
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ---------------------------------------------------------------------------
# App-Umgebung: Emits aufzeichnen, Rate-Limit aus, echter Client
# ---------------------------------------------------------------------------


def _modules_with_emit():
    """Alle app-Module, die emit_to_household_sync direkt importiert haben."""
    import app.routers
    import app.services

    mods = []
    for pkg in (app.routers, app.services):
        for info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + "."):
            mod = importlib.import_module(info.name)
            if hasattr(mod, "emit_to_household_sync"):
                mods.append(mod)
    return mods


@pytest.fixture(autouse=True)
def emits(monkeypatch):
    """Zeichnet alle Socket-Emits auf (``emits.calls`` / ``emits.events("todo_updated")``)."""
    import app.socket_manager as socket_manager

    recorder = harness.EmitRecorder()
    monkeypatch.setattr(socket_manager, "emit_to_household_sync", recorder)
    for mod in _modules_with_emit():
        monkeypatch.setattr(mod, "emit_to_household_sync", recorder)
    return recorder


@pytest.fixture(autouse=True)
def _pg_rate_limit_off():
    from app.core.rate_limit import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture()
def client(pg_url):
    """TestClient ohne get_db-Override: jede Anfrage bekommt ihre eigene echte Session."""
    from app.main import app

    app.dependency_overrides.clear()
    # Kein Kontextmanager → Lifespan (Push-Scheduler, Cleanup-Loop) startet nicht
    return TestClient(app)


@pytest.fixture()
def make_household(pg_url):
    """Factory: ``make_household(["Anna", "Ben"])`` → PgHousehold (Index 0 = Admin)."""
    return harness.create_household


@pytest.fixture()
def household(make_household):
    """Standard-Haushalt mit Anna (Admin) und Ben (Member)."""
    return make_household(["Anna", "Ben"])
