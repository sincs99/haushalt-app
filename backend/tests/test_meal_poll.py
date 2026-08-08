"""Tests für Meal-Poll-Erweiterung (SLICE 2.1 + 2.2)."""

import uuid
from datetime import date

import pytest

from app.models import EventPoll, EventPollOption, MealPlanEntry, Recipe


# ---------------------------------------------------------------------------
# Lokale Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def _second_recipe(db, household_a) -> Recipe:
    """Zweites Rezept in Household A für Tests mit recipe_id."""
    r = Recipe(
        id=uuid.uuid4(),
        household_id=household_a.id,
        name="Risotto",
        servings=2,
        ingredients=["Reis", "Parmesan", "Brühe"],
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


# ---------------------------------------------------------------------------
# 1) test_create_meal_poll
# ---------------------------------------------------------------------------
class TestCreateMealPoll:
    def test_create_meal_poll(self, client, household_a, token_a, recipe_a, _second_recipe):
        """POST mit poll_type='meal', meal_date, Optionen mit recipe_id → 201."""
        url = f"/api/households/{household_a.id}/polls/"
        resp = client.post(
            url,
            json={
                "question": "Was essen wir am Mittwoch?",
                "poll_type": "meal",
                "meal_date": "2026-08-12",
                "options": [
                    {"label": "Spaghetti Bolognese", "recipe_id": str(recipe_a.id)},
                    {"label": "Risotto", "recipe_id": str(_second_recipe.id)},
                ],
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["poll_type"] == "meal"
        assert data["decided_meal_date"] == "2026-08-12"
        assert data["status"] == "offen"
        assert len(data["options"]) == 2
        assert data["options"][0]["recipe_id"] is not None

    def test_create_meal_poll_without_date_returns_400(self, client, household_a, token_a):
        """POST mit poll_type='meal' ohne meal_date → 400."""
        url = f"/api/households/{household_a.id}/polls/"
        resp = client.post(
            url,
            json={
                "question": "Was essen wir?",
                "poll_type": "meal",
                "options": [
                    {"label": "Pizza"},
                    {"label": "Salat"},
                ],
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "POLL_MEAL_DATE_REQUIRED"


# ---------------------------------------------------------------------------
# 2) test_meal_poll_decide
# ---------------------------------------------------------------------------
class TestMealPollDecide:
    @pytest.fixture()
    def meal_poll_with_recipe(self, db, household_a, user_a, recipe_a, _second_recipe):
        """Erstellt einen Meal-Poll mit zwei Optionen (eine mit recipe_id, eine ohne)."""
        poll = EventPoll(
            id=uuid.uuid4(),
            household_id=household_a.id,
            question="Was essen wir am Donnerstag?",
            status="offen",
            poll_type="meal",
            decided_meal_date=date(2026, 8, 13),
            created_by_user_id=user_a.id,
        )
        db.add(poll)
        db.flush()

        opt_recipe = EventPollOption(
            id=uuid.uuid4(),
            poll_id=poll.id,
            household_id=household_a.id,
            label="Spaghetti Bolognese",
            recipe_id=recipe_a.id,
        )
        opt_freetext = EventPollOption(
            id=uuid.uuid4(),
            poll_id=poll.id,
            household_id=household_a.id,
            label="Auswärts essen",
        )
        db.add_all([opt_recipe, opt_freetext])
        db.commit()
        db.refresh(poll)
        return poll, opt_recipe, opt_freetext

    def test_meal_poll_decide_creates_meal_plan_entry(
        self, client, db, household_a, token_a, meal_poll_with_recipe
    ):
        """meal-decide erzeugt MealPlanEntry, Poll status='entschieden'."""
        poll, opt_recipe, _ = meal_poll_with_recipe

        url = f"/api/households/{household_a.id}/polls/{poll.id}/meal-decide"
        resp = client.post(
            url,
            json={"option_id": str(opt_recipe.id)},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "entschieden"
        assert data["decided_meal_date"] == "2026-08-13"

        # MealPlanEntry prüfen
        entry = (
            db.query(MealPlanEntry)
            .filter(
                MealPlanEntry.household_id == household_a.id,
                MealPlanEntry.date == date(2026, 8, 13),
            )
            .first()
        )
        assert entry is not None

    def test_meal_poll_decide_with_recipe_sets_recipe_id(
        self, client, db, household_a, token_a, recipe_a, meal_poll_with_recipe
    ):
        """Option mit recipe_id → MealPlanEntry.recipe_id wird gesetzt."""
        poll, opt_recipe, _ = meal_poll_with_recipe

        url = f"/api/households/{household_a.id}/polls/{poll.id}/meal-decide"
        client.post(
            url,
            json={"option_id": str(opt_recipe.id)},
            headers={"Authorization": f"Bearer {token_a}"},
        )

        entry = (
            db.query(MealPlanEntry)
            .filter(
                MealPlanEntry.household_id == household_a.id,
                MealPlanEntry.date == date(2026, 8, 13),
            )
            .first()
        )
        assert entry is not None
        assert entry.recipe_id == recipe_a.id
        assert entry.free_text is None

    def test_meal_poll_decide_without_recipe_sets_free_text(
        self, client, db, household_a, token_a, meal_poll_with_recipe
    ):
        """Option ohne recipe_id → free_text=label."""
        poll, _, opt_freetext = meal_poll_with_recipe

        url = f"/api/households/{household_a.id}/polls/{poll.id}/meal-decide"
        client.post(
            url,
            json={"option_id": str(opt_freetext.id)},
            headers={"Authorization": f"Bearer {token_a}"},
        )

        entry = (
            db.query(MealPlanEntry)
            .filter(
                MealPlanEntry.household_id == household_a.id,
                MealPlanEntry.date == date(2026, 8, 13),
            )
            .first()
        )
        assert entry is not None
        assert entry.recipe_id is None
        assert entry.free_text == "Auswärts essen"


# ---------------------------------------------------------------------------
# 3) Fehlerfälle
# ---------------------------------------------------------------------------
class TestMealPollErrors:
    def test_meal_decide_on_event_poll_returns_400(
        self, client, db, household_a, user_a, token_a
    ):
        """meal-decide auf event-Poll → 400 POLL_TYPE_MISMATCH."""
        poll = EventPoll(
            id=uuid.uuid4(),
            household_id=household_a.id,
            question="Wann treffen wir uns?",
            status="offen",
            poll_type="event",
            created_by_user_id=user_a.id,
        )
        db.add(poll)
        db.flush()

        opt = EventPollOption(
            id=uuid.uuid4(),
            poll_id=poll.id,
            household_id=household_a.id,
            label="Montag",
        )
        opt2 = EventPollOption(
            id=uuid.uuid4(),
            poll_id=poll.id,
            household_id=household_a.id,
            label="Dienstag",
        )
        db.add_all([opt, opt2])
        db.commit()

        url = f"/api/households/{household_a.id}/polls/{poll.id}/meal-decide"
        resp = client.post(
            url,
            json={"option_id": str(opt.id)},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["code"] == "POLL_TYPE_MISMATCH"

    def test_meal_decide_already_decided_returns_400(
        self, client, db, household_a, user_a, token_a, recipe_a
    ):
        """Doppeltes decide → 400 POLL_ALREADY_DECIDED."""
        poll = EventPoll(
            id=uuid.uuid4(),
            household_id=household_a.id,
            question="Was essen wir am Freitag?",
            status="offen",
            poll_type="meal",
            decided_meal_date=date(2026, 8, 14),
            created_by_user_id=user_a.id,
        )
        db.add(poll)
        db.flush()

        opt1 = EventPollOption(
            id=uuid.uuid4(),
            poll_id=poll.id,
            household_id=household_a.id,
            label="Spaghetti Bolognese",
            recipe_id=recipe_a.id,
        )
        opt2 = EventPollOption(
            id=uuid.uuid4(),
            poll_id=poll.id,
            household_id=household_a.id,
            label="Pizza",
        )
        db.add_all([opt1, opt2])
        db.commit()

        url = f"/api/households/{household_a.id}/polls/{poll.id}/meal-decide"
        # Erster decide → OK
        resp1 = client.post(
            url,
            json={"option_id": str(opt1.id)},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp1.status_code == 200

        # Zweiter decide → 400
        resp2 = client.post(
            url,
            json={"option_id": str(opt2.id)},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp2.status_code == 400
        assert resp2.json()["detail"]["code"] == "POLL_ALREADY_DECIDED"
