"""
Umfassende Tests für das Chores-Modul.

Teil 1: Scheduler-Unit-Tests (direkt gegen Service-Funktionen, kein HTTP)
Teil 2: API-Tests (CRUD, Assignments, Validierung, Socket-Events)

WICHTIG: today_in_tz wird sowohl im Service als auch im Router gepatcht,
damit alle Datumsberechnungen deterministisch sind.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.models import Chore, ChoreAssignment, Household, HouseholdMember, User
from app.core.security import hash_password
from app.services.chore_scheduler import (
    next_due_dates,
    _resolve_next_assignee,
    materialize_due_assignments,
)


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

MOCK_TODAY = date(2026, 8, 6)  # Donnerstag

_PATCH_SERVICE = "app.services.chore_scheduler.today_in_tz"
_PATCH_ROUTER = "app.routers.chores.today_in_tz"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _chores_url(household_id) -> str:
    return f"/api/households/{household_id}/chores/"


def _assignments_url(household_id) -> str:
    return f"/api/households/{household_id}/chores/assignments"


# ===========================================================================
# TEIL 1 — Scheduler-Unit-Tests (ohne HTTP)
# ===========================================================================


# ---------------------------------------------------------------------------
# 1. next_due_dates
# ---------------------------------------------------------------------------


class TestNextDueDates:
    """Pure-Function-Tests für next_due_dates."""

    def test_weekly_dates_in_window(self):
        """Weekly weekday=0 (Mo), 2026-08-03..2026-08-24 → 4 Montage."""
        chore = SimpleNamespace(
            recurrence="weekly",
            weekday=0,
            anchor_date=date(2026, 8, 3),
        )
        result = next_due_dates(chore, date(2026, 8, 3), date(2026, 8, 24))
        assert result == [
            date(2026, 8, 3),
            date(2026, 8, 10),
            date(2026, 8, 17),
            date(2026, 8, 24),
        ]

    def test_biweekly_dates_parity(self):
        """Biweekly weekday=0, anchor=2026-08-03 → nur gerade Wochen."""
        chore = SimpleNamespace(
            recurrence="biweekly",
            weekday=0,
            anchor_date=date(2026, 8, 3),
        )
        result = next_due_dates(chore, date(2026, 8, 3), date(2026, 9, 14))
        assert result == [
            date(2026, 8, 3),
            date(2026, 8, 17),
            date(2026, 8, 31),
            date(2026, 9, 14),
        ]

    def test_monthly_day31_february(self):
        """day_of_month=31 → Feb 28 in Nicht-Schaltjahr (2026)."""
        chore = SimpleNamespace(recurrence="monthly", day_of_month=31)
        result = next_due_dates(chore, date(2026, 1, 1), date(2026, 4, 30))
        assert result == [
            date(2026, 1, 31),
            date(2026, 2, 28),
            date(2026, 3, 31),
            date(2026, 4, 30),
        ]

    def test_monthly_day31_leap_year(self):
        """day_of_month=31 → Feb 29 im Schaltjahr (2028)."""
        chore = SimpleNamespace(recurrence="monthly", day_of_month=31)
        result = next_due_dates(chore, date(2028, 1, 1), date(2028, 3, 31))
        assert result == [
            date(2028, 1, 31),
            date(2028, 2, 29),
            date(2028, 3, 31),
        ]


# ---------------------------------------------------------------------------
# 2. _resolve_next_assignee
# ---------------------------------------------------------------------------


class TestResolveNextAssignee:
    """Unit-Tests für die Rotationslogik."""

    def test_rotation_3_users_5_terms(self):
        """3 User, 5 Aufrufe → zyklische Rotation."""
        chore = SimpleNamespace(
            rotation_order=["aaa", "bbb", "ccc"],
            next_rotation_index=0,
        )
        member_ids = {"aaa", "bbb", "ccc"}

        results = []
        for _ in range(5):
            results.append(_resolve_next_assignee(chore, member_ids))

        assert results == [
            uuid.UUID("aaa" * 4 + "aaa"[0:8].ljust(8, "a"))
            if False
            else uuid.UUID("00000000-0000-0000-0000-00000000" + "0aaa"[-4:])
            if False
            else None,  # placeholder, see below
        ]
        # Korrektur: UUIDs aus Strings müssen valide sein.
        # _resolve_next_assignee gibt uuid.UUID(candidate) zurück.
        # "aaa" ist kein valider UUID → wir nutzen echte UUIDs.
        pass  # Siehe test_rotation_3_users_5_terms_real unten

    def test_rotation_3_users_5_terms(self):
        """3 User, 5 Aufrufe → zyklische Rotation [a, b, c, a, b]."""
        uid_a = str(uuid.UUID(int=1))
        uid_b = str(uuid.UUID(int=2))
        uid_c = str(uuid.UUID(int=3))

        chore = SimpleNamespace(
            rotation_order=[uid_a, uid_b, uid_c],
            next_rotation_index=0,
        )
        member_ids = {uid_a, uid_b, uid_c}

        results = []
        for _ in range(5):
            results.append(_resolve_next_assignee(chore, member_ids))

        assert results == [
            uuid.UUID(int=1),
            uuid.UUID(int=2),
            uuid.UUID(int=3),
            uuid.UUID(int=1),
            uuid.UUID(int=2),
        ]
        assert chore.next_rotation_index == 5

    def test_rotation_skips_departed_member(self):
        """bbb ausgeschieden → wird übersprungen, Index rückt trotzdem weiter."""
        uid_a = str(uuid.UUID(int=1))
        uid_b = str(uuid.UUID(int=2))
        uid_c = str(uuid.UUID(int=3))

        chore = SimpleNamespace(
            rotation_order=[uid_a, uid_b, uid_c],
            next_rotation_index=0,
        )
        member_ids = {uid_a, uid_c}  # uid_b ausgeschieden

        first = _resolve_next_assignee(chore, member_ids)
        assert first == uuid.UUID(int=1)  # uid_a

        second = _resolve_next_assignee(chore, member_ids)
        assert second == uuid.UUID(int=3)  # uid_c (uid_b übersprungen)

        # Index rückt trotzdem 3 weiter nach 2 Aufrufen
        assert chore.next_rotation_index == 3

    def test_rotation_all_departed(self):
        """Alle User ausgeschieden → None."""
        uid_a = str(uuid.UUID(int=1))
        uid_b = str(uuid.UUID(int=2))

        chore = SimpleNamespace(
            rotation_order=[uid_a, uid_b],
            next_rotation_index=0,
        )
        member_ids = set()  # niemand mehr da

        result = _resolve_next_assignee(chore, member_ids)
        assert result is None


# ---------------------------------------------------------------------------
# 3. materialize_due_assignments (mit DB)
# ---------------------------------------------------------------------------


class TestMaterialize:
    """DB-gebundene Tests für die Lazy-Materialisierung."""

    def _setup_household_users_chore(self, db):
        """Erstellt Household + 2 User + wöchentliche Chore (Mi) für Tests."""
        household = Household(
            id=uuid.uuid4(),
            name="Test-HH",
            invite_code="MATTEST1",
            timezone="Europe/Zurich",
        )
        db.add(household)
        db.flush()

        user1 = User(
            id=uuid.uuid4(),
            email="mat_user1@test.com",
            password_hash=hash_password("pw"),
            display_name="MatUser1",
        )
        user2 = User(
            id=uuid.uuid4(),
            email="mat_user2@test.com",
            password_hash=hash_password("pw"),
            display_name="MatUser2",
        )
        db.add_all([user1, user2])
        db.flush()

        for u in [user1, user2]:
            db.add(
                HouseholdMember(
                    id=uuid.uuid4(),
                    household_id=household.id,
                    user_id=u.id,
                    role="member",
                )
            )
        db.flush()

        chore = Chore(
            id=uuid.uuid4(),
            household_id=household.id,
            title="Küche putzen",
            recurrence="weekly",
            weekday=2,  # Mittwoch
            rotation_order=[str(user1.id), str(user2.id)],
            next_rotation_index=0,
            anchor_date=date(2026, 8, 5),  # Mittwoch
            active=True,
            created_by_user_id=user1.id,
        )
        db.add(chore)
        db.commit()

        return household, user1, user2, chore

    def test_materialize_creates_assignments(self, db):
        """
        Chore weekly Mi, anchor=08-05, today=08-06 (Do).
        Horizon = 08-13. Erwartet: Assignments für 08-05 und 08-12.
        """
        household, user1, user2, chore = self._setup_household_users_chore(db)

        with patch(_PATCH_SERVICE, return_value=date(2026, 8, 6)):
            new = materialize_due_assignments(db, household)

        assert len(new) == 2
        due_dates = sorted(a.due_date for a in new)
        assert due_dates == [date(2026, 8, 5), date(2026, 8, 12)]

        # Rotation: user1 → user2
        assignments_sorted = sorted(new, key=lambda a: a.due_date)
        assert assignments_sorted[0].assigned_user_id == user1.id
        assert assignments_sorted[1].assigned_user_id == user2.id

    def test_materialize_idempotent(self, db):
        """Zweiter Aufruf erzeugt keine neuen Assignments."""
        household, user1, user2, chore = self._setup_household_users_chore(db)

        with patch(_PATCH_SERVICE, return_value=date(2026, 8, 6)):
            first_run = materialize_due_assignments(db, household)
        assert len(first_run) == 2

        with patch(_PATCH_SERVICE, return_value=date(2026, 8, 6)):
            second_run = materialize_due_assignments(db, household)
        assert len(second_run) == 0


# ===========================================================================
# TEIL 2 — API-Tests
# ===========================================================================


def _create_chore_body(user_a, user_a2=None, **overrides):
    """Standard-Body für Chore-Erstellung (weekly Mo)."""
    rotation = [str(user_a.id)]
    if user_a2:
        rotation.append(str(user_a2.id))
    body = {
        "title": "Staubsaugen",
        "recurrence": "weekly",
        "weekday": 0,  # Montag
        "rotation_order": rotation,
    }
    body.update(overrides)
    return body


def _create_chore_via_api(client, household_id, token, body, mock_date=MOCK_TODAY):
    """Erstellt eine Chore via POST und gibt die Response zurück."""
    with patch(_PATCH_ROUTER, return_value=mock_date):
        with patch(_PATCH_SERVICE, return_value=mock_date):
            return client.post(
                _chores_url(household_id),
                headers=_auth(token),
                json=body,
            )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestChoreCreate:
    """POST /api/households/{hid}/chores/"""

    def test_create_chore_success(self, client, household_a, token_a, user_a, user_a2):
        """POST valid → 201, alle Felder korrekt."""
        body = _create_chore_body(user_a, user_a2, description="Jede Woche Montag")
        resp = _create_chore_via_api(client, household_a.id, token_a, body)

        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Staubsaugen"
        assert data["description"] == "Jede Woche Montag"
        assert data["recurrence"] == "weekly"
        assert data["weekday"] == 0
        assert data["household_id"] == str(household_a.id)
        assert data["rotation_order"] == [str(user_a.id), str(user_a2.id)]
        assert data["next_rotation_index"] == 0
        assert data["active"] is True
        assert "anchor_date" in data
        assert "created_at" in data
        assert data["created_by_user_id"] == str(user_a.id)

    def test_create_chore_weekday_missing(
        self, client, household_a, token_a, user_a
    ):
        """Weekly ohne weekday → 422, code=CHORE_WEEKDAY_REQUIRED."""
        body = _create_chore_body(user_a, weekday=None)
        # Entferne weekday komplett
        body.pop("weekday", None)
        body["recurrence"] = "weekly"

        resp = _create_chore_via_api(client, household_a.id, token_a, body)
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "CHORE_WEEKDAY_REQUIRED"

    def test_create_chore_day_of_month_missing(
        self, client, household_a, token_a, user_a
    ):
        """Monthly ohne day_of_month → 422."""
        body = _create_chore_body(user_a, recurrence="monthly")
        body.pop("weekday", None)
        resp = _create_chore_via_api(client, household_a.id, token_a, body)

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "CHORE_DAY_OF_MONTH_REQUIRED"

    def test_create_chore_day_of_month_out_of_range(
        self, client, household_a, token_a, user_a
    ):
        """day_of_month=32 → 422."""
        body = _create_chore_body(
            user_a, recurrence="monthly", day_of_month=32
        )
        body.pop("weekday", None)
        resp = _create_chore_via_api(client, household_a.id, token_a, body)
        assert resp.status_code == 422

    def test_create_chore_foreign_user_in_rotation(
        self, client, household_a, token_a, user_a, user_b
    ):
        """rotation_order enthält User aus anderem Household → 422."""
        body = _create_chore_body(user_a, rotation_order=[str(user_a.id), str(user_b.id)])
        resp = _create_chore_via_api(client, household_a.id, token_a, body)

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "USERS_NOT_IN_HOUSEHOLD"

    def test_create_chore_duplicate_in_rotation(
        self, client, household_a, token_a, user_a
    ):
        """rotation_order=[user_a, user_a] → 422, CHORE_INVALID_ROTATION."""
        body = _create_chore_body(
            user_a, rotation_order=[str(user_a.id), str(user_a.id)]
        )
        resp = _create_chore_via_api(client, household_a.id, token_a, body)

        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "CHORE_INVALID_ROTATION"


class TestChoreListDelete:
    """GET / und DELETE /{chore_id}."""

    def test_list_chores(self, client, household_a, token_a, user_a, user_a2):
        """POST + GET → Chore in Liste."""
        body = _create_chore_body(user_a, user_a2)
        _create_chore_via_api(client, household_a.id, token_a, body)

        resp = client.get(
            _chores_url(household_a.id), headers=_auth(token_a)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert any(c["title"] == "Staubsaugen" for c in data)

    def test_delete_chore(self, client, household_a, token_a, user_a):
        """POST + DELETE → 204, danach GET → leer."""
        body = _create_chore_body(user_a)
        create_resp = _create_chore_via_api(client, household_a.id, token_a, body)
        chore_id = create_resp.json()["id"]

        del_resp = client.delete(
            f"{_chores_url(household_a.id)}{chore_id}",
            headers=_auth(token_a),
        )
        assert del_resp.status_code == 204

        list_resp = client.get(
            _chores_url(household_a.id), headers=_auth(token_a)
        )
        assert len(list_resp.json()) == 0

    def test_delete_chore_not_found(self, client, household_a, token_a):
        """DELETE mit random UUID → 404."""
        resp = client.delete(
            f"{_chores_url(household_a.id)}{uuid.uuid4()}",
            headers=_auth(token_a),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------


class TestAssignments:
    """GET /assignments, POST .../complete, .../uncomplete, PATCH (reassign)."""

    def test_get_assignments_materializes(
        self, client, household_a, token_a, user_a, user_a2
    ):
        """POST Chore + GET /assignments → materialisierte Assignments."""
        body = _create_chore_body(user_a, user_a2)
        _create_chore_via_api(client, household_a.id, token_a, body)

        with patch(_PATCH_ROUTER, return_value=MOCK_TODAY):
            with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
                resp = client.get(
                    _assignments_url(household_a.id),
                    headers=_auth(token_a),
                )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        # Alle haben eine due_date und chore_id
        for a in data:
            assert "due_date" in a
            assert "assigned_user_id" in a

    def test_get_assignments_idempotent(
        self, client, household_a, token_a, user_a, user_a2
    ):
        """Zweiter GET /assignments → gleiche Anzahl (keine Duplikate)."""
        body = _create_chore_body(user_a, user_a2)
        _create_chore_via_api(client, household_a.id, token_a, body)

        with patch(_PATCH_ROUTER, return_value=MOCK_TODAY):
            with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
                resp1 = client.get(
                    _assignments_url(household_a.id),
                    headers=_auth(token_a),
                )
                resp2 = client.get(
                    _assignments_url(household_a.id),
                    headers=_auth(token_a),
                )

        assert len(resp1.json()) == len(resp2.json())

    def test_get_assignments_window_too_large(
        self, client, household_a, token_a, user_a
    ):
        """from=2026-01-01 & to=2026-12-31 → 422, CHORE_WINDOW_TOO_LARGE."""
        body = _create_chore_body(user_a)
        _create_chore_via_api(client, household_a.id, token_a, body)

        with patch(_PATCH_ROUTER, return_value=MOCK_TODAY):
            with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
                resp = client.get(
                    _assignments_url(household_a.id),
                    headers=_auth(token_a),
                    params={"from": "2026-01-01", "to": "2026-12-31"},
                )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "CHORE_WINDOW_TOO_LARGE"

    def _create_and_get_assignment(self, client, household_a, token_a, user_a, user_a2=None):
        """Helper: Erstellt Chore und holt erstes Assignment."""
        body = _create_chore_body(user_a, user_a2)
        _create_chore_via_api(client, household_a.id, token_a, body)

        with patch(_PATCH_ROUTER, return_value=MOCK_TODAY):
            with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
                resp = client.get(
                    _assignments_url(household_a.id),
                    headers=_auth(token_a),
                )
        assignments = resp.json()
        assert len(assignments) >= 1
        return assignments[0]

    def test_complete_assignment(
        self, client, household_a, token_a, user_a
    ):
        """POST .../complete → completed_at gesetzt."""
        assignment = self._create_and_get_assignment(
            client, household_a, token_a, user_a
        )
        aid = assignment["id"]

        resp = client.post(
            f"{_assignments_url(household_a.id)}/{aid}/complete",
            headers=_auth(token_a),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["completed_at"] is not None
        assert data["completed_by_user_id"] == str(user_a.id)

    def test_complete_already_completed(
        self, client, household_a, token_a, user_a
    ):
        """Zweimal complete → 200, completed_at unverändert (idempotent)."""
        assignment = self._create_and_get_assignment(
            client, household_a, token_a, user_a
        )
        aid = assignment["id"]

        resp1 = client.post(
            f"{_assignments_url(household_a.id)}/{aid}/complete",
            headers=_auth(token_a),
        )
        first_completed_at = resp1.json()["completed_at"]

        resp2 = client.post(
            f"{_assignments_url(household_a.id)}/{aid}/complete",
            headers=_auth(token_a),
        )
        assert resp2.status_code == 200
        assert resp2.json()["completed_at"] == first_completed_at

    def test_uncomplete_assignment(
        self, client, household_a, token_a, user_a
    ):
        """complete + uncomplete → completed_at = None."""
        assignment = self._create_and_get_assignment(
            client, household_a, token_a, user_a
        )
        aid = assignment["id"]

        client.post(
            f"{_assignments_url(household_a.id)}/{aid}/complete",
            headers=_auth(token_a),
        )
        resp = client.post(
            f"{_assignments_url(household_a.id)}/{aid}/uncomplete",
            headers=_auth(token_a),
        )
        assert resp.status_code == 200
        assert resp.json()["completed_at"] is None
        assert resp.json()["completed_by_user_id"] is None

    def test_uncomplete_already_uncomplete(
        self, client, household_a, token_a, user_a
    ):
        """Uncomplete auf nie-completed → 200 (idempotent)."""
        assignment = self._create_and_get_assignment(
            client, household_a, token_a, user_a
        )
        aid = assignment["id"]

        resp = client.post(
            f"{_assignments_url(household_a.id)}/{aid}/uncomplete",
            headers=_auth(token_a),
        )
        assert resp.status_code == 200
        assert resp.json()["completed_at"] is None

    def test_reassign_assignment(
        self, client, household_a, token_a, user_a, user_a2
    ):
        """PATCH mit assigned_user_id = user_a2 → Zuweisung geändert."""
        assignment = self._create_and_get_assignment(
            client, household_a, token_a, user_a, user_a2
        )
        aid = assignment["id"]

        resp = client.patch(
            f"{_assignments_url(household_a.id)}/{aid}",
            headers=_auth(token_a),
            json={"assigned_user_id": str(user_a2.id)},
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_user_id"] == str(user_a2.id)


# ---------------------------------------------------------------------------
# Patch Recurrence löscht zukünftige Assignments
# ---------------------------------------------------------------------------


class TestPatchRecurrence:
    """PATCH /{chore_id} mit Recurrence-Änderung."""

    def test_patch_recurrence_deletes_future_assignments(
        self, client, household_a, token_a, user_a, user_a2
    ):
        """
        1. Chore weekly Mo erstellen (today=08-03, Mo)
        2. GET assignments → materialisiert 08-03 + 08-10
        3. Complete 08-03
        4. PATCH recurrence → monthly day_of_month=15
        5. GET assignments → 08-03 (completed) bleibt, 08-10 (future+uncompleted) weg
        """
        mock_monday = date(2026, 8, 3)  # Montag

        body = _create_chore_body(user_a, user_a2)
        create_resp = _create_chore_via_api(
            client, household_a.id, token_a, body, mock_date=mock_monday
        )
        assert create_resp.status_code == 201
        chore_id = create_resp.json()["id"]

        # GET assignments → materialisiert
        with patch(_PATCH_ROUTER, return_value=mock_monday):
            with patch(_PATCH_SERVICE, return_value=mock_monday):
                assign_resp = client.get(
                    _assignments_url(household_a.id),
                    headers=_auth(token_a),
                )
        assignments = assign_resp.json()
        assert len(assignments) >= 2

        # Finde Assignment für 08-03 und complete es
        a_0803 = next(a for a in assignments if a["due_date"] == "2026-08-03")
        client.post(
            f"{_assignments_url(household_a.id)}/{a_0803['id']}/complete",
            headers=_auth(token_a),
        )

        # PATCH recurrence → monthly
        with patch(_PATCH_ROUTER, return_value=mock_monday):
            with patch(_PATCH_SERVICE, return_value=mock_monday):
                patch_resp = client.patch(
                    f"{_chores_url(household_a.id)}{chore_id}",
                    headers=_auth(token_a),
                    json={
                        "recurrence": "monthly",
                        "day_of_month": 15,
                    },
                )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["recurrence"] == "monthly"

        # GET assignments → completed bleibt, zukünftige uncompleted weg
        with patch(_PATCH_ROUTER, return_value=mock_monday):
            with patch(_PATCH_SERVICE, return_value=mock_monday):
                final_resp = client.get(
                    _assignments_url(household_a.id),
                    headers=_auth(token_a),
                )
        final_assignments = final_resp.json()

        # 08-03 (completed) muss noch da sein
        completed = [a for a in final_assignments if a["completed_at"] is not None]
        assert len(completed) >= 1
        assert any(a["due_date"] == "2026-08-03" for a in completed)

        # 08-10 (uncompleted, future) darf nicht mehr da sein
        uncompleted_future = [
            a
            for a in final_assignments
            if a["completed_at"] is None and a["due_date"] == "2026-08-10"
        ]
        assert len(uncompleted_future) == 0


# ---------------------------------------------------------------------------
# Socket-Events
# ---------------------------------------------------------------------------


class TestSocketEvents:
    """Prüft, dass die richtigen Socket-Events emittiert werden."""

    def test_socket_events(
        self, client, household_a, token_a, user_a, user_a2, _mock_socket_emit
    ):
        """
        Kompletter Lifecycle:
        1. POST Chore → chore_created
        2. PATCH Chore → chore_updated
        3. GET /assignments (Materialisierung) → chore_assignment_created
        4. POST .../complete → chore_assignment_updated
        5. DELETE Chore → chore_deleted
        """
        _mock_socket_emit.reset_mock()

        # 1. POST Chore
        body = _create_chore_body(user_a, user_a2)
        create_resp = _create_chore_via_api(client, household_a.id, token_a, body)
        assert create_resp.status_code == 201
        chore_id = create_resp.json()["id"]

        created_calls = [
            c for c in _mock_socket_emit.call_args_list
            if c[0][1] == "chore_created"
        ]
        assert len(created_calls) >= 1
        assert created_calls[0][0][2]["title"] == "Staubsaugen"

        # 2. PATCH Chore
        _mock_socket_emit.reset_mock()
        with patch(_PATCH_ROUTER, return_value=MOCK_TODAY):
            with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
                client.patch(
                    f"{_chores_url(household_a.id)}{chore_id}",
                    headers=_auth(token_a),
                    json={"title": "Staubsaugen (aktualisiert)"},
                )
        updated_calls = [
            c for c in _mock_socket_emit.call_args_list
            if c[0][1] == "chore_updated"
        ]
        assert len(updated_calls) >= 1

        # 3. GET /assignments → chore_assignment_created
        _mock_socket_emit.reset_mock()
        with patch(_PATCH_ROUTER, return_value=MOCK_TODAY):
            with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
                assign_resp = client.get(
                    _assignments_url(household_a.id),
                    headers=_auth(token_a),
                )
        assignments = assign_resp.json()
        assignment_created_calls = [
            c for c in _mock_socket_emit.call_args_list
            if c[0][1] == "chore_assignment_created"
        ]
        # Sollte mindestens 1 neues Assignment materialisiert haben
        assert len(assignment_created_calls) >= 1

        # 4. POST .../complete → chore_assignment_updated
        _mock_socket_emit.reset_mock()
        aid = assignments[0]["id"]
        client.post(
            f"{_assignments_url(household_a.id)}/{aid}/complete",
            headers=_auth(token_a),
        )
        complete_calls = [
            c for c in _mock_socket_emit.call_args_list
            if c[0][1] == "chore_assignment_updated"
        ]
        assert len(complete_calls) >= 1

        # 5. DELETE Chore → chore_deleted
        _mock_socket_emit.reset_mock()
        del_resp = client.delete(
            f"{_chores_url(household_a.id)}{chore_id}",
            headers=_auth(token_a),
        )
        assert del_resp.status_code == 204
        deleted_calls = [
            c for c in _mock_socket_emit.call_args_list
            if c[0][1] == "chore_deleted"
        ]
        assert len(deleted_calls) == 1
        assert deleted_calls[0][0][2]["id"] == chore_id


# ---------------------------------------------------------------------------
# Backfill-Limit
# ---------------------------------------------------------------------------


class TestBackfillLimit:
    """Prüft, dass die Backfill-Begrenzung auf 14 Tage greift."""

    def _setup_old_chore(self, db):
        """Erstellt Household + 2 User + wöchentliche Chore (Mi) mit anchor_date 60 Tage zurück."""
        household = Household(
            id=uuid.uuid4(),
            name="Backfill-HH",
            invite_code="BKFL0001",
            timezone="Europe/Zurich",
        )
        db.add(household)
        db.flush()

        user1 = User(
            id=uuid.uuid4(),
            email="backfill_u1@test.com",
            password_hash=hash_password("pw"),
            display_name="BF-User1",
        )
        user2 = User(
            id=uuid.uuid4(),
            email="backfill_u2@test.com",
            password_hash=hash_password("pw"),
            display_name="BF-User2",
        )
        db.add_all([user1, user2])
        db.flush()

        for u in [user1, user2]:
            db.add(
                HouseholdMember(
                    id=uuid.uuid4(),
                    household_id=household.id,
                    user_id=u.id,
                    role="member",
                )
            )
        db.flush()

        # anchor_date = 2026-06-10 (Mittwoch), ca. 57 Tage vor MOCK_TODAY
        chore = Chore(
            id=uuid.uuid4(),
            household_id=household.id,
            title="Alte Chore",
            recurrence="weekly",
            weekday=2,  # Mittwoch
            rotation_order=[str(user1.id), str(user2.id)],
            next_rotation_index=0,
            anchor_date=date(2026, 6, 10),  # Mittwoch, ~60 Tage zurück
            active=True,
            created_by_user_id=user1.id,
        )
        db.add(chore)
        db.commit()

        return household, user1, user2, chore

    def test_backfill_limited_to_14_days(self, db):
        """
        Chore weekly Mi, anchor=2026-06-10, today=2026-08-06 (Do).
        Ohne Backfill-Limit wären 9 Mittwoche seit 10.06. fällig.
        Mit Limit (today-14d = 2026-07-23) werden nur Mittwoche im
        Fenster [2026-07-23, 2026-08-13] materialisiert:
        29.07, 05.08, 12.08 → 3 Assignments.
        Rotation rückt nur 3× weiter → next_rotation_index == 3.
        """
        household, user1, user2, chore = self._setup_old_chore(db)

        with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
            new = materialize_due_assignments(db, household)

        # Erwartete Mittwoche: 29.07, 05.08, 12.08
        assert len(new) == 3
        due_dates = sorted(a.due_date for a in new)
        assert due_dates == [
            date(2026, 7, 29),
            date(2026, 8, 5),
            date(2026, 8, 12),
        ]

        # Rotation: nur 3 Schritte weiter (nicht 9)
        db.refresh(chore)
        assert chore.next_rotation_index == 3
