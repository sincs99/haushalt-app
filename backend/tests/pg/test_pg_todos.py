"""Aufgaben mit mehreren Zuständigen auf PostgreSQL: parallele Claims und Migration mas1a2b3c4d5."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text

from tests.pg.harness import fresh_database, run_alembic, run_parallel, status_codes

BEFORE = "cal1a2b3c4d5"
MIGRATION = "mas1a2b3c4d5"


def test_parallel_claims_add_every_claimer(client, make_household, emits):
    """Drei Personen tippen gleichzeitig "Ich übernehme" → alle drei zuständig, kein 500/409."""
    hh = make_household(["Anna", "Ben", "Carla"])
    r = client.post(hh.url("/todos/"), json={"title": "Umzug"}, headers=hh.headers(0))
    assert r.status_code == 201
    todo_id = r.json()["id"]
    emits.clear()

    results = run_parallel(
        lambda i: client.post(hh.url(f"/todos/{todo_id}/claim"), headers=hh.headers(i)), 3
    )
    assert status_codes(results) == [200, 200, 200]

    final = client.get(hh.url("/todos/"), headers=hh.headers(0)).json()
    todo = next(t for t in final if t["id"] == todo_id)
    assert sorted(todo["assignee_ids"]) == sorted(str(u) for u in hh.user_ids)
    # Jede tatsächliche Änderung zählt die Version hoch (3 Claims → +3)
    assert todo["version"] == r.json()["version"] + 3
    assert len(emits.events("todo_updated")) == 3


def test_parallel_duplicate_claims_are_idempotent(client, make_household, emits):
    """Dieselbe Person doppelt (Doppeltipp, zwei Geräte) → einmal eingetragen, beide 200."""
    hh = make_household(["Anna", "Ben"])
    todo_id = client.post(hh.url("/todos/"), json={"title": "Keller"}, headers=hh.headers(0)).json()["id"]
    emits.clear()

    results = run_parallel(
        lambda i: client.post(hh.url(f"/todos/{todo_id}/claim"), headers=hh.headers(1)), 4
    )
    assert status_codes(results) == [200, 200, 200, 200]
    for res in results:
        assert res.json()["assignee_ids"] == [str(hh.user_ids[1])]
    assert len(emits.events("todo_updated")) == 1


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def _seed(conn):
    hh, anna, ben = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn.execute(text(
        "INSERT INTO households (id, name, invite_code, currency, timezone, created_at) "
        "VALUES (:id, 'HH', :code, 'CHF', 'Europe/Zurich', now())"
    ), {"id": hh, "code": uuid.uuid4().hex[:8].upper()})
    for uid, name in ((anna, "anna"), (ben, "ben")):
        conn.execute(text(
            "INSERT INTO users (id, email, password_hash, display_name, created_at) "
            "VALUES (:id, :email, 'x', :name, now())"
        ), {"id": uid, "email": f"{name}-{uuid.uuid4().hex[:6]}@example.com", "name": name})
    todos = {}
    created = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for label, assignee, done in (("ben", ben, False), ("open", None, False), ("done", anna, True)):
        todos[label] = tid = uuid.uuid4()
        conn.execute(text(
            "INSERT INTO todos (id, household_id, title, assigned_to_user_id, is_done, tags, "
            "created_at, updated_at, version) "
            "VALUES (:id, :hh, :t, :a, :d, '[]', :c, now(), 1)"
        ), {"id": tid, "hh": hh, "t": label, "a": assignee, "d": done, "c": created})
        created += timedelta(hours=1)
    return hh, anna, ben, todos


def test_migration_moves_assignments_and_downgrades(pg_admin_url):
    with fresh_database(pg_admin_url, upgrade_to=BEFORE) as url:
        engine = create_engine(url)
        try:
            with engine.begin() as conn:
                hh, anna, ben, todos = _seed(conn)

            run_alembic(url, "upgrade", MIGRATION)

            with engine.begin() as conn:
                rows = conn.execute(text(
                    "SELECT todo_id, user_id, household_id FROM todo_assignees ORDER BY user_id"
                )).all()
                assert {(r[0], r[1]) for r in rows} == {(todos["ben"], ben), (todos["done"], anna)}
                assert {r[2] for r in rows} == {hh}
                cols = set(conn.execute(text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = 'todos'"
                )).scalars())
                assert "assigned_to_user_id" not in cols
                assert "done_by_user_id" in cols
                # Neue Daten auf dem neuen Stand: zweite Zuständige auf "ben"
                conn.execute(text(
                    "INSERT INTO todo_assignees (todo_id, user_id, household_id, created_at) "
                    "VALUES (:t, :u, :hh, now())"
                ), {"t": todos["ben"], "u": anna, "hh": hh})
                # PK verhindert Doppel-Einträge
                dup = conn.execute(text(
                    "INSERT INTO todo_assignees (todo_id, user_id, household_id) VALUES (:t, :u, :hh) "
                    "ON CONFLICT DO NOTHING"
                ), {"t": todos["ben"], "u": anna, "hh": hh})
                assert dup.rowcount == 0

            run_alembic(url, "downgrade", BEFORE)

            with engine.connect() as conn:
                assigned = dict(conn.execute(text("SELECT id, assigned_to_user_id FROM todos")).all())
                # Erste zuständige Person (zuerst eingetragen) bleibt erhalten
                assert assigned == {todos["ben"]: ben, todos["open"]: None, todos["done"]: anna}
                exists = conn.execute(text("SELECT to_regclass('todo_assignees')")).scalar_one()
                assert exists is None

            run_alembic(url, "upgrade", "head")
        finally:
            engine.dispose()


def test_user_delete_cascades_assignment_and_nulls_done_by(pg_url, db, make_household):
    """Konto gelöscht → Zuweisung weg, "erledigt von" leer (Aufgabe bleibt)."""
    hh = make_household(["Anna", "Ben"])
    todo_id, ben = uuid.uuid4(), hh.user_ids[1]
    db.execute(text(
        "INSERT INTO todos (id, household_id, title, is_done, done_by_user_id, tags, created_at, updated_at, version) "
        "VALUES (:id, :hh, 'T', true, :ben, '[]', now(), now(), 1)"
    ), {"id": todo_id, "hh": hh.id, "ben": ben})
    db.execute(text(
        "INSERT INTO todo_assignees (todo_id, user_id, household_id) VALUES (:t, :u, :hh)"
    ), {"t": todo_id, "u": ben, "hh": hh.id})
    db.execute(text("DELETE FROM household_members WHERE user_id = :u"), {"u": ben})
    db.execute(text("DELETE FROM users WHERE id = :u"), {"u": ben})
    db.commit()
    assert db.execute(text("SELECT done_by_user_id FROM todos WHERE id = :t"), {"t": todo_id}).scalar_one() is None
    assert db.execute(text("SELECT count(*) FROM todo_assignees WHERE todo_id = :t"), {"t": todo_id}).scalar_one() == 0
