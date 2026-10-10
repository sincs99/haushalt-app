"""Kalender/Termine/Abstimmungen auf PostgreSQL: Races beim Löschen eines Kalenders (CASA-20, CASA-54)."""

import uuid

from app.models import Calendar, Event, EventPoll
from tests.pg.harness import run_parallel, status_codes


def _calendar(client, hh, name="Kalender"):
    resp = client.post(hh.url("/calendars/"), json={"name": name, "color": "#112233"}, headers=hh.headers())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_delete_calendar_vs_create_event_never_loses_confirmed_event(client, make_household, db):
    """Löschen ‖ Termin anlegen: ein bestätigter Termin (201) muss danach existieren."""
    for _ in range(5):
        hh = make_household(["Anna", "Ben"])
        _calendar(client, hh, "Bleibt")
        doomed = _calendar(client, hh, "Weg")

        def act(i, hh=hh, doomed=doomed):
            if i == 0:
                return client.delete(hh.url(f"/calendars/{doomed}"), headers=hh.headers(0))
            return client.post(
                hh.url("/events/"),
                json={"title": f"T{i}", "starts_at": "2026-10-07T09:00:00", "calendar_id": doomed},
                headers=hh.headers(1),
            )

        results = run_parallel(act, 4)
        codes = status_codes(results)
        assert 500 not in codes, codes

        db.expire_all()
        created = [r.json()["id"] for r in results[1:] if r.status_code == 201]
        for event_id in created:
            assert db.get(Event, uuid.UUID(event_id)) is not None, "bestätigter Termin verschwunden"
        if codes[0] == 204:
            assert not created
            assert db.get(Calendar, uuid.UUID(doomed)) is None
        else:
            assert codes[0] in (409, 422), codes


def test_concurrent_calendar_deletes_keep_one_calendar(client, make_household, db):
    """Zwei gleichzeitige Löschungen der letzten beiden Kalender: mindestens einer bleibt."""
    for _ in range(5):
        hh = make_household(["Anna", "Ben"])
        ids = [_calendar(client, hh, "A"), _calendar(client, hh, "B")]

        def delete(i, hh=hh, ids=ids):
            return client.delete(hh.url(f"/calendars/{ids[i]}"), headers=hh.headers(i))

        codes = status_codes(run_parallel(delete, 2))
        assert 500 not in codes, codes
        assert codes.count(204) == 1, codes
        db.expire_all()
        assert db.query(Calendar).filter_by(household_id=hh.id).count() == 1


def test_delete_calendar_vs_poll_decide(client, make_household, db):
    """Löschen ‖ Abstimmung entscheiden: nie 500, nie 'entschieden' ohne Termin."""
    for _ in range(5):
        hh = make_household(["Anna", "Ben"])
        _calendar(client, hh, "Bleibt")
        doomed = _calendar(client, hh, "Weg")
        poll = client.post(
            hh.url("/polls/"),
            json={
                "question": "Wann?",
                "options": [
                    {"label": "Sa", "starts_at": "2026-10-10T18:00:00"},
                    {"label": "So", "starts_at": "2026-10-11T18:00:00"},
                ],
            },
            headers=hh.headers(),
        ).json()

        def act(i, hh=hh, doomed=doomed, poll=poll):
            if i == 0:
                return client.delete(hh.url(f"/calendars/{doomed}"), headers=hh.headers(0))
            return client.post(
                hh.url(f"/polls/{poll['id']}/decide"),
                json={"option_id": poll["options"][0]["id"], "event_title": "Fest", "calendar_id": doomed},
                headers=hh.headers(1),
            )

        codes = status_codes(run_parallel(act, 2))
        assert 500 not in codes, codes
        db.expire_all()
        stored = db.get(EventPoll, uuid.UUID(poll["id"]))
        if stored.status == "entschieden":
            assert codes[1] == 200
            assert stored.decided_event_id is not None
            assert db.get(Event, stored.decided_event_id) is not None
        else:
            assert codes[1] in (409, 422), codes
            assert stored.decided_event_id is None


def test_household_delete_still_cascades_calendars_and_events(client, make_household, db):
    """FK events.calendar_id ist RESTRICT — das Löschen des ganzen Haushalts muss trotzdem gehen."""
    hh = make_household(["Anna"])
    cal = _calendar(client, hh)
    resp = client.post(
        hh.url("/events/"),
        json={"title": "T", "starts_at": "2026-10-07T09:00:00", "calendar_id": cal},
        headers=hh.headers(),
    )
    assert resp.status_code == 201
    # Letztes Mitglied verlässt den Haushalt → Haushalt wird gelöscht
    resp = client.post(hh.url("/leave"), headers=hh.headers())
    assert resp.status_code in (200, 204), resp.text
    db.expire_all()
    assert db.query(Calendar).filter_by(household_id=hh.id).count() == 0
    assert db.query(Event).filter_by(household_id=hh.id).count() == 0


def test_raw_household_delete_cascades_despite_restrict(client, make_household, db):
    """Auch ein reines SQL-DELETE des Haushalts (DB-Cascades) scheitert nicht am RESTRICT."""
    from sqlalchemy import text

    hh = make_household(["Anna"])
    cal = _calendar(client, hh)
    client.post(
        hh.url("/events/"),
        json={"title": "T", "starts_at": "2026-10-07T09:00:00", "calendar_id": cal},
        headers=hh.headers(),
    )
    db.execute(text("DELETE FROM households WHERE id = :id"), {"id": hh.id})
    db.commit()
    assert db.query(Event).filter_by(household_id=hh.id).count() == 0


def test_migration_cal_upgrade_downgrade(pg_admin_url):
    """cal1a2b3c4d5: bestehende Termine bekommen reminder='none'; RESTRICT greift; Rückweg geht."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import IntegrityError

    from tests.pg.harness import fresh_database, run_alembic

    with fresh_database(pg_admin_url, upgrade_to="pet1a2b3c4d5") as url:
        engine = create_engine(url)
        try:
            hh, user, cal, ev = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            with engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO households (id, name, invite_code, currency, timezone, created_at) "
                    "VALUES (:id, 'HH', :code, 'CHF', 'Europe/Zurich', now())"
                ), {"id": hh, "code": uuid.uuid4().hex[:8].upper()})
                conn.execute(text(
                    "INSERT INTO users (id, email, password_hash, display_name, created_at) "
                    "VALUES (:id, :email, 'x', 'Anna', now())"
                ), {"id": user, "email": f"anna-{uuid.uuid4().hex[:6]}@example.com"})
                conn.execute(text(
                    "INSERT INTO calendars (id, household_id, name, color, position, created_at) "
                    "VALUES (:id, :hh, 'Allgemein', '#5B8DEF', 0, now())"
                ), {"id": cal, "hh": hh})
                conn.execute(text(
                    "INSERT INTO events (id, household_id, calendar_id, title, starts_at, all_day, "
                    "participant_ids, created_by_user_id, created_at) "
                    "VALUES (:id, :hh, :cal, 'T', now(), false, CAST('[]' AS json), :u, now())"
                ), {"id": ev, "hh": hh, "cal": cal, "u": user})

            run_alembic(url, "upgrade", "cal1a2b3c4d5")
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT reminder, notified_at FROM events WHERE id = :id"), {"id": ev}
                ).one()
                assert row == ("none", None)
            with engine.connect() as conn:
                try:
                    conn.execute(text("DELETE FROM calendars WHERE id = :id"), {"id": cal})
                    raise AssertionError("RESTRICT hätte das Löschen verhindern müssen")
                except IntegrityError:
                    conn.rollback()

            run_alembic(url, "downgrade", "-1")
            run_alembic(url, "upgrade", "head")
        finally:
            engine.dispose()
