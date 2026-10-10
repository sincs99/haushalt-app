"""
CASA-19 / PD-M1: Essens-Abstimmung entscheiden auf einem belegten Tag.

- Ohne replace → 409 MEAL_PLAN_OCCUPIED (mit dem bestehenden Eintrag), Abstimmung bleibt offen.
- Mit replace=true → Eintrag ersetzt.
- Socket-Event meal_plan_updated trägt den VOLLSTÄNDIGEN Eintrag (id, recipe) wie PUT,
  sonst zeigen andere Geräte den Tag leer an.
"""

import uuid
from datetime import date

from app.models import EventPoll, MealPlanEntry


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _meal_poll(client, household, token, recipe):
    resp = client.post(
        f"/api/households/{household.id}/polls/",
        headers=_auth(token),
        json={
            "question": "Was essen wir?",
            "poll_type": "meal",
            "meal_date": "2026-10-17",
            "options": [{"label": recipe.name, "recipe_id": str(recipe.id)}, {"label": "Zopf"}],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _plan(client, household, token, day, **body):
    resp = client.put(f"/api/households/{household.id}/meal-plan/{day}", headers=_auth(token), json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _decide(client, household, token, poll, option_index, **extra):
    return client.post(
        f"/api/households/{household.id}/polls/{poll['id']}/meal-decide",
        headers=_auth(token),
        json={"option_id": poll["options"][option_index]["id"], **extra},
    )


def test_decide_on_occupied_date_returns_409(client, db, household_a, token_a, recipe_a):
    _plan(client, household_a, token_a, "2026-10-17", free_text="Grosis Geburtstag – Fondue")
    poll = _meal_poll(client, household_a, token_a, recipe_a)

    resp = _decide(client, household_a, token_a, poll, 0)
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "MEAL_PLAN_OCCUPIED"
    assert detail["entry"]["free_text"] == "Grosis Geburtstag – Fondue"

    db.expire_all()
    assert db.get(EventPoll, uuid.UUID(poll["id"])).status == "offen"
    entry = db.query(MealPlanEntry).filter_by(household_id=household_a.id, date=date(2026, 10, 17)).one()
    assert entry.free_text == "Grosis Geburtstag – Fondue"
    assert entry.recipe_id is None


def test_decide_with_replace_overwrites(client, db, household_a, token_a, recipe_a):
    _plan(client, household_a, token_a, "2026-10-17", free_text="Fondue")
    poll = _meal_poll(client, household_a, token_a, recipe_a)

    resp = _decide(client, household_a, token_a, poll, 0, replace=True)
    assert resp.status_code == 200, resp.text
    db.expire_all()
    entry = db.query(MealPlanEntry).filter_by(household_id=household_a.id, date=date(2026, 10, 17)).one()
    assert entry.recipe_id == recipe_a.id
    assert entry.free_text is None


def test_decide_on_free_date_emits_full_entry(client, household_a, token_a, recipe_a, _mock_socket_emit):
    poll = _meal_poll(client, household_a, token_a, recipe_a)
    resp = _decide(client, household_a, token_a, poll, 0)
    assert resp.status_code == 200

    payloads = [c.args[2] for c in _mock_socket_emit.call_args_list if c.args[1] == "meal_plan_updated"]
    assert len(payloads) == 1
    entry = payloads[0]
    assert entry["id"]
    assert entry["date"] == "2026-10-17"
    assert entry["recipe_id"] == str(recipe_a.id)
    assert entry["recipe"]["name"] == recipe_a.name


def test_put_still_overwrites(client, household_a, token_a, recipe_a):
    """Manuelles Planen über PUT bleibt ein Upsert (bewusste Aktion im Menüplan)."""
    first = _plan(client, household_a, token_a, "2026-10-18", free_text="Pasta")
    second = _plan(client, household_a, token_a, "2026-10-18", recipe_id=str(recipe_a.id))
    assert first["id"] == second["id"]
    assert second["recipe_id"] == str(recipe_a.id)
    assert second["free_text"] is None
