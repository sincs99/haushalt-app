"""
Multi-Tenant Scoping Tests für das Food-Modul (Recipes + MealPlan).

Stellt sicher, dass User NUR auf Rezepte und Wochenpläne ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""

import uuid


# ===========================================================================
# Rezepte — Positiv
# ===========================================================================


def test_user_a_can_read_own_recipes(
    client, household_a, token_a, recipe_a
):
    """GET eigene Rezepte liefert 200 und enthält das eigene Rezept."""
    resp = client.get(
        f"/api/households/{household_a.id}/recipes/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(r["id"] == str(recipe_a.id) for r in data)


def test_user_a_can_create_recipe(
    client, household_a, token_a
):
    """POST eigenes Rezept liefert 201."""
    resp = client.post(
        f"/api/households/{household_a.id}/recipes/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Neues Rezept",
            "servings": 2,
            "ingredients": ["Zutat A", "Zutat B"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Neues Rezept"
    assert data["household_id"] == str(household_a.id)


# ===========================================================================
# Rezepte — Negativ (Cross-Household)
# ===========================================================================


def test_user_a_cannot_read_other_household_recipes(
    client, household_b, token_a, recipe_b
):
    """GET fremde Rezepte liefert 403 Forbidden."""
    resp = client.get(
        f"/api/households/{household_b.id}/recipes/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_create_in_other_household(
    client, household_b, token_a
):
    """POST Rezept in fremdem Household liefert 403 Forbidden."""
    resp = client.post(
        f"/api/households/{household_b.id}/recipes/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Hacker-Rezept",
            "servings": 1,
            "ingredients": ["Exploit"],
        },
    )
    assert resp.status_code == 403


def test_user_a_cannot_patch_other_household_recipe(
    client, household_b, token_a, recipe_b
):
    """PATCH auf fremdes Rezept liefert 403 Forbidden."""
    resp = client.patch(
        f"/api/households/{household_b.id}/recipes/{recipe_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Gehacktes Rezept"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_delete_other_household_recipe(
    client, household_b, token_a, recipe_b
):
    """DELETE auf fremdes Rezept liefert 403 Forbidden."""
    resp = client.delete(
        f"/api/households/{household_b.id}/recipes/{recipe_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ===========================================================================
# MealPlan — Positiv
# ===========================================================================


def test_user_a_can_read_own_meal_plan(
    client, household_a, token_a, meal_plan_entry_a
):
    """GET Wochenplan liefert 200 und enthält den eigenen Eintrag."""
    resp = client.get(
        f"/api/households/{household_a.id}/meal-plan/?week=2026-08-10",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(e["id"] == str(meal_plan_entry_a.id) for e in data)


def test_user_a_can_assign_meal(
    client, household_a, token_a, recipe_a
):
    """PUT eigenes Datum liefert 200 (Upsert)."""
    resp = client.put(
        f"/api/households/{household_a.id}/meal-plan/2026-08-11",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"recipe_id": str(recipe_a.id)},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["recipe_id"] == str(recipe_a.id)
    assert data["date"] == "2026-08-11"


# ===========================================================================
# MealPlan — Negativ (Cross-Household)
# ===========================================================================


def test_user_a_cannot_read_other_household_meal_plan(
    client, household_b, token_a, meal_plan_entry_b
):
    """GET fremder Wochenplan liefert 403 Forbidden."""
    resp = client.get(
        f"/api/households/{household_b.id}/meal-plan/?week=2026-08-10",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_assign_in_other_household(
    client, household_b, token_a, recipe_b
):
    """PUT in fremdem Household liefert 403 Forbidden."""
    resp = client.put(
        f"/api/households/{household_b.id}/meal-plan/2026-08-12",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"recipe_id": str(recipe_b.id)},
    )
    assert resp.status_code == 403


def test_user_a_cannot_delete_other_household_meal_plan_entry(
    client, household_b, token_a, meal_plan_entry_b
):
    """DELETE fremder MealPlanEntry liefert 403 Forbidden."""
    resp = client.delete(
        f"/api/households/{household_b.id}/meal-plan/2026-08-10",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403
