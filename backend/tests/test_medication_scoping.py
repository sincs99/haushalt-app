"""
Multi-Tenant Scoping Tests für Medications.

Stellt sicher, dass User NUR auf Medikamente ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""


# ---------------------------------------------------------------------------
# Positiv: User kann Medikament erstellen → 201
# ---------------------------------------------------------------------------


def test_user_can_create_medication(client, household_a, token_a, pet_a):
    """POST Medikament im eigenen Household liefert 201."""
    resp = client.post(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/medications",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Flohschutz", "dosage": "1 Pipette", "schedule": "Monatlich"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Flohschutz"
    assert data["dosage"] == "1 Pipette"
    assert data["pet_id"] == str(pet_a.id)
    assert data["household_id"] == str(household_a.id)
    assert data["active"] is True


# ---------------------------------------------------------------------------
# Positiv: User kann Medikamente auflisten → 200
# ---------------------------------------------------------------------------


def test_user_can_list_medications(
    client, household_a, token_a, pet_a, medication_a
):
    """GET Medikamente im eigenen Household liefert 200."""
    resp = client.get(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/medications",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(m["id"] == str(medication_a.id) for m in data)


# ---------------------------------------------------------------------------
# Positiv: User kann Medikament aktualisieren → 200
# ---------------------------------------------------------------------------


def test_user_can_update_medication(
    client, household_a, token_a, pet_a, medication_a
):
    """PATCH auf eigenes Medikament liefert 200."""
    resp = client.patch(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/medications/{medication_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Entwurmung Plus", "active": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Entwurmung Plus"
    assert data["active"] is False


# ---------------------------------------------------------------------------
# Positiv: User kann Medikament löschen → 204
# ---------------------------------------------------------------------------


def test_user_can_delete_medication(
    client, household_a, token_a, pet_a, medication_a
):
    """DELETE auf eigenes Medikament liefert 204."""
    resp = client.delete(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/medications/{medication_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Positiv: User kann Medikament als gegeben markieren → 201
# ---------------------------------------------------------------------------


def test_user_can_give_medication(
    client, household_a, token_a, pet_a, medication_a
):
    """POST give auf eigenes Medikament liefert 201."""
    resp = client.post(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/medications/{medication_a.id}/give",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["medication_id"] == str(medication_a.id)
    assert data["household_id"] == str(household_a.id)
    assert "given_at" in data
    assert "given_by_user_id" in data


# ---------------------------------------------------------------------------
# Positiv: User kann Medikamenten-Log einsehen → 200
# ---------------------------------------------------------------------------


def test_user_can_view_medication_log(
    client, household_a, token_a, pet_a, medication_a
):
    """GET log nach give liefert 200 mit Einträgen."""
    # Erst eine Gabe erfassen
    client.post(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/medications/{medication_a.id}/give",
        headers={"Authorization": f"Bearer {token_a}"},
    )

    resp = client.get(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/medications/{medication_a.id}/log",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["medication_id"] == str(medication_a.id)


# ---------------------------------------------------------------------------
# Negativ: User kann kein Medikament in fremdem Household erstellen → 403
# ---------------------------------------------------------------------------


def test_user_cannot_create_medication_in_other_household(
    client, household_b, token_a, pet_b, user_b
):
    """POST Medikament in fremdem Household liefert 403."""
    resp = client.post(
        f"/api/households/{household_b.id}/pets/{pet_b.id}/medications",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Hacker-Medikament"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User kann kein Medikament in fremdem Household geben → 403
# ---------------------------------------------------------------------------


def test_user_cannot_give_medication_in_other_household(
    client, household_b, token_a, pet_b, medication_b
):
    """POST give in fremdem Household liefert 403."""
    resp = client.post(
        f"/api/households/{household_b.id}/pets/{pet_b.id}/medications/{medication_b.id}/give",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User kann keine Medikamente in fremdem Household auflisten → 403
# ---------------------------------------------------------------------------


def test_user_cannot_list_medications_of_other_household(
    client, household_b, token_a, pet_b, medication_b
):
    """GET Medikamente in fremdem Household liefert 403."""
    resp = client.get(
        f"/api/households/{household_b.id}/pets/{pet_b.id}/medications",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403
