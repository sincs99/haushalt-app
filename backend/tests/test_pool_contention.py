"""
Regressionstest für Epic 11: Connection-Pool-Contention + Event-Loop-Blocking.

Verifiziert, dass:
  - 25 gleichzeitige Requests keinen sqlalchemy.exc.TimeoutError auslösen
  - engine.pool.checkedout() nach Abschluss auf 0 zurückkehrt
  - Die alten Engine-Defaults (pool_size=5) unter gleicher Last versagen würden

Dieser Test nutzt bewusst eigene QueuePool-Engines (nicht conftest StaticPool),
um reales Pool-Verhalten zu simulieren.
"""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import TimeoutError as SATimeoutError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

_SQLITE_CONNECT_ARGS = {"check_same_thread": False}


def _make_engine(pool_size: int, max_overflow: int, pool_timeout: int):
    """Erstellt einen SQLite-Engine mit QueuePool (statt StaticPool).

    check_same_thread=False ist nötig, da SQLite standardmäßig nur
    vom erstellenden Thread genutzt werden darf.
    """
    return create_engine(
        "sqlite:///:memory:",
        connect_args=_SQLITE_CONNECT_ARGS,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        poolclass=QueuePool,
    )


def _hold_connection(session_factory, hold_seconds: float = 0.3):
    """Öffnet eine Session, hält die Connection kurz und gibt sie zurück."""
    session = session_factory()
    try:
        session.execute(text("SELECT 1"))
        time.sleep(hold_seconds)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tests: QueuePool-Verhalten unter konkurrierendem Zugriff
# ---------------------------------------------------------------------------


class TestPoolContention:
    """Prüft QueuePool-Verhalten unter konkurrierendem Zugriff."""

    def test_old_defaults_fail_under_load(self):
        """Alte Defaults (pool_size=5, max_overflow=10) versagen bei 25
        gleichzeitigen Requests — mindestens ein TimeoutError wird erwartet.

        pool_timeout=1 damit der Test schnell fehlschlägt.
        hold_seconds=2 damit alle 25 Threads gleichzeitig eine Connection
        brauchen und die 15 verfügbaren (5+10) nicht ausreichen.
        """
        eng = _make_engine(pool_size=5, max_overflow=10, pool_timeout=1)
        factory = sessionmaker(bind=eng)
        errors = []
        barrier = threading.Barrier(25, timeout=5)

        def _worker():
            try:
                # Alle Threads warten aufeinander, damit sie wirklich
                # gleichzeitig eine Connection anfordern
                barrier.wait()
                session = factory()
                try:
                    session.execute(text("SELECT 1"))
                    time.sleep(2)
                finally:
                    session.close()
            except SATimeoutError:
                errors.append(True)
            except threading.BrokenBarrierError:
                pass  # Barrier-Timeout ignorieren

        threads = [threading.Thread(target=_worker) for _ in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        eng.dispose()
        # Mit pool_size=5 + max_overflow=10 = max 15 Connections,
        # aber 25 Threads brauchen gleichzeitig eine → Timeout erwartet
        assert len(errors) > 0, (
            "Erwarteter TimeoutError trat nicht auf — "
            "alte Pool-Defaults wären nicht erschöpft worden"
        )

    def test_new_config_handles_25_concurrent(self):
        """Neue Konfiguration (pool_size=20, max_overflow=10, timeout=10)
        bewältigt 25 gleichzeitige Requests ohne TimeoutError.
        """
        eng = _make_engine(pool_size=20, max_overflow=10, pool_timeout=10)
        factory = sessionmaker(bind=eng)
        errors = []

        def _worker():
            try:
                _hold_connection(factory, hold_seconds=0.1)
            except SATimeoutError:
                errors.append(True)

        threads = [threading.Thread(target=_worker) for _ in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        # Pool muss komplett freigegeben sein
        assert eng.pool.checkedout() == 0, (
            f"Pool hat noch {eng.pool.checkedout()} ausgeliehene Connections"
        )
        assert len(errors) == 0, (
            f"{len(errors)} Requests bekamen TimeoutError — "
            "Pool ist trotz neuer Konfiguration zu klein"
        )
        eng.dispose()

    def test_pool_returns_to_zero_after_burst(self):
        """Nach einem Burst von 25 Requests müssen alle Connections
        zum Pool zurückkehren (checkedout == 0).
        """
        eng = _make_engine(pool_size=20, max_overflow=10, pool_timeout=10)
        factory = sessionmaker(bind=eng)

        with ThreadPoolExecutor(max_workers=25) as executor:
            futures = [
                executor.submit(_hold_connection, factory, 0.05)
                for _ in range(25)
            ]
            for f in as_completed(futures):
                f.result()  # wirft Exception falls aufgetreten

        assert eng.pool.checkedout() == 0
        eng.dispose()


class TestConcurrentDashboardWithSocket:
    """Simuliert den realen Lastfall: Dashboard-Requests + Socket-DB-Calls
    gleichzeitig über einen gemeinsamen Pool.
    """

    def test_mixed_load_no_timeout(self):
        """25 Dashboard-ähnliche Requests + 5 Socket-ähnliche DB-Lookups
        über denselben QueuePool — kein TimeoutError.
        """
        eng = _make_engine(pool_size=20, max_overflow=10, pool_timeout=10)
        factory = sessionmaker(bind=eng)
        errors = []

        def _dashboard_request():
            """Simuliert einen sync Dashboard-Endpoint (hält Connection kurz)."""
            try:
                session = factory()
                try:
                    session.execute(text("SELECT 1"))
                    time.sleep(0.05)
                finally:
                    session.close()
            except SATimeoutError:
                errors.append("dashboard")

        def _socket_db_lookup():
            """Simuliert einen Socket-Handler DB-Zugriff (kurz, im Threadpool)."""
            try:
                session = factory()
                try:
                    session.execute(text("SELECT 1"))
                    time.sleep(0.02)
                finally:
                    session.close()
            except SATimeoutError:
                errors.append("socket")

        threads = []
        # 25 Dashboard-Requests
        for _ in range(25):
            threads.append(threading.Thread(target=_dashboard_request))
        # 5 Socket-DB-Lookups (parallel)
        for _ in range(5):
            threads.append(threading.Thread(target=_socket_db_lookup))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert eng.pool.checkedout() == 0, (
            f"Pool hat noch {eng.pool.checkedout()} ausgeliehene Connections"
        )
        assert len(errors) == 0, (
            f"TimeoutErrors aufgetreten: {errors}"
        )
        eng.dispose()


class TestSocketHelperFunctions:
    """Prüft die extrahierten sync DB-Hilfsfunktionen aus socket_manager.

    Nutzt die conftest-Fixtures (db), damit Tabellen vorhanden sind.
    """

    def test_load_user_id_returns_none_for_unknown(self, db):
        """_load_user_id gibt None zurück für eine unbekannte UUID."""
        from app.socket_manager import _load_user_id
        from app.database import SessionLocal as _OrigSessionLocal

        # SessionLocal in socket_manager mit der Test-Session-Factory patchen
        def _test_session_factory():
            return db

        with patch("app.socket_manager.SessionLocal", return_value=db):
            result = _load_user_id(uuid.uuid4())
        assert result is None

    def test_is_household_member_returns_false_for_unknown(self, db):
        """_is_household_member gibt False zurück für unbekannte UUIDs."""
        from app.socket_manager import _is_household_member

        with patch("app.socket_manager.SessionLocal", return_value=db):
            result = _is_household_member(uuid.uuid4(), uuid.uuid4())
        assert result is False
