"""
Multi-Tenant Scoping Tests für Pets.

Stellt sicher, dass User NUR auf Pets ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""


# ---------------------------------------------------------------------------
# Positiv: User A listet eigene Pets → 200
# ---------------------------------------------------------------------------


def test_user_a_can_list_own_pets(client, household_a, token_a, pet_a):
    """GET eigene Pets liefert 200 und enthält das eigene Pet."""
    resp = client.get(
        f"/api/households/{household_a.id}/pets/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(p["id"] == str(pet_a.id) for p in data)


# ---------------------------------------------------------------------------
# Negativ: User A listet Pets von Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_list_other_household_pets(
    client, household_b, token_a, pet_b
):
    """GET fremde Pets liefert 403 Forbidden."""
    resp = client.get(
        f"/api/households/{household_b.id}/pets/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: User A erstellt Pet → 201
# ---------------------------------------------------------------------------


def test_user_a_can_create_pet(client, household_a, token_a):
    """POST in eigenem Household liefert 201."""
    resp = client.post(
        f"/api/households/{household_a.id}/pets/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Mimi", "species": "cat"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Mimi"
    assert data["species"] == "cat"
    assert data["household_id"] == str(household_a.id)


# ---------------------------------------------------------------------------
# Negativ: User A erstellt Pet in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_create_pet_in_other_household(
    client, household_b, token_a, user_b
):
    """POST in fremden Household liefert 403 Forbidden."""
    resp = client.post(
        f"/api/households/{household_b.id}/pets/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Hacker-Pet", "species": "cat"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: User A aktualisiert eigenes Pet → 200
# ---------------------------------------------------------------------------


def test_user_a_can_update_own_pet(client, household_a, token_a, pet_a):
    """PATCH auf eigenes Pet liefert 200."""
    resp = client.patch(
        f"/api/households/{household_a.id}/pets/{pet_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Luna Updated"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Luna Updated"


# ---------------------------------------------------------------------------
# Negativ: User A aktualisiert Pet in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_update_other_household_pet(
    client, household_b, token_a, pet_b
):
    """PATCH auf fremdes Pet liefert 403 Forbidden."""
    resp = client.patch(
        f"/api/households/{household_b.id}/pets/{pet_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Gehacktes Pet"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: User A löscht eigenes Pet → 204
# ---------------------------------------------------------------------------


def test_user_a_can_delete_own_pet(client, household_a, token_a, pet_a):
    """DELETE auf eigenes Pet liefert 204."""
    resp = client.delete(
        f"/api/households/{household_a.id}/pets/{pet_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Negativ: User A löscht Pet in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_delete_other_household_pet(
    client, household_b, token_a, pet_b
):
    """DELETE auf fremdes Pet liefert 403 Forbidden."""
    resp = client.delete(
        f"/api/households/{household_b.id}/pets/{pet_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403
