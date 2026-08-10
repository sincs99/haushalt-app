"""
Multi-Tenant Scoping Tests für Dashboard.

Stellt sicher, dass User NUR das Dashboard ihres eigenen Households
lesen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""

import uuid
from datetime import datetime, timezone as tz

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
