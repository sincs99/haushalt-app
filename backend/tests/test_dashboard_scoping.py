"""
Multi-Tenant Scoping Tests für Dashboard.

Stellt sicher, dass User NUR das Dashboard ihres eigenen Households
lesen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""

import uuid
from datetime import datetime
from datetime import timezone as tz

from app.models import Event

# ---------------------------------------------------------------------------
# Positiv: User A liest eigenes Dashboard → 200, alle Sektionen vorhanden
# ---------------------------------------------------------------------------


def test_user_a_can_read_own_dashboard(client, household_a, token_a, user_a):
    resp = client.get(
        f"/api/households/{household_a.id}/dashboard",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "todos" in data
    assert "chores" in data
    assert "shopping" in data
    assert "finance" in data
    assert "events" in data


# ---------------------------------------------------------------------------
# Negativ: User A liest Dashboard von Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_read_other_dashboard(client, household_b, token_a, user_b):
    resp = client.get(
        f"/api/households/{household_b.id}/dashboard",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Inhalt: Dashboard enthält Todo-Daten
# ---------------------------------------------------------------------------


def test_dashboard_contains_todo_data(client, household_a, token_a, user_a, todo_a):
    resp = client.get(
        f"/api/households/{household_a.id}/dashboard",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    data = resp.json()
    assert data["todos"]["open_count"] >= 1


# ---------------------------------------------------------------------------
# Inhalt: Dashboard enthält Shopping-Daten
# ---------------------------------------------------------------------------


def test_dashboard_contains_shopping_data(
    client, household_a, token_a, user_a, shopping_item_a
):
    resp = client.get(
        f"/api/households/{household_a.id}/dashboard",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    data = resp.json()
    assert data["shopping"]["open_count"] >= 1


# ---------------------------------------------------------------------------
# Inhalt: Dashboard enthält Event-Daten (Event von "heute")
# ---------------------------------------------------------------------------


def test_dashboard_contains_event_data(client, household_a, token_a, user_a, calendar_a, db):
    """Ein Event mit starts_at=jetzt muss in der events-Sektion erscheinen."""
    now = datetime.now(tz.utc)
    event = Event(
        id=uuid.uuid4(),
        household_id=household_a.id,
        calendar_id=calendar_a.id,
        title="Dashboard-Test-Event",
        starts_at=now,
        all_day=False,
        participant_ids=[],
        created_by_user_id=user_a.id,
    )
    db.add(event)
    db.commit()

    resp = client.get(
        f"/api/households/{household_a.id}/dashboard",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    data = resp.json()
    assert len(data["events"]["items"]) >= 1
    titles = [e["title"] for e in data["events"]["items"]]
    assert "Dashboard-Test-Event" in titles


def test_dashboard_plants_water_section(client, db, household_a, household_b, token_a, plant_a, plant_b):
    """Nur fällige/überfällige Gießaufgaben des eigenen Haushalts, Überfällige zuerst."""
    from datetime import timedelta

    from app.models import Plant, PlantCareTask
    from app.services.chore_scheduler import today_in_tz

    today = today_in_tz(household_a.timezone)
    other = Plant(household_id=household_a.id, name="Aloe")
    db.add(other)
    db.flush()

    def task(plant, care_type, due, household=household_a):
        db.add(PlantCareTask(
            household_id=household.id, plant_id=plant.id, care_type=care_type,
            interval_days=7, next_due_at=due,
        ))

    task(plant_a, "water", today)
    task(other, "water", today - timedelta(days=3))
    task(plant_a, "fertilize", today - timedelta(days=9))      # keine Gießaufgabe
    task(plant_a, "water", today + timedelta(days=2))          # noch nicht fällig
    task(plant_b, "water", today - timedelta(days=5), household_b)  # fremder Haushalt
    db.commit()

    resp = client.get(f"/api/households/{household_a.id}/dashboard", headers={"Authorization": f"Bearer {token_a}"})
    assert resp.status_code == 200
    section = resp.json()["plants_water"]
    assert section["due_count"] == 2
    assert [i["plant_name"] for i in section["items"]] == ["Aloe", "Monstera"]
    assert [i["is_overdue"] for i in section["items"]] == [True, False]


def test_dashboard_plants_water_empty(client, household_a, token_a):
    resp = client.get(f"/api/households/{household_a.id}/dashboard", headers={"Authorization": f"Bearer {token_a}"})
    assert resp.json()["plants_water"] == {"due_count": 0, "items": []}


# ---------------------------------------------------------------------------
# Überfällig: Fälligkeit ist ein Datum und gilt den ganzen Tag (Logik-Review L-04)
# ---------------------------------------------------------------------------


def _todo_due(client, household_a, token_a, title, due: str):
    resp = client.post(
        f"/api/households/{household_a.id}/todos/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": title, "due_date": due},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_dashboard_todo_due_today_is_not_overdue(client, household_a, token_a, user_a):
    from datetime import timedelta

    from app.services.chore_scheduler import today_in_tz

    today = today_in_tz(household_a.timezone)
    due_today = _todo_due(client, household_a, token_a, "Heute", today.isoformat())
    due_yesterday = _todo_due(client, household_a, token_a, "Gestern", (today - timedelta(days=1)).isoformat())
    _todo_due(client, household_a, token_a, "Morgen", (today + timedelta(days=1)).isoformat())

    resp = client.get(
        f"/api/households/{household_a.id}/dashboard",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()["todos"]
    assert data["overdue_count"] == 1
    by_id = {item["id"]: item for item in data["items"]}
    assert by_id[due_yesterday]["is_overdue"] is True
    assert by_id[due_today]["is_overdue"] is False
    # Überfällige zuerst, dann nach Fälligkeit
    assert [item["title"] for item in data["items"]] == ["Gestern", "Heute", "Morgen"]
