"""
Multi-Tenant Scoping Tests für Chores.

Stellt sicher, dass User NUR auf Chores/Assignments ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""

import uuid
from datetime import date
from unittest.mock import patch

import pytest

from app.models import Chore, ChoreAssignment


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

MOCK_TODAY = date(2026, 8, 6)

_PATCH_SERVICE = "app.services.chore_scheduler.today_in_tz"
_PATCH_ROUTER = "app.routers.chores.today_in_tz"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _chores_url(household_id) -> str:
    return f"/api/households/{household_id}/chores/"


def _assignments_url(household_id) -> str:
    return f"/api/households/{household_id}/chores/assignments"


# ---------------------------------------------------------------------------
# Fixtures: Chore + Assignment in Household B
# ---------------------------------------------------------------------------


@pytest.fixture()
def chore_b(db, household_b, user_b) -> Chore:
    """Chore in Household B (direkt in DB erstellt)."""
    chore = Chore(
        id=uuid.uuid4(),
        household_id=household_b.id,
        title="Bad putzen (HH-B)",
        recurrence="weekly",
        weekday=2,  # Mittwoch
        rotation_order=[str(user_b.id)],
        next_rotation_index=0,
        anchor_date=date(2026, 8, 5),
        active=True,
        created_by_user_id=user_b.id,
    )
    db.add(chore)
    db.commit()
    db.refresh(chore)
    return chore


@pytest.fixture()
def assignment_b(db, household_b, chore_b, user_b) -> ChoreAssignment:
    """Assignment in Household B (direkt in DB erstellt)."""
    assignment = ChoreAssignment(
        id=uuid.uuid4(),
        household_id=household_b.id,
        chore_id=chore_b.id,
        assigned_user_id=user_b.id,
        due_date=date(2026, 8, 5),
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


# ---------------------------------------------------------------------------
# Positiv: User A liest eigene Chores → 200
# ---------------------------------------------------------------------------


def test_user_a_can_read_own_chores(client, household_a, token_a, user_a, db):
    """GET eigene Chores liefert 200."""
    # Chore erstellen via API
    with patch(_PATCH_ROUTER, return_value=MOCK_TODAY):
        with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
            client.post(
                _chores_url(household_a.id),
                headers=_auth(token_a),
                json={
                    "title": "Eigene Chore",
                    "recurrence": "weekly",
                    "weekday": 0,
                    "rotation_order": [str(user_a.id)],
                },
            )

    resp = client.get(
        _chores_url(household_a.id),
        headers=_auth(token_a),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(c["title"] == "Eigene Chore" for c in data)


# ---------------------------------------------------------------------------
# Negativ: Cross-Household-Zugriffe → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_read_other_household_chores(
    client, household_b, token_a, chore_b
):
    """GET fremde Chores liefert 403."""
    resp = client.get(
        _chores_url(household_b.id),
        headers=_auth(token_a),
    )
    assert resp.status_code == 403


def test_user_a_cannot_create_chore_in_other_household(
    client, household_b, token_a, user_b
):
    """POST in fremden Household liefert 403."""
    with patch(_PATCH_ROUTER, return_value=MOCK_TODAY):
        with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
            resp = client.post(
                _chores_url(household_b.id),
                headers=_auth(token_a),
                json={
                    "title": "Hacker-Chore",
                    "recurrence": "weekly",
                    "weekday": 0,
                    "rotation_order": [str(user_b.id)],
                },
            )
    assert resp.status_code == 403


def test_user_a_cannot_patch_chore_in_other_household(
    client, household_b, token_a, chore_b
):
    """PATCH auf fremde Chore liefert 403."""
    with patch(_PATCH_ROUTER, return_value=MOCK_TODAY):
        with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
            resp = client.patch(
                f"{_chores_url(household_b.id)}{chore_b.id}",
                headers=_auth(token_a),
                json={"title": "Gehackte Chore"},
            )
    assert resp.status_code == 403


def test_user_a_cannot_delete_chore_in_other_household(
    client, household_b, token_a, chore_b
):
    """DELETE auf fremde Chore liefert 403."""
    resp = client.delete(
        f"{_chores_url(household_b.id)}{chore_b.id}",
        headers=_auth(token_a),
    )
    assert resp.status_code == 403


def test_user_a_cannot_read_assignments_in_other_household(
    client, household_b, token_a, chore_b
):
    """GET /assignments in fremdem Household liefert 403."""
    with patch(_PATCH_ROUTER, return_value=MOCK_TODAY):
        with patch(_PATCH_SERVICE, return_value=MOCK_TODAY):
            resp = client.get(
                _assignments_url(household_b.id),
                headers=_auth(token_a),
            )
    assert resp.status_code == 403


def test_user_a_cannot_complete_assignment_in_other_household(
    client, household_b, token_a, assignment_b
):
    """POST .../complete in fremdem Household liefert 403."""
    resp = client.post(
        f"{_assignments_url(household_b.id)}/{assignment_b.id}/complete",
        headers=_auth(token_a),
    )
    assert resp.status_code == 403


def test_user_a_cannot_reassign_in_other_household(
    client, household_b, token_a, assignment_b, user_b
):
    """PATCH assignment in fremdem Household liefert 403."""
    resp = client.patch(
        f"{_assignments_url(household_b.id)}/{assignment_b.id}",
        headers=_auth(token_a),
        json={"assigned_user_id": str(user_b.id)},
    )
    assert resp.status_code == 403
