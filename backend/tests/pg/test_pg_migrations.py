"""Migrationen auf PostgreSQL: Datenreparatur fnd1a2b3c4d5 (P0-3 / CASA-04) und Downgrade."""

import uuid

from sqlalchemy import create_engine, text

from tests.pg.harness import fresh_database, run_alembic

BEFORE = "a3b4c5d6e7f8"
REPAIR = "fnd1a2b3c4d5"


def _seed_json_nulls(conn):
    """Legt je Tabelle eine kaputte (JSON-null) und eine gesunde Zeile an."""
    hh, user, cal = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn.execute(text(
        "INSERT INTO households (id, name, invite_code, currency, timezone, created_at) "
        "VALUES (:id, 'HH', :code, 'CHF', 'Europe/Zurich', now())"
    ), {"id": hh, "code": uuid.uuid4().hex[:8].upper()})
    conn.execute(text(
        "INSERT INTO users (id, email, password_hash, display_name, created_at) "
        "VALUES (:id, :email, 'x', 'Anna', now())"
    ), {"id": user, "email": f"anna-{uuid.uuid4().hex[:6]}@example.com"})
    conn.execute(text(
        "INSERT INTO calendars (id, household_id, name, color, position) "
        "VALUES (:id, :hh, 'Allgemein', '#5B8DEF', 0)"
    ), {"id": cal, "hh": hh})
    ids = {}
    for label, participants in (("broken", "null"), ("ok", f'["{user}"]')):
        ids[("events", label)] = eid = uuid.uuid4()
        conn.execute(text(
            "INSERT INTO events (id, household_id, calendar_id, title, starts_at, all_day, "
            "participant_ids, created_by_user_id, created_at) "
            "VALUES (:id, :hh, :cal, 'T', now(), false, CAST(:p AS json), :u, now())"
        ), {"id": eid, "hh": hh, "cal": cal, "p": participants, "u": user})

        ids[("recipes", label)] = rid = uuid.uuid4()
        value = "null" if label == "broken" else '["Mehl"]'
        conn.execute(text(
            "INSERT INTO recipes (id, household_id, name, servings, ingredients, steps, tags, "
            "is_favorite, created_at) VALUES (:id, :hh, 'R', 2, CAST(:v AS json), CAST(:v AS json), "
            "CAST(:v AS json), false, now())"
        ), {"id": rid, "hh": hh, "v": value})

        ids[("todos", label)] = tid = uuid.uuid4()
        conn.execute(text(
            "INSERT INTO todos (id, household_id, title, is_done, tags, created_by_user_id, "
            "created_at, updated_at, version) "
            "VALUES (:id, :hh, 'T', false, CAST(:v AS json), :u, now(), now(), 1)"
        ), {"id": tid, "hh": hh, "v": value, "u": user})

        ids[("chores", label)] = cid = uuid.uuid4()
        rotation = "null" if label == "broken" else f'["{user}"]'
        conn.execute(text(
            "INSERT INTO chores (id, household_id, title, recurrence, weekday, rotation_order, "
            "next_rotation_index, anchor_date, active, created_at) "
            "VALUES (:id, :hh, 'C', 'weekly', 0, CAST(:v AS json), 0, current_date, true, now())"
        ), {"id": cid, "hh": hh, "v": rotation})
    # created_at NULL in einer bisher nullable Spalte
    conn.execute(text("UPDATE calendars SET created_at = NULL WHERE id = :id"), {"id": cal})
    return ids, user, cal


def _json(conn, table, column, row_id):
    return conn.execute(
        text(f"SELECT CAST({column} AS TEXT) FROM {table} WHERE id = :id"), {"id": row_id}
    ).scalar_one()


def test_repair_migration_replaces_json_null_with_empty_list(pg_admin_url):
    with fresh_database(pg_admin_url, upgrade_to=BEFORE) as url:
        engine = create_engine(url)
        try:
            with engine.begin() as conn:
                ids, user, cal = _seed_json_nulls(conn)

            run_alembic(url, "upgrade", REPAIR)

            with engine.connect() as conn:
                checks = [
                    ("events", "participant_ids"), ("recipes", "ingredients"), ("recipes", "steps"),
                    ("recipes", "tags"), ("todos", "tags"), ("chores", "rotation_order"),
                ]
                for table, column in checks:
                    assert _json(conn, table, column, ids[(table, "broken")]) == "[]", (table, column)
                    # Gesunde Zeilen bleiben unverändert
                    assert _json(conn, table, column, ids[(table, "ok")]) != "[]", (table, column)
                assert _json(conn, "events", "participant_ids", ids[("events", "ok")]) == f'["{user}"]'

                created = conn.execute(
                    text("SELECT created_at FROM calendars WHERE id = :id"), {"id": cal}
                ).scalar_one()
                assert created is not None
                nullable = conn.execute(text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'calendars' AND column_name = 'created_at'"
                )).scalar_one()
                assert nullable == "NO"

            # Rückweg und erneuter Aufstieg funktionieren
            run_alembic(url, "downgrade", "-1")
            run_alembic(url, "upgrade", "head")
        finally:
            engine.dispose()
