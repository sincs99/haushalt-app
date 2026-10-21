"""
Hilfsfunktionen der PostgreSQL-Testlane (portiert aus docs/qa/audit-evidence/pgharness.py).

Alles hier arbeitet mit ECHTEN Sessions (eine pro Request bzw. pro Helper-Aufruf) gegen
eine frisch per ``alembic upgrade head`` aufgebaute Datenbank. Die Fixtures in
``conftest.py`` binden ``app.database.SessionLocal`` an diese Datenbank.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Datenbanken anlegen / löschen, Alembic ausführen
# ---------------------------------------------------------------------------


def _admin_engine(admin_url: str):
    # CREATE/DROP DATABASE darf nicht in einer Transaktion laufen
    return create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)


def create_database(admin_url: str, prefix: str = "casa_test") -> str:
    """Legt eine leere Datenbank an und liefert deren URL (gleicher Server/User wie admin_url)."""
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    eng = _admin_engine(admin_url)
    try:
        with eng.connect() as conn:
            conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        eng.dispose()
    return make_url(admin_url).set(database=name).render_as_string(hide_password=False)


def drop_database(admin_url: str, db_url: str) -> None:
    name = make_url(db_url).database
    eng = _admin_engine(admin_url)
    try:
        with eng.connect() as conn:
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    finally:
        eng.dispose()


def run_alembic(db_url: str, *args: str) -> subprocess.CompletedProcess:
    """Führt das echte Alembic-CLI gegen db_url aus (Subprozess: env.py liest DATABASE_URL).

    Wirft AssertionError mit stdout/stderr, wenn Alembic fehlschlägt.
    """
    env = {
        **os.environ,
        "DATABASE_URL": db_url,
        "JWT_SECRET_KEY": os.environ.get("JWT_SECRET_KEY", "pg-lane-secret-key-only-for-tests-min32"),
        "CORS_ORIGINS": os.environ.get("CORS_ORIGINS", "http://localhost:5173"),
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(args)} failed ({result.returncode})\n"
            f"--- stdout ---\n{result.stdout[-4000:]}\n--- stderr ---\n{result.stderr[-4000:]}"
        )
    return result


@contextmanager
def fresh_database(admin_url: str, upgrade_to: str | None = "head"):
    """Context-Manager: eigene Wegwerf-DB (z. B. für Migrationstests), optional migriert."""
    url = create_database(admin_url, prefix="casa_mig")
    try:
        if upgrade_to:
            run_alembic(url, "upgrade", upgrade_to)
        yield url
    finally:
        drop_database(admin_url, url)


# ---------------------------------------------------------------------------
# Testdaten: Haushalte, Mitglieder, Tokens
# ---------------------------------------------------------------------------


@dataclass
class PgHousehold:
    """Haushalt mit Mitgliedern; Index 0 ist Admin, alle weiteren sind Member."""

    id: uuid.UUID
    user_ids: list[uuid.UUID] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)

    def headers(self, i: int = 0) -> dict[str, str]:
        return auth_headers(self.tokens[i])

    def url(self, path: str = "") -> str:
        """Pfad unterhalb von /api/households/{id} — z. B. hh.url("/budget")."""
        return f"/api/households/{self.id}{path}"


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_household(
    names: list[str] = ("Anna", "Ben"),  # type: ignore[assignment]
    *,
    timezone_name: str = "Europe/Zurich",
    currency: str = "CHF",
) -> PgHousehold:
    """Legt Haushalt + Mitglieder in einer eigenen Session an (committed)."""
    from app.core.security import create_access_token
    from app.database import SessionLocal
    from app.models import Household, HouseholdMember, User

    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with SessionLocal() as s:
        h = Household(
            id=uuid.uuid4(),
            name="HH-" + uuid.uuid4().hex[:6],
            invite_code=uuid.uuid4().hex[:8].upper(),
            timezone=timezone_name,
            currency=currency,
        )
        s.add(h)
        s.flush()
        hh = PgHousehold(id=h.id)
        for i, name in enumerate(names):
            u = User(
                id=uuid.uuid4(),
                email=f"{name.lower()}-{uuid.uuid4().hex[:8]}@example.com",
                password_hash="x",
                display_name=name,
            )
            s.add(u)
            s.flush()
            # joined_at gestaffelt → "Senior"-Reihenfolge ist deterministisch
            s.add(
                HouseholdMember(
                    id=uuid.uuid4(),
                    household_id=h.id,
                    user_id=u.id,
                    role="admin" if i == 0 else "member",
                    joined_at=base + timedelta(days=i),
                )
            )
            hh.user_ids.append(u.id)
            hh.tokens.append(create_access_token(str(u.id)))
        s.commit()
    return hh


def add_member(hh: PgHousehold, name: str, role: str = "member") -> tuple[uuid.UUID, str]:
    """Fügt einem bestehenden Haushalt ein Mitglied hinzu; aktualisiert hh in place."""
    from app.core.security import create_access_token
    from app.database import SessionLocal
    from app.models import HouseholdMember, User

    with SessionLocal() as s:
        u = User(
            id=uuid.uuid4(),
            email=f"{name.lower()}-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="x",
            display_name=name,
        )
        s.add(u)
        s.flush()
        s.add(HouseholdMember(id=uuid.uuid4(), household_id=hh.id, user_id=u.id, role=role))
        s.commit()
        uid = u.id
    token = create_access_token(str(uid))
    hh.user_ids.append(uid)
    hh.tokens.append(token)
    return uid, token


# ---------------------------------------------------------------------------
# Parallelität
# ---------------------------------------------------------------------------


def run_parallel(fn: Callable[[int], Any], n: int, timeout: float = 60) -> list[Any]:
    """Startet fn(0..n-1) in n Threads, die per Barrier gleichzeitig loslaufen.

    Liefert die Ergebnisse in Index-Reihenfolge; eine Exception wird als Wert
    zurückgegeben (nicht geworfen), damit Tests alle Ausgänge auswerten können.
    """
    barrier = threading.Barrier(n)
    out: list[Any] = [None] * n

    def run(i: int) -> None:
        barrier.wait()
        try:
            out[i] = fn(i)
        except Exception as exc:  # noqa: BLE001 – Ergebnis statt Abbruch
            out[i] = exc

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
        if t.is_alive():
            raise AssertionError(f"run_parallel: thread did not finish within {timeout}s (deadlock?)")
    return out


def status_codes(results: list[Any]) -> list[int | str]:
    """Statuscodes aus run_parallel-Ergebnissen (Response) — Exceptions als Klassenname."""
    return [getattr(r, "status_code", type(r).__name__) for r in results]


# ---------------------------------------------------------------------------
# Socket-Emits
# ---------------------------------------------------------------------------


class EmitRecorder:
    """Ersatz für emit_to_household_sync: zeichnet (household_id, event, data) auf."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, household_id, event, data=None, *args, **kwargs) -> None:
        with self._lock:
            self.calls.append((household_id, event, data))

    def events(self, name: str | None = None) -> list[tuple[Any, str, Any]]:
        return [c for c in self.calls if name is None or c[1] == name]

    def names(self) -> list[str]:
        return [c[1] for c in self.calls]

    def clear(self) -> None:
        with self._lock:
            self.calls.clear()
