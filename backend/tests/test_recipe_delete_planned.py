"""
CASA-52 / PD-M3: Ein Rezept, das im Menüplan steht, wird gelöscht → die Einträge
bleiben mit dem Rezeptnamen als Freitext (statt weder Rezept noch Text).
"""

from app.models import MealPlanEntry


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_delete_recipe_keeps_name_as_free_text(client, db, household_a, token_a, recipe_a, meal_plan_entry_a):
    resp = client.delete(f"/api/households/{household_a.id}/recipes/{recipe_a.id}", headers=_auth(token_a))
    assert resp.status_code == 204

    db.expire_all()
    entry = db.get(MealPlanEntry, meal_plan_entry_a.id)
    assert entry is not None
    assert entry.recipe_id is None
    assert entry.free_text == "Spaghetti Bolognese"

    week = client.get(
        f"/api/households/{household_a.id}/meal-plan/", headers=_auth(token_a), params={"week": "2026-08-10"}
    ).json()
    assert week[0]["free_text"] == "Spaghetti Bolognese"
    assert week[0]["recipe"] is None


def test_delete_recipe_does_not_touch_other_households(
    client, db, household_a, token_a, recipe_a, meal_plan_entry_a, meal_plan_entry_b
):
    client.delete(f"/api/households/{household_a.id}/recipes/{recipe_a.id}", headers=_auth(token_a))
    db.expire_all()
    other = db.get(MealPlanEntry, meal_plan_entry_b.id)
    assert other.recipe_id is not None
    assert other.free_text is None
