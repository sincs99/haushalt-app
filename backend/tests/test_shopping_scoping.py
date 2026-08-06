"""
Multi-Tenant Scoping Tests für Shopping-Items.

Stellt sicher, dass User NUR auf Shopping-Items ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""

import uuid


# ---------------------------------------------------------------------------
# Positiv: User A liest eigene Shopping-Items → 200
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Negativ: User A liest Shopping-Items von Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_read_other_household_shopping(
    client, household_b, token_a, shopping_item_b
):
    """GET fremde Shopping-Items liefert 403 Forbidden."""
    resp = client.get(
        f"/api/households/{household_b.id}/shopping-items/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A erstellt Item in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_create_in_other_household(
    client, household_b, token_a, user_b
):
    """POST in fremden Household liefert 403 Forbidden."""
    resp = client.post(
        f"/api/households/{household_b.id}/shopping-items/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Hacker-Item", "quantity": "1"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A patcht Item in Household B → 403
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Negativ: User A löscht Item in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_delete_other_household_item(
    client, household_b, token_a, shopping_item_b
):
    """DELETE auf fremdes Item liefert 403 Forbidden."""
    resp = client.delete(
        f"/api/households/{household_b.id}/shopping-items/{shopping_item_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403
