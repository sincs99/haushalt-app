"""
Tests für Todo-Reminders: CRUD, Scoping und Max-5-Limit.

Endpoints:
- POST /api/households/{hid}/todos/{tid}/reminders/ → 201
- DELETE /api/households/{hid}/todos/{tid}/reminders/{rid} → 204
"""

import uuid
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Positiv: Reminder erstellen → 201
# ---------------------------------------------------------------------------
def test_create_reminder_success(client, household_a, token_a, todo_a):
    remind_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    resp = client.post(
        f"/api/households/{household_a.id}/todos/{todo_a.id}/reminders/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"remind_at": remind_at},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["todo_id"] == str(todo_a.id)
    assert data["remind_at"] is not None
    assert data["notified_at"] is None


# ---------------------------------------------------------------------------
# Negativ: Cross-Tenant POST → 403
# ---------------------------------------------------------------------------
def test_create_reminder_cross_tenant_403(client, household_b, token_a, todo_b):
    remind_at = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    resp = client.post(
        f"/api/households/{household_b.id}/todos/{todo_b.id}/reminders/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"remind_at": remind_at},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: Reminder löschen → 204
# ---------------------------------------------------------------------------
def test_delete_reminder_success(client, household_a, token_a, todo_a, reminder_a):
    resp = client.delete(
        f"/api/households/{household_a.id}/todos/{todo_a.id}/reminders/{reminder_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Negativ: Cross-Tenant DELETE → 403
# ---------------------------------------------------------------------------
def test_delete_reminder_cross_tenant_403(client, household_b, token_a, todo_b, reminder_b):
    resp = client.delete(
        f"/api/households/{household_b.id}/todos/{todo_b.id}/reminders/{reminder_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Max 5 Reminders → 6. ergibt 422
# ---------------------------------------------------------------------------
def test_max_5_reminders_422(client, household_a, token_a, todo_a):
    # 5 Reminders erstellen
    for i in range(5):
        remind_at = (datetime.now(timezone.utc) + timedelta(hours=i + 1)).isoformat()
        resp = client.post(
            f"/api/households/{household_a.id}/todos/{todo_a.id}/reminders/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"remind_at": remind_at},
        )
        assert resp.status_code == 201, f"Reminder {i+1} failed: {resp.json()}"

    # 6. Reminder → 422
    remind_at = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
    resp = client.post(
        f"/api/households/{household_a.id}/todos/{todo_a.id}/reminders/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"remind_at": remind_at},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "TOO_MANY_REMINDERS"


# ---------------------------------------------------------------------------
# Reminder nicht gefunden → 404
# ---------------------------------------------------------------------------
def test_reminder_not_found_404(client, household_a, token_a, todo_a):
    fake_id = uuid.uuid4()
    resp = client.delete(
        f"/api/households/{household_a.id}/todos/{todo_a.id}/reminders/{fake_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET todos enthält reminders Array
# ---------------------------------------------------------------------------
def test_list_todos_includes_reminders(client, household_a, token_a, todo_a, reminder_a):
    resp = client.get(
        f"/api/households/{household_a.id}/todos/?include_done=true",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    todo = next(t for t in data if t["id"] == str(todo_a.id))
    assert "reminders" in todo
    assert len(todo["reminders"]) >= 1
    assert todo["reminders"][0]["id"] == str(reminder_a.id)


# ---------------------------------------------------------------------------
# Reminders sortiert nach remind_at ASC
# ---------------------------------------------------------------------------
def test_reminders_sorted_asc(client, household_a, token_a, todo_a):
    # 3 Reminders in umgekehrter Reihenfolge erstellen
    times = [
        datetime.now(timezone.utc) + timedelta(hours=3),
        datetime.now(timezone.utc) + timedelta(hours=1),
        datetime.now(timezone.utc) + timedelta(hours=2),
    ]
    for t in times:
        client.post(
            f"/api/households/{household_a.id}/todos/{todo_a.id}/reminders/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"remind_at": t.isoformat()},
        )

    # Todos abrufen
    resp = client.get(
        f"/api/households/{household_a.id}/todos/?include_done=true",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    todo = next(t for t in resp.json() if t["id"] == str(todo_a.id))
    remind_ats = [r["remind_at"] for r in todo["reminders"]]
    assert remind_ats == sorted(remind_ats), f"Reminders not sorted ASC: {remind_ats}"
