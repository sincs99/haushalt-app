"""Zeitplanänderung, Pausieren und Reaktivieren von Ämtli (CASA-16, CASA-17/PD-C1, CASA-51, CASA-46).

„Heute“ wird in Router und Scheduler gepatcht (wie in test_chores.py).
"""

import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from app.core.security import hash_password
from app.models import ChoreAssignment, HouseholdMember, User

_PATCH_SERVICE = "app.services.chore_scheduler.today_in_tz"
_PATCH_ROUTER = "app.routers.chores.today_in_tz"


@contextmanager
def on(day: date):
    with patch(_PATCH_ROUTER, return_value=day), patch(_PATCH_SERVICE, return_value=day):
        yield


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def trio(db, household_a, user_a, user_a2, token_a):
    """Anna (user_a), Ben (user_a2), Carla — Rotation in dieser Reihenfolge."""
    carla = User(
        id=uuid.uuid4(),
        email="carla@example.com",
        password_hash=hash_password("password123"),
        display_name="Carla",
    )
    db.add(carla)
    db.flush()
    db.add(HouseholdMember(id=uuid.uuid4(), household_id=household_a.id, user_id=carla.id, role="member"))
    db.commit()
    return [user_a.id, user_a2.id, carla.id]


class Api:
    def __init__(self, client, household_id, token):
        self.client, self.hid, self.headers = client, household_id, _auth(token)

    @property
    def base(self):
        return f"/api/households/{self.hid}/chores"

    def create(self, day, rotation, **kw):
        with on(day):
            r = self.client.post(
                f"{self.base}/",
                json={"title": "Ämtli", "rotation_order": [str(u) for u in rotation], **kw},
                headers=self.headers,
            )
        assert r.status_code == 201, r.text
        return r.json()

    def patch(self, day, chore_id, body):
        with on(day):
            r = self.client.patch(f"{self.base}/{chore_id}", json=body, headers=self.headers)
        assert r.status_code == 200, r.text
        return r.json()

    def assignments(self, day, chore_id=None):
        with on(day):
            r = self.client.get(f"{self.base}/assignments", headers=self.headers)
        assert r.status_code == 200, r.text
        return [a for a in r.json() if chore_id is None or a["chore_id"] == chore_id]

    def complete(self, assignment_id):
        r = self.client.post(f"{self.base}/assignments/{assignment_id}/complete", headers=self.headers)
        assert r.status_code == 200, r.text


@pytest.fixture()
def api(client, household_a, token_a):
    return Api(client, household_a.id, token_a)


def _events(mock_emit, name):
    return [c[0][2] for c in mock_emit.call_args_list if c[0][1] == name]


# ---------------------------------------------------------------------------
# CASA-16: Zeitplanänderung erzeugt keinen überfälligen Termin, Rotation läuft weiter
# ---------------------------------------------------------------------------


def test_weekly_change_does_not_create_overdue_assignment(api, trio, _mock_socket_emit):
    chore = api.create(date(2026, 9, 28), trio, recurrence="weekly", weekday=0)  # Mo
    before = api.assignments(date(2026, 10, 10), chore["id"])  # Sa
    by_date = {a["due_date"]: a for a in before}
    assert set(by_date) >= {"2026-09-28", "2026-10-05", "2026-10-12"}
    deleted_id = by_date["2026-10-12"]["id"]
    assert by_date["2026-10-12"]["assigned_user_id"] == str(trio[2])  # Carla ist dran

    _mock_socket_emit.reset_mock()
    patched = api.patch(date(2026, 10, 10), chore["id"], {"weekday": 2})  # → Mi
    assert patched["anchor_date"] == "2026-10-14"

    after = api.assignments(date(2026, 10, 10), chore["id"])
    open_dates = sorted(a["due_date"] for a in after if a["completed_at"] is None)
    # Kein 2026-10-07 (wäre sofort überfällig); Carla behält ihren Turnus
    assert "2026-10-07" not in open_dates
    new = next(a for a in after if a["due_date"] == "2026-10-14")
    assert new["assigned_user_id"] == str(trio[2])

    # Andere Clients erfahren, welche Termine weg sind, und bekommen die neuen
    deleted = _events(_mock_socket_emit, "chore_assignments_deleted")
    assert deleted == [{"chore_id": chore["id"], "household_id": str(api.hid), "ids": [deleted_id]}]
    created = _events(_mock_socket_emit, "chore_assignment_created")
    assert [c["due_date"] for c in created] == ["2026-10-14"]


def test_monthly_change_does_not_create_overdue_assignment(api, trio):
    chore = api.create(date(2026, 10, 1), trio, recurrence="monthly", day_of_month=1)
    api.assignments(date(2026, 10, 10), chore["id"])
    patched = api.patch(date(2026, 10, 10), chore["id"], {"day_of_month": 8})
    assert patched["anchor_date"] == "2026-11-08"
    after = api.assignments(date(2026, 10, 10), chore["id"])
    assert [a["due_date"] for a in after] == ["2026-10-01"]


# ---------------------------------------------------------------------------
# CASA-51: vorzeitig erledigter künftiger Termin blockiert den neuen Zeitplan nicht
# ---------------------------------------------------------------------------


def test_completed_future_assignment_does_not_block_new_schedule(api, trio):
    today = date(2026, 10, 10)  # Sa
    chore = api.create(today, trio, recurrence="weekly", weekday=4)  # Fr 10-16
    friday = api.assignments(today, chore["id"])
    assert [a["due_date"] for a in friday] == ["2026-10-16"]
    api.complete(friday[0]["id"])

    api.patch(today, chore["id"], {"weekday": 0})  # → Mo
    dates = [a["due_date"] for a in api.assignments(today, chore["id"])]
    assert "2026-10-12" in dates  # nächster Montag
    assert "2026-10-16" in dates  # erledigter Termin bleibt Historie


def test_completed_early_assignment_is_not_duplicated_and_keeps_rotation(api, trio):
    today = date(2026, 10, 10)
    chore = api.create(today, trio, recurrence="weekly", weekday=4)
    first = api.assignments(today, chore["id"])[0]
    api.complete(first["id"])
    # Eine Woche später: nächster Termin (10-23) geht an die nächste Person
    later = api.assignments(date(2026, 10, 17), chore["id"])
    assert [a["due_date"] for a in later] == ["2026-10-16", "2026-10-23"]
    assert later[1]["assigned_user_id"] == str(trio[1])


# ---------------------------------------------------------------------------
# CASA-17 / PD-C1: Pausieren löscht offene Termine ab heute, Reaktivieren ohne Nachholen
# ---------------------------------------------------------------------------


def test_pause_deletes_open_assignments_from_today(api, trio, db, _mock_socket_emit):
    today = date(2026, 10, 10)  # Sa
    chore = api.create(today, trio, recurrence="weekly", weekday=5)  # Sa → heute
    assigned = api.assignments(today, chore["id"])
    assert [a["due_date"] for a in assigned] == ["2026-10-10", "2026-10-17"]

    _mock_socket_emit.reset_mock()
    paused = api.patch(today, chore["id"], {"active": False})
    assert paused["active"] is False
    # Rotationsplätze zurückgegeben
    assert paused["next_rotation_index"] == 0

    db.expire_all()
    assert db.query(ChoreAssignment).filter_by(chore_id=uuid.UUID(chore["id"])).count() == 0
    deleted = _events(_mock_socket_emit, "chore_assignments_deleted")
    assert sorted(deleted[0]["ids"]) == sorted(a["id"] for a in assigned)

    # Pausiert: nichts wird mehr materialisiert
    assert api.assignments(date(2026, 10, 24), chore["id"]) == []


def test_pause_keeps_completed_and_past_assignments(api, trio):
    chore = api.create(date(2026, 10, 3), trio, recurrence="weekly", weekday=5)
    first = api.assignments(date(2026, 10, 3), chore["id"])[0]  # 10-03
    api.complete(first["id"])
    api.assignments(date(2026, 10, 10), chore["id"])
    api.patch(date(2026, 10, 10), chore["id"], {"active": False})
    remaining = api.assignments(date(2026, 10, 10), chore["id"])
    assert [a["due_date"] for a in remaining] == ["2026-10-03"]


def test_reactivation_reanchors_without_overdue_burst(api, trio):
    chore = api.create(date(2026, 10, 10), trio, recurrence="weekly", weekday=5)
    api.assignments(date(2026, 10, 10), chore["id"])
    api.patch(date(2026, 10, 10), chore["id"], {"active": False})

    reactivated = api.patch(date(2026, 11, 18), chore["id"], {"active": True})  # Mi
    assert reactivated["anchor_date"] == "2026-11-21"  # nächster Samstag ab heute
    after = api.assignments(date(2026, 11, 18), chore["id"])
    assert [a["due_date"] for a in after] == ["2026-11-21"]
    # Anna war vor der Pause dran (Platz zurückgegeben) → ist es wieder
    assert after[0]["assigned_user_id"] == str(trio[0])


def test_rename_while_paused_keeps_paused(api, trio):
    chore = api.create(date(2026, 10, 10), trio, recurrence="weekly", weekday=5)
    api.patch(date(2026, 10, 10), chore["id"], {"active": False})
    renamed = api.patch(date(2026, 10, 12), chore["id"], {"title": "Neu", "active": False})
    assert renamed["active"] is False
    assert renamed["anchor_date"] == "2026-10-10"


def test_paused_chore_not_counted_in_badge_or_pushed(api, trio, db, household_a, token_a, client):
    """Überfälliger offener Termin eines pausierten Ämtlis zählt nicht mehr."""
    chore = api.create(date(2026, 10, 3), trio, recurrence="weekly", weekday=5)
    api.assignments(date(2026, 10, 10), chore["id"])  # 10-03 (Anna) überfällig, 10-10, 10-17
    api.patch(date(2026, 10, 10), chore["id"], {"active": False})

    with patch("app.services.attention.household_today", return_value=date(2026, 10, 10)):
        badge = client.get(f"/api/households/{household_a.id}/dashboard/badge", headers=_auth(token_a))
    assert badge.json()["count"] == 0

    import app.services.push_service as ps

    sent = []
    with patch.object(ps, "send_to_users", side_effect=lambda *a, **k: sent.append(a) or 1):
        ps.process_chore_assignments(db, datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc))
    assert sent == []


# ---------------------------------------------------------------------------
# CASA-46: Materialisierung durch den Push-Scheduler meldet neue Termine
# ---------------------------------------------------------------------------


def test_push_scheduler_materialisation_emits_created(db, api, trio, household_a, _mock_socket_emit):
    import app.services.push_service as ps

    chore = api.create(date(2026, 10, 10), trio, recurrence="weekly", weekday=0)
    _mock_socket_emit.reset_mock()
    ps._chores_materialized.pop(household_a.id, None)
    with patch(_PATCH_SERVICE, return_value=date(2026, 10, 10)), patch.object(
        ps, "send_to_users", return_value=0
    ):
        ps.process_chore_assignments(db, datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc))
    created = _events(_mock_socket_emit, "chore_assignment_created")
    assert [c["chore_id"] for c in created] == [chore["id"]]
