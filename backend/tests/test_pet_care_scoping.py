"""
Multi-Tenant Scoping Tests für PetCareTask.
Stellt sicher, dass Cross-Household-Zugriffe mit 403 abgelehnt werden.
+ Funktionstest für /complete.
"""

from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Helper: Care-Task inline erstellen
# ---------------------------------------------------------------------------


def _create_care_task(client, household_id, pet_id, token, **overrides):
    """Erstellt einen Care-Task per POST und gibt die Response-Daten zurück."""
    payload = {
        "name": overrides.get("name", "Wurmkur"),
        "interval_days": overrides.get("interval_days", 90),
        "next_due_at": overrides.get("next_due_at", str(date.today() + timedelta(days=30))),
    }
    resp = client.post(
        f"/api/households/{household_id}/pets/{pet_id}/care-tasks/",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert resp.status_code == 201, f"Care-Task creation failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Positiv: User kann eigene Care-Tasks auflisten → 200
# ---------------------------------------------------------------------------


def test_user_a_can_list_own_care_tasks(
    client, household_a, token_a, pet_a, user_a
):
    """GET Care-Tasks im eigenen Household liefert 200."""
    _create_care_task(client, household_a.id, pet_a.id, token_a)

    resp = client.get(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/care-tasks/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["name"] == "Wurmkur"


# ---------------------------------------------------------------------------
# Negativ: User kann keine Care-Tasks in fremdem Household auflisten → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_list_other_household_care_tasks(
    client, household_b, token_a, pet_b, user_a, user_b
):
    """GET Care-Tasks in fremdem Household liefert 403."""
    resp = client.get(
        f"/api/households/{household_b.id}/pets/{pet_b.id}/care-tasks/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: User kann Care-Task erstellen → 201
# ---------------------------------------------------------------------------


def test_user_a_can_create_care_task(
    client, household_a, token_a, pet_a, user_a
):
    """POST Care-Task im eigenen Household liefert 201 mit korrekten Feldern."""
    next_due = str(date.today() + timedelta(days=60))
    resp = client.post(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/care-tasks/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Impfung",
            "interval_days": 365,
            "next_due_at": next_due,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Impfung"
    assert data["interval_days"] == 365
    assert data["next_due_at"] == next_due
    assert data["pet_id"] == str(pet_a.id)
    assert data["household_id"] == str(household_a.id)
    assert data["last_done_at"] is None
    assert data["notified_at"] is None
    assert "id" in data
    assert "created_at" in data


# ---------------------------------------------------------------------------
# Negativ: User kann keinen Care-Task in fremdem Household erstellen → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_create_care_task_in_other_household(
    client, household_b, token_a, pet_b, user_a, user_b
):
    """POST Care-Task in fremdem Household liefert 403."""
    resp = client.post(
        f"/api/households/{household_b.id}/pets/{pet_b.id}/care-tasks/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Hacker-Task",
            "interval_days": 30,
            "next_due_at": str(date.today()),
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: User kann eigenen Care-Task updaten → 200
# ---------------------------------------------------------------------------


def test_user_a_can_update_own_care_task(
    client, household_a, token_a, pet_a, user_a
):
    """PATCH auf eigenen Care-Task liefert 200."""
    task = _create_care_task(client, household_a.id, pet_a.id, token_a)

    resp = client.patch(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/care-tasks/{task['id']}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Krallen schneiden", "interval_days": 14},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Krallen schneiden"
    assert data["interval_days"] == 14


# ---------------------------------------------------------------------------
# Negativ: User kann keinen Care-Task in fremdem Household updaten → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_update_other_household_care_task(
    client, household_a, household_b, token_a, token_b, pet_a, pet_b, user_a, user_b
):
    """PATCH auf Care-Task in fremdem Household liefert 403."""
    task = _create_care_task(client, household_b.id, pet_b.id, token_b)

    resp = client.patch(
        f"/api/households/{household_b.id}/pets/{pet_b.id}/care-tasks/{task['id']}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Hacker-Update"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: User kann eigenen Care-Task löschen → 204
# ---------------------------------------------------------------------------


def test_user_a_can_delete_own_care_task(
    client, household_a, token_a, pet_a, user_a
):
    """DELETE auf eigenen Care-Task liefert 204."""
    task = _create_care_task(client, household_a.id, pet_a.id, token_a)

    resp = client.delete(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/care-tasks/{task['id']}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Negativ: User kann keinen Care-Task in fremdem Household löschen → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_delete_other_household_care_task(
    client, household_a, household_b, token_a, token_b, pet_a, pet_b, user_a, user_b
):
    """DELETE auf Care-Task in fremdem Household liefert 403."""
    task = _create_care_task(client, household_b.id, pet_b.id, token_b)

    resp = client.delete(
        f"/api/households/{household_b.id}/pets/{pet_b.id}/care-tasks/{task['id']}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Funktionstest: /complete setzt last_done_at und berechnet next_due_at
# ---------------------------------------------------------------------------


def test_complete_care_task_updates_dates(
    client, household_a, token_a, pet_a, user_a
):
    """POST /complete setzt last_done_at=heute, next_due_at=heute+interval_days, notified_at=None."""
    interval = 90
    task = _create_care_task(
        client,
        household_a.id,
        pet_a.id,
        token_a,
        name="Entwurmung",
        interval_days=interval,
        next_due_at=str(date.today()),
    )

    resp = client.post(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/care-tasks/{task['id']}/complete",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()

    # Household timezone ist Europe/Zurich (default), also "heute" in der Test-Umgebung
    # Da die Tests mit SQLite in-memory laufen, ist das Datum "heute" in der Household-TZ
    today = date.today()
    expected_next_due = today + timedelta(days=interval)

    assert data["last_done_at"] == str(today)
    assert data["next_due_at"] == str(expected_next_due)
    assert data["notified_at"] is None
