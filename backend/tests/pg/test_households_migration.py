"""Migration hh1a2b3c4d5e: verwaiste Haushalte löschen, fehlenden Admin nachtragen (CASA-10)."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text

from tests.pg.harness import fresh_database, run_alembic

BEFORE = "fin1a2b3c4d5"
REPAIR = "hh1a2b3c4d5e"


def _household(conn) -> uuid.UUID:
    hh = uuid.uuid4()
    conn.execute(text(
        "INSERT INTO households (id, name, invite_code, currency, timezone, created_at) "
        "VALUES (:id, 'HH', :code, 'CHF', 'Europe/Zurich', now())"
    ), {"id": hh, "code": uuid.uuid4().hex[:8].upper()})
    return hh


def _member(conn, hh, role, joined_at) -> uuid.UUID:
    user = uuid.uuid4()
    conn.execute(text(
        "INSERT INTO users (id, email, password_hash, display_name, created_at) "
        "VALUES (:id, :email, 'x', 'U', now())"
    ), {"id": user, "email": f"u-{uuid.uuid4().hex[:8]}@example.com"})
    conn.execute(text(
        "INSERT INTO household_members (id, household_id, user_id, role, joined_at) "
        "VALUES (:id, :hh, :u, :role, :j)"
    ), {"id": uuid.uuid4(), "hh": hh, "u": user, "role": role, "j": joined_at})
    return user


def _roles(conn, hh) -> dict:
    rows = conn.execute(
        text("SELECT user_id, role FROM household_members WHERE household_id = :hh"), {"hh": hh}
    ).all()
    return {r[0]: r[1] for r in rows}


def test_repair_deletes_orphans_and_promotes_senior(pg_admin_url):
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with fresh_database(pg_admin_url, upgrade_to=BEFORE) as url:
        engine = create_engine(url)
        try:
            with engine.begin() as conn:
                orphan = _household(conn)
                # Daten des verwaisten Haushalts (müssen per CASCADE mit verschwinden)
                conn.execute(text(
                    "INSERT INTO calendars (id, household_id, name, color, position, created_at) "
                    "VALUES (:id, :hh, 'Allgemein', '#5B8DEF', 0, now())"
                ), {"id": uuid.uuid4(), "hh": orphan})
                conn.execute(text(
                    "INSERT INTO todos (id, household_id, title, is_done, tags, created_at, updated_at, version) "
                    "VALUES (:id, :hh, 'geheim', false, '[]', now(), now(), 1)"
                ), {"id": uuid.uuid4(), "hh": orphan})

                no_admin = _household(conn)
                junior = _member(conn, no_admin, "member", t0 + timedelta(days=2))
                senior = _member(conn, no_admin, "member", t0 + timedelta(days=1))

                healthy = _household(conn)
                admin = _member(conn, healthy, "admin", t0 + timedelta(days=3))
                old_member = _member(conn, healthy, "member", t0)

            run_alembic(url, "upgrade", REPAIR)

            with engine.connect() as conn:
                exists = conn.execute(
                    text("SELECT count(*) FROM households WHERE id = :id"), {"id": orphan}
                ).scalar_one()
                assert exists == 0
                assert conn.execute(
                    text("SELECT count(*) FROM todos WHERE household_id = :id"), {"id": orphan}
                ).scalar_one() == 0
                assert _roles(conn, no_admin) == {senior: "admin", junior: "member"}
                # Haushalte mit Admin bleiben unverändert (kein zweiter Admin)
                assert _roles(conn, healthy) == {admin: "admin", old_member: "member"}

            # Forward-only Datenreparatur: Downgrade läuft durch, Upgrade erneut auch
            run_alembic(url, "downgrade", "-1")
            run_alembic(url, "upgrade", "head")
        finally:
            engine.dispose()
