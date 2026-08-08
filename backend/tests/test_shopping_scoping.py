"""
Multi-Tenant Scoping Tests für Shopping-Items und Shopping-Lists.

Stellt sicher, dass User NUR auf Shopping-Items/-Listen ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""

import uuid


# ===========================================================================
# Shopping Items — Positiv
# ===========================================================================


def test_user_a_can_read_own_shopping_items(
    client, household_a, token_a, shopping_item_a
):
    """GET eigene Shopping-Items liefert 200 und enthält das eigene Item."""
    resp = client.get(
        f"/api/households/{household_a.id}/shopping-items/?include_checked=true",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(item["id"] == str(shopping_item_a.id) for item in data)


# ===========================================================================
# Shopping Items — Negativ (Cross-Household)
# ===========================================================================


def test_user_a_cannot_read_other_household_shopping(
    client, household_b, token_a, shopping_item_b
):
    """GET fremde Shopping-Items liefert 403 Forbidden."""
    resp = client.get(
        f"/api/households/{household_b.id}/shopping-items/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_create_in_other_household(
    client, household_b, token_a, user_b, shopping_list_b
):
    """POST in fremden Household liefert 403 Forbidden."""
    resp = client.post(
        f"/api/households/{household_b.id}/shopping-items/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Hacker-Item", "quantity": "1", "list_id": str(shopping_list_b.id)},
    )
    assert resp.status_code == 403


def test_user_a_cannot_patch_other_household_item(
    client, household_b, token_a, shopping_item_b
):
    """PATCH auf fremdes Item liefert 403 Forbidden."""
    resp = client.patch(
        f"/api/households/{household_b.id}/shopping-items/{shopping_item_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Gehacktes Item"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_delete_other_household_item(
    client, household_b, token_a, shopping_item_b
):
    """DELETE auf fremdes Item liefert 403 Forbidden."""
    resp = client.delete(
        f"/api/households/{household_b.id}/shopping-items/{shopping_item_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ===========================================================================
# Shopping Lists — Scoping
# ===========================================================================


def test_user_a_can_list_own_shopping_lists(
    client, household_a, token_a, shopping_list_a
):
    """GET eigene Shopping-Listen liefert 200."""
    resp = client.get(
        f"/api/households/{household_a.id}/shopping-lists/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(lst["id"] == str(shopping_list_a.id) for lst in data)


def test_user_a_cannot_list_other_household_lists(
    client, household_b, token_a, shopping_list_b
):
    """GET fremde Shopping-Listen liefert 403."""
    resp = client.get(
        f"/api/households/{household_b.id}/shopping-lists/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_create_list_in_other_household(
    client, household_b, token_a
):
    """POST Liste in fremdem Household liefert 403."""
    resp = client.post(
        f"/api/households/{household_b.id}/shopping-lists/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Hacker-Liste"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_delete_other_household_list(
    client, household_b, token_a, shopping_list_b
):
    """DELETE fremde Liste liefert 403."""
    resp = client.delete(
        f"/api/households/{household_b.id}/shopping-lists/{shopping_list_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ===========================================================================
# Konsistenz: list_id ↔ household_id
# ===========================================================================


def test_item_cannot_use_list_from_other_household(
    client, household_a, token_a, shopping_list_b
):
    """Item kann NICHT mit list_id einer Liste aus fremdem Haushalt erstellt werden → 400."""
    resp = client.post(
        f"/api/households/{household_a.id}/shopping-items/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Infiltration-Item",
            "list_id": str(shopping_list_b.id),
        },
    )
    assert resp.status_code == 400
    assert "list_id" in resp.json()["detail"].lower()


# ===========================================================================
# DELETE-Schutz für Listen
# ===========================================================================


def test_delete_non_empty_list_without_force_returns_409(
    client, household_a, token_a, shopping_list_a, shopping_item_a
):
    """DELETE auf nicht-leere Liste ohne ?force=true liefert 409."""
    resp = client.delete(
        f"/api/households/{household_a.id}/shopping-lists/{shopping_list_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 409


def test_delete_non_empty_list_with_force_returns_204(
    client, household_a, token_a, shopping_list_a, shopping_item_a
):
    """DELETE auf nicht-leere Liste mit ?force=true liefert 204."""
    resp = client.delete(
        f"/api/households/{household_a.id}/shopping-lists/{shopping_list_a.id}?force=true",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 204


def test_delete_empty_list_returns_204(
    client, household_a, token_a, shopping_list_a
):
    """DELETE auf leere Liste liefert 204."""
    resp = client.delete(
        f"/api/households/{household_a.id}/shopping-lists/{shopping_list_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 204


# ===========================================================================
# assigned_to_user_id Validierung
# ===========================================================================


def test_assign_item_to_non_member_returns_400(
    client, household_a, token_a, shopping_list_a, user_b
):
    """assigned_to_user_id mit User aus fremdem Haushalt → 400."""
    resp = client.post(
        f"/api/households/{household_a.id}/shopping-items/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Test-Item",
            "list_id": str(shopping_list_a.id),
            "assigned_to_user_id": str(user_b.id),
        },
    )
    assert resp.status_code == 400
    assert "assigned_to_user_id" in resp.json()["detail"].lower()


def test_assign_item_to_own_member_succeeds(
    client, household_a, token_a, shopping_list_a, user_a
):
    """assigned_to_user_id mit eigenem Mitglied → 201."""
    resp = client.post(
        f"/api/households/{household_a.id}/shopping-items/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Zugewiesenes Item",
            "list_id": str(shopping_list_a.id),
            "assigned_to_user_id": str(user_a.id),
        },
    )
    assert resp.status_code == 201
    assert resp.json()["assigned_to_user_id"] == str(user_a.id)
