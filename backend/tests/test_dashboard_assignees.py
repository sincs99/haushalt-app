"""Dashboard zeigt die Zuständigen von Aufgaben und Ämtli (Name + ID, nur aktuelle Mitglieder)."""

import uuid
from datetime import timedelta

from app.core.security import hash_password
from app.models import Chore, ChoreAssignment, HouseholdMember, Todo, User
from app.services.chore_scheduler import today_in_tz


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _member(db, household, name, *, member=True):
    user = User(id=uuid.uuid4(), email=f"{name.lower()}-{uuid.uuid4().hex[:6]}@example.com",
                password_hash=hash_password("x" * 10), display_name=name)
    db.add(user)
    db.flush()
    if member:
        db.add(HouseholdMember(household_id=household.id, user_id=user.id, role="member"))
    db.commit()
    return user


def _dashboard(client, household, token):
    resp = client.get(f"/api/households/{household.id}/dashboard", headers=_auth(token))
    assert resp.status_code == 200
    return resp.json()


def test_dashboard_todo_items_list_current_assignees(client, db, household_a, token_a, user_a):
    ben = _member(db, household_a, "Ben")
    former = _member(db, household_a, "Fritz", member=False)  # nicht (mehr) Mitglied
    shared = Todo(household_id=household_a.id, title="Altglas")
    shared.assignee_ids = [user_a.id, ben.id, former.id]
    open_for_all = Todo(household_id=household_a.id, title="Blumen giessen")
    db.add_all([shared, open_for_all])
    db.commit()

    items = {i["title"]: i for i in _dashboard(client, household_a, token_a)["todos"]["items"]}

    assert sorted(a["display_name"] for a in items["Altglas"]["assignees"]) == ["Alice", "Ben"]
    assert {a["user_id"] for a in items["Altglas"]["assignees"]} == {str(user_a.id), str(ben.id)}
    assert items["Blumen giessen"]["assignees"] == []


def test_dashboard_chore_items_carry_assignee_name(client, db, household_a, token_a, user_a):
    today = today_in_tz(household_a.timezone)
    chore = Chore(household_id=household_a.id, title="Bad", recurrence="weekly", weekday=today.weekday(),
                  rotation_order=[str(user_a.id)], anchor_date=today - timedelta(days=30))
    db.add(chore)
    db.flush()
    db.add(ChoreAssignment(household_id=household_a.id, chore_id=chore.id,
                           assigned_user_id=user_a.id, due_date=today))
    db.commit()

    item = _dashboard(client, household_a, token_a)["chores"]["items"][0]

    assert item["assignees"] == [{"user_id": str(user_a.id), "display_name": "Alice"}]
