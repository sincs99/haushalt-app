"""
Shopping-Integration-Tests für den Food-Endpunkt
POST /meal-plan/{entry_id}/add-missing-to-shopping.

Testet das Anlegen von Einkaufs-Items aus Rezept-Zutaten,
Duplikat-Erkennung (case-insensitive) und Cross-Household-Schutz.
"""

import uuid

from app.models import MealPlanEntry, ShoppingItem, ShoppingList


# ===========================================================================
# Positiv-Tests
# ===========================================================================


def test_add_missing_to_shopping_creates_items(
    client, household_a, token_a, meal_plan_entry_a, recipe_a, shopping_list_a
):
    """Alle Zutaten werden als ShoppingItems angelegt, Response enthält korrekte added-Liste."""
    resp = client.post(
        f"/api/households/{household_a.id}/meal-plan/{meal_plan_entry_a.id}/add-missing-to-shopping",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Alle 4 Zutaten sollten hinzugefügt worden sein
    assert set(data["added"]) == {"Spaghetti", "Hackfleisch", "Tomaten", "Zwiebeln"}
    assert data["skipped"] == []
    assert data["list_id"] == str(shopping_list_a.id)


def test_add_missing_to_shopping_skips_duplicates(
    client, db, household_a, token_a, user_a, meal_plan_entry_a, recipe_a, shopping_list_a
):
    """Wenn ein ShoppingItem mit gleichem Namen (case-insensitive) bereits unchecked existiert, wird es übersprungen."""
    # Vorab ein Item mit dem Namen einer Zutat anlegen (kleingeschrieben → case-insensitive)
    existing = ShoppingItem(
        id=uuid.uuid4(),
        household_id=household_a.id,
        list_id=shopping_list_a.id,
        name="spaghetti",  # case-insensitive Match zu "Spaghetti"
        added_by_user_id=user_a.id,
        is_checked=False,
    )
    db.add(existing)
    db.commit()

    resp = client.post(
        f"/api/households/{household_a.id}/meal-plan/{meal_plan_entry_a.id}/add-missing-to-shopping",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "Spaghetti" in data["skipped"]
    assert "Spaghetti" not in data["added"]
    # Die restlichen 3 sollten hinzugefügt sein
    assert set(data["added"]) == {"Hackfleisch", "Tomaten", "Zwiebeln"}


def test_add_missing_to_shopping_creates_list_if_none(
    client, db, household_a, token_a, meal_plan_entry_a, recipe_a
):
    """Wenn keine ShoppingList existiert, wird automatisch eine erstellt."""
    # Sicherstellen, dass keine Liste existiert
    db.query(ShoppingList).filter(ShoppingList.household_id == household_a.id).delete()
    db.commit()

    resp = client.post(
        f"/api/households/{household_a.id}/meal-plan/{meal_plan_entry_a.id}/add-missing-to-shopping",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["added"]) == 4
    # list_id muss gesetzt sein (auto-erstellte Liste)
    assert data["list_id"] is not None

    # Prüfen dass die Liste wirklich existiert
    created_list = db.get(ShoppingList, uuid.UUID(data["list_id"]))
    assert created_list is not None
    assert created_list.household_id == household_a.id


def test_add_missing_to_shopping_ignores_checked_items(
    client, db, household_a, token_a, user_a, meal_plan_entry_a, recipe_a, shopping_list_a
):
    """Checked Items mit gleichem Namen werden NICHT als Duplikate gezählt → Zutat wird neu angelegt."""
    # Checked Item mit gleichem Namen anlegen
    checked = ShoppingItem(
        id=uuid.uuid4(),
        household_id=household_a.id,
        list_id=shopping_list_a.id,
        name="Spaghetti",
        added_by_user_id=user_a.id,
        is_checked=True,
    )
    db.add(checked)
    db.commit()

    resp = client.post(
        f"/api/households/{household_a.id}/meal-plan/{meal_plan_entry_a.id}/add-missing-to-shopping",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Spaghetti sollte NICHT geskippt werden, weil das existierende Item checked ist
    assert "Spaghetti" in data["added"]
    assert "Spaghetti" not in data["skipped"]
    assert set(data["added"]) == {"Spaghetti", "Hackfleisch", "Tomaten", "Zwiebeln"}


# ===========================================================================
# Negativ-Tests
# ===========================================================================


def test_add_missing_no_recipe_returns_400(
    client, db, household_a, token_a
):
    """MealPlanEntry mit free_text ohne recipe_id → 400."""
    from datetime import date

    # MealPlanEntry ohne recipe_id erstellen (nur free_text)
    entry = MealPlanEntry(
        id=uuid.uuid4(),
        household_id=household_a.id,
        date=date(2026, 8, 15),
        recipe_id=None,
        free_text="Etwas Spontanes",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)

    resp = client.post(
        f"/api/households/{household_a.id}/meal-plan/{entry.id}/add-missing-to-shopping",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 400


def test_add_missing_cross_household_returns_403(
    client, household_b, token_a, meal_plan_entry_b, recipe_b
):
    """Cross-Household-Zugriff auf add-missing-to-shopping → 403."""
    resp = client.post(
        f"/api/households/{household_b.id}/meal-plan/{meal_plan_entry_b.id}/add-missing-to-shopping",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403
