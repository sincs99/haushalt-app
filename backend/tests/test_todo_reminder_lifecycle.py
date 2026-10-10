"""Todos: Erinnerungen über Erledigen/Rückgängig, Zeitzone, Version, Zuständige (CASA-06, CASA-51, CASA-46, CASA-21)."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models import HouseholdMember, TodoReminder
from app.services import push_service


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _url(household, path=""):
    return f"/api/households/{household.id}/todos{path}"


def _add_reminder(client, household, token, todo_id, remind_at):
    return client.post(
        _url(household, f"/{todo_id}/reminders/"), headers=_auth(token), json={"remind_at": remind_at}
    )


def _set_done(client, household, token, todo_id, done):
    r = client.patch(_url(household, f"/{todo_id}"), headers=_auth(token), json={"is_done": done})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# CASA-06: Erledigt → Rückgängig behält künftige Erinnerungen
# ---------------------------------------------------------------------------


def test_done_then_undo_keeps_future_reminder(client, db, household_a, token_a, todo_a):
    remind_at = datetime.now(timezone.utc) + timedelta(hours=5)
    r = _add_reminder(client, household_a, token_a, todo_a.id, remind_at.isoformat())
    assert r.status_code == 201
    reminder_id = uuid.UUID(r.json()["id"])

    _set_done(client, household_a, token_a, todo_a.id, True)
    reopened = _set_done(client, household_a, token_a, todo_a.id, False)
    assert reopened["reminders"][0]["notified_at"] is None

    sent = []
    with patch.object(push_service, "send_to_users", side_effect=lambda db, uids, b, **k: sent.append(b("de")) or 1):
        assert push_service.process_todo_reminders(db, remind_at + timedelta(minutes=1)) == 1
    assert sent[0]["body"] == todo_a.title
    db.expire_all()
    assert db.get(TodoReminder, reminder_id).notified_at is not None


def test_done_todo_reminder_not_sent(client, db, household_a, token_a, todo_a):
    remind_at = datetime.now(timezone.utc) + timedelta(hours=1)
    _add_reminder(client, household_a, token_a, todo_a.id, remind_at.isoformat())
    _set_done(client, household_a, token_a, todo_a.id, True)
    with patch.object(push_service, "send_to_users", return_value=1) as send:
        assert push_service.process_todo_reminders(db, remind_at + timedelta(minutes=1)) == 0
    send.assert_not_called()


def test_reopen_rearms_future_reminders_marked_by_older_versions(client, db, household_a, token_a, todo_a):
    """Altbestand: frühere Versionen markierten Erinnerungen beim Erledigen."""
    now = datetime.now(timezone.utc)
    future = TodoReminder(household_id=household_a.id, todo_id=todo_a.id, remind_at=now + timedelta(hours=2), notified_at=now)
    past = TodoReminder(household_id=household_a.id, todo_id=todo_a.id, remind_at=now - timedelta(hours=2), notified_at=now)
    todo_a.is_done = True
    db.add_all([future, past])
    db.commit()
    _set_done(client, household_a, token_a, todo_a.id, False)
    db.refresh(future)
    db.refresh(past)
    assert future.notified_at is None
    assert past.notified_at is not None


def test_dashboard_lists_reminder_again_after_undo(client, household_a, token_a, todo_a):
    remind_at = datetime.now(timezone.utc) + timedelta(hours=5)
    _add_reminder(client, household_a, token_a, todo_a.id, remind_at.isoformat())
    _set_done(client, household_a, token_a, todo_a.id, True)
    _set_done(client, household_a, token_a, todo_a.id, False)
    dash = client.get(f"/api/households/{household_a.id}/dashboard", headers=_auth(token_a)).json()
    assert [r["todo_id"] for r in dash["upcoming_reminders"]] == [str(todo_a.id)]


# ---------------------------------------------------------------------------
# CASA-51: keine Erinnerung an erledigte Todos; naive Zeit = Haushaltszeit
# ---------------------------------------------------------------------------


def test_reminder_on_done_todo_is_422(client, household_a, token_a, todo_a):
    _set_done(client, household_a, token_a, todo_a.id, True)
    r = _add_reminder(client, household_a, token_a, todo_a.id, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "TODO_IS_DONE"


def test_naive_remind_at_is_household_wall_time(client, db, household_a, token_a, todo_a):
    year = datetime.now().year + 1
    r = _add_reminder(client, household_a, token_a, todo_a.id, f"{year}-01-15T09:00:00")
    assert r.status_code == 201, r.text
    reminder = db.get(TodoReminder, uuid.UUID(r.json()["id"]))
    stored = reminder.remind_at.replace(tzinfo=reminder.remind_at.tzinfo or timezone.utc)
    # Europe/Zurich im Januar: UTC+1
    assert stored == datetime(year, 1, 15, 8, 0, tzinfo=timezone.utc)


def test_past_remind_at_is_422(client, household_a, token_a, todo_a):
    r = _add_reminder(client, household_a, token_a, todo_a.id, (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "REMINDER_IN_PAST"


# ---------------------------------------------------------------------------
# CASA-46: Erinnerung anlegen/löschen erhöht die Todo-Version
# ---------------------------------------------------------------------------


def test_reminder_add_and_delete_bump_todo_version(client, household_a, token_a, todo_a, _mock_socket_emit):
    before = client.get(_url(household_a, "/"), headers=_auth(token_a)).json()[0]["version"]
    _mock_socket_emit.reset_mock()
    r = _add_reminder(client, household_a, token_a, todo_a.id, (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    events = [c.args[2] for c in _mock_socket_emit.call_args_list if c.args[1] == "todo_updated"]
    assert events[-1]["version"] == before + 1
    assert len(events[-1]["reminders"]) == 1

    _mock_socket_emit.reset_mock()
    client.delete(_url(household_a, f"/{todo_a.id}/reminders/{r.json()['id']}"), headers=_auth(token_a))
    events = [c.args[2] for c in _mock_socket_emit.call_args_list if c.args[1] == "todo_updated"]
    assert events[-1]["version"] == before + 2
    assert events[-1]["reminders"] == []


# ---------------------------------------------------------------------------
# CASA-21: zuständige Person muss Mitglied sein
# ---------------------------------------------------------------------------


def test_create_with_foreign_or_unknown_assignee_is_422(client, household_a, token_a, user_b):
    for assignee in (user_b.id, uuid.uuid4()):
        r = client.post(
            _url(household_a, "/"), headers=_auth(token_a), json={"title": "X", "assigned_to_user_id": str(assignee)}
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "USERS_NOT_IN_HOUSEHOLD"


def test_update_to_foreign_assignee_is_422(client, household_a, token_a, todo_a, user_b):
    r = client.patch(_url(household_a, f"/{todo_a.id}"), headers=_auth(token_a), json={"assigned_to_user_id": str(user_b.id)})
    assert r.status_code == 422


def test_ex_member_already_assigned_may_stay(client, db, household_a, token_a, todo_a, user_a2):
    todo_a.assigned_to_user_id = user_a2.id
    db.commit()
    db.query(HouseholdMember).filter_by(household_id=household_a.id, user_id=user_a2.id).delete()
    db.commit()
    # Das UI sendet beim Speichern alle Felder mit, auch die bisherige Zuständige
    r = client.patch(
        _url(household_a, f"/{todo_a.id}"),
        headers=_auth(token_a),
        json={"title": "Neu", "assigned_to_user_id": str(user_a2.id)},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Neu"


def test_member_assignee_ok(client, household_a, token_a, user_a2):
    r = client.post(
        _url(household_a, "/"), headers=_auth(token_a), json={"title": "X", "assigned_to_user_id": str(user_a2.id)}
    )
    assert r.status_code == 201
