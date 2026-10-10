"""Austritt "freigeben" (PD-H1 / CASA-22): offene Zuständigkeiten einer Person, die
den Haushalt verlässt oder entfernt wird, werden im selben Commit freigegeben.
Erledigtes und Geschichte behalten die Person.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.security import create_access_token, hash_password
from app.models import (
    Chore,
    ChoreAssignment,
    EventPoll,
    EventPollOption,
    EventPollVote,
    Household,
    HouseholdMember,
    RecurringBill,
    ShoppingItem,
    ShoppingList,
    Todo,
    User,
    WidgetToken,
)
from app.services.attention import due_items
from app.services.membership import _remove_from_rotation


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def hh(db):
    """Anna (Admin), Ben (Member, geht), Carla (Member) — mit offenen und erledigten Dingen von Ben."""
    h = Household(id=uuid.uuid4(), name="WG", invite_code="DEPART01", currency="CHF")
    db.add(h)
    users = {}
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i, (name, role) in enumerate((("Anna", "admin"), ("Ben", "member"), ("Carla", "member"))):
        u = User(id=uuid.uuid4(), email=f"{name.lower()}@dep.test", password_hash=hash_password("pw123456"), display_name=name)
        db.add(u)
        db.flush()
        db.add(HouseholdMember(household_id=h.id, user_id=u.id, role=role, joined_at=t0 + timedelta(hours=i)))
        users[name] = u
    anna, ben, carla = users["Anna"], users["Ben"], users["Carla"]
    db.flush()

    now = datetime.now(timezone.utc)
    open_todo = Todo(household_id=h.id, title="Altglas", assigned_to_user_id=ben.id, due_date=now, created_by_user_id=anna.id)
    done_todo = Todo(household_id=h.id, title="Erledigt", assigned_to_user_id=ben.id, is_done=True, created_by_user_id=anna.id)
    other_todo = Todo(household_id=h.id, title="Carlas", assigned_to_user_id=carla.id, created_by_user_id=anna.id)

    lst = ShoppingList(household_id=h.id, name="Einkauf")
    db.add_all([open_todo, done_todo, other_todo, lst])
    db.flush()
    open_item = ShoppingItem(household_id=h.id, list_id=lst.id, name="Milch", assigned_to_user_id=ben.id)
    checked_item = ShoppingItem(household_id=h.id, list_id=lst.id, name="Brot", is_checked=True, assigned_to_user_id=ben.id)

    # Rotation Anna → Ben → Carla, als Nächstes ist Carla dran (Index 2 in Runde 3 → 8)
    chore = Chore(
        household_id=h.id, title="Bad putzen", recurrence="weekly", weekday=0,
        rotation_order=[str(anna.id), str(ben.id), str(carla.id)], next_rotation_index=8,
        anchor_date=date(2024, 1, 1),
    )
    db.add_all([open_item, checked_item, chore])
    db.flush()
    today = date.today()
    overdue = ChoreAssignment(household_id=h.id, chore_id=chore.id, assigned_user_id=ben.id, due_date=today - timedelta(days=3))
    future = ChoreAssignment(household_id=h.id, chore_id=chore.id, assigned_user_id=ben.id, due_date=today + timedelta(days=4))
    done = ChoreAssignment(
        household_id=h.id, chore_id=chore.id, assigned_user_id=ben.id, due_date=today - timedelta(days=10),
        completed_at=now, completed_by_user_id=ben.id,
    )
    bill = RecurringBill(household_id=h.id, name="Miete", amount_rappen=100000, day_of_month=1, paid_by_user_id=ben.id)
    carla_bill = RecurringBill(household_id=h.id, name="Strom", amount_rappen=5000, day_of_month=2, paid_by_user_id=carla.id)

    open_poll = EventPoll(household_id=h.id, question="Wann?", status="offen", created_by_user_id=anna.id)
    decided_poll = EventPoll(household_id=h.id, question="Wo?", status="entschieden", created_by_user_id=anna.id)
    db.add_all([overdue, future, done, bill, carla_bill, open_poll, decided_poll])
    db.flush()
    opt_open = EventPollOption(poll_id=open_poll.id, household_id=h.id, label="Mo")
    opt_decided = EventPollOption(poll_id=decided_poll.id, household_id=h.id, label="Bar")
    db.add_all([opt_open, opt_decided])
    db.flush()
    db.add_all([
        EventPollVote(poll_id=open_poll.id, option_id=opt_open.id, user_id=ben.id, household_id=h.id),
        EventPollVote(poll_id=open_poll.id, option_id=opt_open.id, user_id=carla.id, household_id=h.id),
        EventPollVote(poll_id=decided_poll.id, option_id=opt_decided.id, user_id=ben.id, household_id=h.id),
        WidgetToken(user_id=ben.id, household_id=h.id, token_hash="b" * 64, token_prefix="hw_ben"),
        WidgetToken(user_id=carla.id, household_id=h.id, token_hash="c" * 64, token_prefix="hw_carla"),
    ])
    db.commit()
    return SimpleNamespace(
        h=h, anna=anna, ben=ben, carla=carla, open_todo=open_todo, done_todo=done_todo, other_todo=other_todo,
        open_item=open_item, checked_item=checked_item, chore=chore, overdue=overdue, future=future, done=done,
        bill=bill, carla_bill=carla_bill, open_poll=open_poll, decided_poll=decided_poll,
    )


def _leave(client, s):
    return client.post(f"/api/households/{s.h.id}/leave", headers=_auth(create_access_token(str(s.ben.id))))


def _remove(client, s):
    return client.delete(
        f"/api/households/{s.h.id}/members/{s.ben.id}", headers=_auth(create_access_token(str(s.anna.id)))
    )


@pytest.mark.parametrize("depart", [_leave, _remove], ids=["leave", "remove"])
def test_departure_releases_open_responsibilities(client, db, hh, depart):
    s = hh
    open_todo_version = s.open_todo.version

    assert depart(client, s).status_code == 204
    db.expire_all()

    # Offenes → niemand; Erledigtes behält Ben
    assert db.get(Todo, s.open_todo.id).assigned_to_user_id is None
    assert db.get(Todo, s.open_todo.id).version == open_todo_version + 1  # Offline-Sync sieht die Änderung
    assert db.get(Todo, s.done_todo.id).assigned_to_user_id == s.ben.id
    assert db.get(Todo, s.other_todo.id).assigned_to_user_id == s.carla.id
    assert db.get(ShoppingItem, s.open_item.id).assigned_to_user_id is None
    assert db.get(ShoppingItem, s.checked_item.id).assigned_to_user_id == s.ben.id
    assert db.get(ChoreAssignment, s.overdue.id).assigned_user_id is None
    assert db.get(ChoreAssignment, s.future.id).assigned_user_id is None
    assert db.get(ChoreAssignment, s.done.id).assigned_user_id == s.ben.id

    # Rotation ohne Ben, Carla bleibt die Nächste
    chore = db.get(Chore, s.chore.id)
    assert chore.rotation_order == [str(s.anna.id), str(s.carla.id)]
    assert chore.rotation_order[chore.next_rotation_index % 2] == str(s.carla.id)

    assert db.get(RecurringBill, s.bill.id).paid_by_user_id is None
    assert db.get(RecurringBill, s.carla_bill.id).paid_by_user_id == s.carla.id

    votes = {(v.poll_id, v.user_id) for v in db.query(EventPollVote).all()}
    assert (s.open_poll.id, s.ben.id) not in votes
    assert (s.open_poll.id, s.carla.id) in votes
    assert (s.decided_poll.id, s.ben.id) in votes  # Geschichte bleibt

    tokens = {t.user_id for t in db.query(WidgetToken).filter_by(household_id=s.h.id)}
    assert tokens == {s.carla.id}


@pytest.mark.parametrize("depart", [_leave, _remove], ids=["leave", "remove"])
def test_departure_event_tells_clients_to_refetch(client, db, hh, depart, _mock_socket_emit):
    s = hh
    assert depart(client, s).status_code == 204
    events = {c.args[1]: c.args[2] for c in _mock_socket_emit.call_args_list}
    name = "household_member_left" if depart is _leave else "household_member_removed"
    payload = events[name]
    assert payload["user_id"] == str(s.ben.id)
    # Welche Bereiche sich geändert haben → Clients laden genau diese neu
    assert set(payload["released"]) == {"todos", "shopping", "chores", "recurring_bills", "polls"}


# ---------------------------------------------------------------------------
# Rotation: Wer als Nächstes dran ist, bleibt gleich
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rotation", "index", "leaver", "expected_next"),
    [
        (["a", "b", "c"], 0, "b", "a"),  # Entfernte Position nach der nächsten
        (["a", "b", "c"], 2, "a", "c"),  # davor → Index rückt nach
        (["a", "b", "c"], 1, "b", "c"),  # die Nächste selbst → die Folgende
        (["a", "b", "c"], 2, "c", "a"),  # Letzte ist dran und geht → wieder von vorn
        (["a", "b", "c"], 7, "a", "b"),  # mehrere Runden (7 % 3 = 1 → b), davor entfernt
    ],
)
def test_remove_from_rotation_keeps_next_person(rotation, index, leaver, expected_next):
    chore = SimpleNamespace(rotation_order=list(rotation), next_rotation_index=index)
    # Erwartung ohne Austritt: rotation[index % len], Nicht-Mitglieder übersprungen
    _remove_from_rotation(chore, leaver)
    assert leaver not in chore.rotation_order
    assert chore.rotation_order[chore.next_rotation_index % len(chore.rotation_order)] == expected_next


def test_remove_last_person_from_rotation_empties_it():
    chore = SimpleNamespace(rotation_order=["a"], next_rotation_index=5)
    _remove_from_rotation(chore, "a")
    assert chore.rotation_order == []
    assert chore.next_rotation_index == 0


# ---------------------------------------------------------------------------
# Attention/Badge/Widget: Ex-Mitglieder gelten als "niemand zugewiesen"
# ---------------------------------------------------------------------------


def test_attention_counts_items_of_ex_members_as_unassigned(db, hh):
    """Altbestand (vor PD-H1) oder Zuweisung an ein Ex-Mitglied: zählt für alle."""
    s = hh
    db.query(HouseholdMember).filter_by(household_id=s.h.id, user_id=s.ben.id).delete()
    db.commit()

    items = due_items(db, s.h, s.carla.id)
    titles = {(i.kind, i.title, i.mine) for i in items}
    assert ("todo", "Altglas", False) in titles
    assert ("chore", "Bad putzen", False) in titles  # überfälliger Termin von Ben


def test_dashboard_shows_ex_member_chore_as_unassigned(client, db, hh):
    s = hh
    today_assignment = ChoreAssignment(household_id=s.h.id, chore_id=s.chore.id, assigned_user_id=s.ben.id, due_date=date.today())
    db.add(today_assignment)
    db.query(HouseholdMember).filter_by(household_id=s.h.id, user_id=s.ben.id).delete()
    db.commit()

    resp = client.get(f"/api/households/{s.h.id}/dashboard", headers=_auth(create_access_token(str(s.carla.id))))
    assert resp.status_code == 200
    chores = resp.json()["chores"]["items"]
    assert [c["assigned_user_id"] for c in chores if c["id"] == str(today_assignment.id)] == [None]
