"""
Multi-Tenant Scoping Tests für Feeding Logs.

Stellt sicher, dass Fütterungen korrekt erfasst, duplikat-geschützt und
auf den eigenen Household beschränkt sind.
"""

import uuid


# ---------------------------------------------------------------------------
# Positiv: User kann Fütterung erstellen → 201
# ---------------------------------------------------------------------------


def test_user_can_create_feeding(client, household_a, token_a, pet_a):
    """POST Fütterung im eigenen Household liefert 201."""
    resp = client.post(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/feedings",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"slot": "morning"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["pet_id"] == str(pet_a.id)
    assert data["slot"] == "morning"
    assert data["household_id"] == str(household_a.id)


# ---------------------------------------------------------------------------
# Duplikat: Gleiche Fütterung nochmal → 409
# ---------------------------------------------------------------------------


def test_feeding_duplicate_returns_409(client, household_a, token_a, pet_a):
    """Zweite Fütterung für gleichen Slot+Tag liefert 409 Conflict."""
    url = f"/api/households/{household_a.id}/pets/{pet_a.id}/feedings"
    headers = {"Authorization": f"Bearer {token_a}"}

    # Erste Fütterung → 201
    resp1 = client.post(url, headers=headers, json={"slot": "morning"})
    assert resp1.status_code == 201

    # Zweite Fütterung gleicher Slot → 409
    resp2 = client.post(url, headers=headers, json={"slot": "morning"})
    assert resp2.status_code == 409


# ---------------------------------------------------------------------------
# Positiv: User kann Fütterung löschen (undo) → 204
# ---------------------------------------------------------------------------


def test_user_can_undo_feeding(client, household_a, token_a, pet_a):
    """DELETE einer eigenen Fütterung liefert 204."""
    # Erst erstellen
    resp = client.post(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/feedings",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"slot": "evening"},
    )
    assert resp.status_code == 201
    feeding_id = resp.json()["id"]

    # Dann löschen
    resp2 = client.delete(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/feedings/{feeding_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp2.status_code == 204


# ---------------------------------------------------------------------------
# Negativ: User kann fremdes Pet nicht füttern → 403
# ---------------------------------------------------------------------------


def test_user_cannot_feed_other_household_pet(
    client, household_b, token_a, pet_b
):
    """POST Fütterung in fremdem Household liefert 403 Forbidden."""
    resp = client.post(
        f"/api/households/{household_b.id}/pets/{pet_b.id}/feedings",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"slot": "morning"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: Feeding-Status liefert heutige Daten → 200
# ---------------------------------------------------------------------------


def test_feeding_status_returns_today(client, household_a, token_a, pet_a):
    """GET feeding-status liefert 200 mit korrekten Daten für heute."""
    headers = {"Authorization": f"Bearer {token_a}"}

    # Erst ein Feeding erstellen
    resp = client.post(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/feedings",
        headers=headers,
        json={"slot": "morning"},
    )
    assert resp.status_code == 201

    # Dann Status abrufen
    resp2 = client.get(
        f"/api/households/{household_a.id}/pets/feeding-status",
        headers=headers,
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    # Finde den Eintrag für pet_a
    pet_status = next(
        (s for s in data if s["pet_id"] == str(pet_a.id)), None
    )
    assert pet_status is not None
    assert pet_status["pet_name"] == "Luna"
    assert pet_status["morning"] is not None
    assert pet_status["morning"]["slot"] == "morning"
    assert pet_status["evening"] is None
