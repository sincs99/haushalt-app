"""Mehrere zuständige Personen pro Aufgabe (todo_assignees).

Entscheide (Owner):
- beliebig viele Zuständige, keine = "offen für alle"
- "eine:r für alle": wer abhakt, erledigt die Aufgabe für alle; ``done_by_user_id``
  hält fest, wer es war
- "Ich übernehme" (claim) fügt mich hinzu, auch wenn schon andere eingetragen sind;
  bereits eingetragen → 200 ohne Änderung
- Übergangsweise (eine Version): das alte Feld ``assigned_to_user_id`` wird im
  Request noch angenommen und in der Antwort als erste zuständige Person geliefert
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import HouseholdMember, PushSubscription, Todo, TodoReminder
from app.services import push_service
from app.services.attention import due_items


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _url(household, path: str = "/") -> str:
    return f"/api/households/{household.id}/todos{path}"


def _emitted(mock, event: str) -> list[dict]:
    return [c.args[2] for c in mock.call_args_list if c.args[1] == event]


@pytest.fixture()
def user_a3(db, household_a):
    from app.core.security import hash_password
    from app.models import User

    u = User(id=uuid.uuid4(), email="carla@test.com", password_hash=hash_password("pw123456"), display_name="Carla")
    db.add(u)
    db.flush()
    db.add(HouseholdMember(household_id=household_a.id, user_id=u.id, role="member"))
    db.commit()
    return u


def _ids(*users) -> list[str]:
    return [str(u.id) for u in users]


# ---------------------------------------------------------------------------
# Anlegen
# ---------------------------------------------------------------------------


def test_create_with_several_assignees(client, household_a, token_a, user_a, user_a2, _mock_socket_emit):
    r = client.post(_url(household_a), headers=_auth(token_a),
                    json={"title": "Keller", "assignee_ids": _ids(user_a, user_a2, user_a)})
    assert r.status_code == 201, r.text
    body = r.json()
    # Doppelte werden zusammengefasst
    assert sorted(body["assignee_ids"]) == sorted(_ids(user_a, user_a2))
    assert body["done_by_user_id"] is None
    # Übergangsfeld: erste zuständige Person
    assert body["assigned_to_user_id"] in body["assignee_ids"]
    # Socket-Payload = volle TodoResponse
    created = _emitted(_mock_socket_emit, "todo_created")[-1]
    assert sorted(created["assignee_ids"]) == sorted(body["assignee_ids"])


def test_create_without_assignees_is_open_for_all(client, household_a, token_a):
    r = client.post(_url(household_a), headers=_auth(token_a), json={"title": "Offen"})
    assert r.status_code == 201
    assert r.json()["assignee_ids"] == []
    assert r.json()["assigned_to_user_id"] is None


def test_create_rejects_non_member_and_too_many(client, household_a, token_a, user_a, user_b):
    r = client.post(_url(household_a), headers=_auth(token_a),
                    json={"title": "X", "assignee_ids": _ids(user_a, user_b)})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "USERS_NOT_IN_HOUSEHOLD"

    too_many = [str(uuid.uuid4()) for _ in range(11)]
    r = client.post(_url(household_a), headers=_auth(token_a), json={"title": "X", "assignee_ids": too_many})
    assert r.status_code == 422


def test_create_legacy_field_maps_to_assignees(client, household_a, token_a, user_a2):
    r = client.post(_url(household_a), headers=_auth(token_a),
                    json={"title": "Alt", "assigned_to_user_id": str(user_a2.id)})
    assert r.status_code == 201
    assert r.json()["assignee_ids"] == [str(user_a2.id)]
    assert r.json()["assigned_to_user_id"] == str(user_a2.id)


def test_create_new_field_wins_over_legacy(client, household_a, token_a, user_a, user_a2):
    r = client.post(_url(household_a), headers=_auth(token_a), json={
        "title": "Beides", "assigned_to_user_id": str(user_a2.id), "assignee_ids": _ids(user_a),
    })
    assert r.status_code == 201
    assert r.json()["assignee_ids"] == [str(user_a.id)]


def test_create_idempotent_with_client_id_keeps_assignees(client, household_a, token_a, user_a, user_a2):
    todo_id = str(uuid.uuid4())
    payload = {"id": todo_id, "title": "Offline", "assignee_ids": _ids(user_a, user_a2)}
    first = client.post(_url(household_a), headers=_auth(token_a), json=payload)
    second = client.post(_url(household_a), headers=_auth(token_a), json=payload)
    assert first.status_code == 201 and second.status_code == 200
    assert sorted(second.json()["assignee_ids"]) == sorted(_ids(user_a, user_a2))


# ---------------------------------------------------------------------------
# Ändern
# ---------------------------------------------------------------------------


def test_patch_replaces_assignees_and_bumps_version(client, household_a, token_a, todo_a, user_a, user_a2, user_a3, _mock_socket_emit):
    url = _url(household_a, f"/{todo_a.id}")
    r = client.patch(url, headers=_auth(token_a), json={"assignee_ids": _ids(user_a, user_a2)})
    assert r.status_code == 200, r.text
    v1 = r.json()["version"]
    assert sorted(r.json()["assignee_ids"]) == sorted(_ids(user_a, user_a2))

    r = client.patch(url, headers=_auth(token_a), json={"assignee_ids": _ids(user_a2, user_a3)})
    assert r.status_code == 200
    assert sorted(r.json()["assignee_ids"]) == sorted(_ids(user_a2, user_a3))
    # Reine Zuständigkeits-Änderung zählt die Version hoch (Socket-Merge im Client)
    assert r.json()["version"] == v1 + 1
    assert _emitted(_mock_socket_emit, "todo_updated")[-1]["version"] == v1 + 1

    # Gleiche Menge nochmals → keine Änderung, keine neue Version
    r = client.patch(url, headers=_auth(token_a), json={"assignee_ids": _ids(user_a3, user_a2)})
    assert r.json()["version"] == v1 + 1

    r = client.patch(url, headers=_auth(token_a), json={"assignee_ids": []})
    assert r.json()["assignee_ids"] == []


def test_patch_assignee_ids_null_is_422(client, db, household_a, token_a, todo_a, user_a):
    todo_a.assignee_ids = [user_a.id]
    db.commit()
    r = client.patch(_url(household_a, f"/{todo_a.id}"), headers=_auth(token_a), json={"assignee_ids": None})
    assert r.status_code == 422
    db.expire_all()
    assert db.get(Todo, todo_a.id).assignee_ids == [user_a.id]


def test_patch_legacy_field(client, db, household_a, token_a, todo_a, user_a, user_a2):
    url = _url(household_a, f"/{todo_a.id}")
    r = client.patch(url, headers=_auth(token_a), json={"assigned_to_user_id": str(user_a2.id)})
    assert r.status_code == 200
    assert r.json()["assignee_ids"] == [str(user_a2.id)]
    # null = niemand (wie bisher)
    r = client.patch(url, headers=_auth(token_a), json={"assigned_to_user_id": None})
    assert r.status_code == 200
    assert r.json()["assignee_ids"] == []


def test_patch_other_fields_keep_assignees(client, db, household_a, token_a, todo_a, user_a, user_a2):
    todo_a.assignee_ids = [user_a.id, user_a2.id]
    db.commit()
    r = client.patch(_url(household_a, f"/{todo_a.id}"), headers=_auth(token_a), json={"title": "Neu"})
    assert r.status_code == 200
    assert sorted(r.json()["assignee_ids"]) == sorted(_ids(user_a, user_a2))


def test_patch_ex_member_on_record_may_stay_but_not_be_added(client, db, household_a, token_a, todo_a, user_a, user_a2, user_a3):
    todo_a.assignee_ids = [user_a2.id]
    db.commit()
    db.query(HouseholdMember).filter_by(household_id=household_a.id, user_id=user_a2.id).delete()
    db.commit()
    url = _url(household_a, f"/{todo_a.id}")
    # Bleibt stehen, neue Person kommt dazu
    r = client.patch(url, headers=_auth(token_a), json={"assignee_ids": _ids(user_a2, user_a)})
    assert r.status_code == 200, r.text
    # Ex-Mitglied neu hinzufügen (anderswo) geht nicht
    r = client.post(_url(household_a), headers=_auth(token_a), json={"title": "X", "assignee_ids": _ids(user_a2)})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Erledigen: eine:r für alle, done_by
# ---------------------------------------------------------------------------


def test_done_records_who_did_it(client, db, household_a, token_a, token_a2, todo_a, user_a, user_a2, _mock_socket_emit):
    todo_a.assignee_ids = [user_a.id, user_a2.id]
    db.commit()
    url = _url(household_a, f"/{todo_a.id}")
    r = client.patch(url, headers=_auth(token_a2), json={"is_done": True})
    assert r.status_code == 200
    assert r.json()["is_done"] is True
    assert r.json()["done_by_user_id"] == str(user_a2.id)
    assert _emitted(_mock_socket_emit, "todo_updated")[-1]["done_by_user_id"] == str(user_a2.id)

    # Zweites Abhaken durch jemand anderen ändert nichts am "wer"
    r = client.patch(url, headers=_auth(token_a), json={"is_done": True})
    assert r.json()["done_by_user_id"] == str(user_a2.id)

    # Wieder öffnen → leer
    r = client.patch(url, headers=_auth(token_a), json={"is_done": False})
    assert r.json()["done_by_user_id"] is None


def test_done_by_is_not_writable(client, household_a, token_a, todo_a, user_a2):
    r = client.patch(_url(household_a, f"/{todo_a.id}"), headers=_auth(token_a),
                     json={"done_by_user_id": str(user_a2.id)})
    assert r.status_code == 200
    assert r.json()["done_by_user_id"] is None


def test_done_by_set_null_when_user_deleted(db, household_a, todo_a, user_a2):
    todo_a.is_done = True
    todo_a.done_by_user_id = user_a2.id
    todo_a.assignee_ids = [user_a2.id]
    db.commit()
    db.query(HouseholdMember).filter_by(user_id=user_a2.id).delete()
    db.delete(user_a2)
    db.commit()
    db.expire_all()
    todo = db.get(Todo, todo_a.id)
    assert todo.done_by_user_id is None
    assert todo.assignee_ids == []


# ---------------------------------------------------------------------------
# Ich übernehme (claim)
# ---------------------------------------------------------------------------


def test_claim_adds_me_to_existing_assignees(client, db, household_a, token_a2, todo_a, user_a, user_a2, _mock_socket_emit):
    todo_a.assignee_ids = [user_a.id]
    db.commit()
    before = db.get(Todo, todo_a.id).version
    r = client.post(_url(household_a, f"/{todo_a.id}/claim"), headers=_auth(token_a2))
    assert r.status_code == 200, r.text
    assert sorted(r.json()["assignee_ids"]) == sorted(_ids(user_a, user_a2))
    assert r.json()["version"] == before + 1
    assert _emitted(_mock_socket_emit, "todo_updated")[-1]["version"] == before + 1


def test_claim_is_idempotent(client, db, household_a, token_a, todo_a, user_a, _mock_socket_emit):
    url = _url(household_a, f"/{todo_a.id}/claim")
    first = client.post(url, headers=_auth(token_a))
    assert first.status_code == 200
    events = len(_emitted(_mock_socket_emit, "todo_updated"))
    second = client.post(url, headers=_auth(token_a))
    assert second.status_code == 200
    assert second.json()["assignee_ids"] == [str(user_a.id)]
    assert second.json()["version"] == first.json()["version"]
    # Keine Änderung → kein weiteres Event
    assert len(_emitted(_mock_socket_emit, "todo_updated")) == events


def test_claim_done_todo_is_422(client, db, household_a, token_a, todo_a):
    todo_a.is_done = True
    db.commit()
    r = client.post(_url(household_a, f"/{todo_a.id}/claim"), headers=_auth(token_a))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "TODO_IS_DONE"


# ---------------------------------------------------------------------------
# Liste: "mir zugewiesen"
# ---------------------------------------------------------------------------


def test_list_assigned_to_me_matches_any_assignee(client, db, household_a, token_a, user_a, user_a2):
    db.add_all([
        Todo(household_id=household_a.id, title="beide", assignee_ids=[user_a2.id, user_a.id]),
        Todo(household_id=household_a.id, title="nur-ben", assignee_ids=[user_a2.id]),
        Todo(household_id=household_a.id, title="niemand"),
    ])
    db.commit()
    r = client.get(_url(household_a), headers=_auth(token_a), params={"assigned_to_me": True})
    assert [t["title"] for t in r.json()] == ["beide"]
    r = client.get(_url(household_a), headers=_auth(token_a))
    assert {t["title"] for t in r.json()} == {"beide", "nur-ben", "niemand"}


# ---------------------------------------------------------------------------
# Badge / Widget (attention)
# ---------------------------------------------------------------------------


def test_attention_counts_todo_for_every_assignee(db, household_a, user_a, user_a2, user_a3):
    due = datetime.now(timezone.utc) - timedelta(hours=1)
    ex = uuid.uuid4()  # nie Mitglied gewesen (Altbestand ohne FK-Prüfung in SQLite)
    from app.core.security import hash_password
    from app.models import User

    gone = User(id=ex, email="gone@test.com", password_hash=hash_password("pw123456"), display_name="Gone")
    db.add(gone)
    db.flush()
    db.add_all([
        Todo(household_id=household_a.id, title="zu-zweit", due_date=due, assignee_ids=[user_a.id, user_a2.id]),
        Todo(household_id=household_a.id, title="carla", due_date=due, assignee_ids=[user_a3.id]),
        Todo(household_id=household_a.id, title="alle", due_date=due),
        # Nur Ex-Mitglieder → gilt als niemandem zugewiesen
        Todo(household_id=household_a.id, title="verwaist", due_date=due, assignee_ids=[ex]),
        # Ex-Mitglied + Carla → Carla ist zuständig, nicht ich
        Todo(household_id=household_a.id, title="gemischt", due_date=due, assignee_ids=[ex, user_a3.id]),
    ])
    db.commit()

    mine = {i.title: i.mine for i in due_items(db, household_a, user_a.id) if i.kind == "todo"}
    assert mine == {"zu-zweit": True, "alle": False, "verwaist": False}
    ben = {i.title: i.mine for i in due_items(db, household_a, user_a2.id) if i.kind == "todo"}
    assert ben == {"zu-zweit": True, "alle": False, "verwaist": False}
    carla = {i.title: i.mine for i in due_items(db, household_a, user_a3.id) if i.kind == "todo"}
    assert carla == {"carla": True, "alle": False, "verwaist": False, "gemischt": True}


# ---------------------------------------------------------------------------
# Push-Erinnerung: alle zuständigen (aktuellen) Mitglieder, sonst alle
# ---------------------------------------------------------------------------


def _sub(db, user):
    sub = PushSubscription(user_id=user.id, endpoint=f"https://fcm.googleapis.com/fcm/send/{user.id.hex}",
                           p256dh="p256", auth="authsecret", locale="de")
    db.add(sub)
    db.commit()
    return sub


def _recipients(db, todo, mock_webpush) -> set[str]:
    now = datetime.now(timezone.utc)
    db.add(TodoReminder(household_id=todo.household_id, todo_id=todo.id, remind_at=now - timedelta(minutes=1)))
    db.commit()
    mock_webpush.reset_mock()
    push_service.process_todo_reminders(db, now)
    return {c.kwargs["subscription_info"]["endpoint"] for c in mock_webpush.call_args_list}


@pytest.fixture()
def mock_webpush():
    from unittest.mock import patch

    with patch("app.services.push_service.webpush") as m:
        yield m


def test_reminder_goes_to_all_member_assignees(db, household_a, todo_a, user_a, user_a2, user_a3, mock_webpush):
    subs = {u.id: _sub(db, u).endpoint for u in (user_a, user_a2, user_a3)}
    todo_a.assignee_ids = [user_a2.id, user_a3.id]
    db.commit()
    assert _recipients(db, todo_a, mock_webpush) == {subs[user_a2.id], subs[user_a3.id]}


def test_reminder_for_ex_member_only_goes_to_everyone(db, household_a, todo_a, user_a, user_a2, user_a3, mock_webpush):
    subs = {u.id: _sub(db, u).endpoint for u in (user_a, user_a2, user_a3)}
    todo_a.assignee_ids = [user_a3.id]
    db.commit()
    db.query(HouseholdMember).filter_by(household_id=household_a.id, user_id=user_a3.id).delete()
    db.commit()
    assert _recipients(db, todo_a, mock_webpush) == {subs[user_a.id], subs[user_a2.id]}


# ---------------------------------------------------------------------------
# NFC-Tag todo.done: wer scannt, hat erledigt; Details nennen alle Zuständigen
# ---------------------------------------------------------------------------


def test_tag_done_sets_done_by_and_lists_assignees(client, db, household_a, token_a2, todo_a, user_a, user_a2):
    from app.models import Tag
    from app.routers.tags import generate_tag_token

    todo_a.assignee_ids = [user_a.id, user_a2.id]
    tag = Tag(household_id=household_a.id, token=generate_tag_token(), label="Chip",
              target_type="todo", target_id=todo_a.id, action="todo.done")
    db.add(tag)
    db.commit()

    resolved = client.post(f"/api/tags/resolve/{tag.token}", headers=_auth(token_a2))
    assert resolved.status_code == 200
    names = resolved.json()["details"]["assigned_user_name"]
    assert user_a.display_name in names and user_a2.display_name in names

    r = client.post(f"/api/tags/{tag.token}/execute", headers=_auth(token_a2),
                    json={"confirm": resolved.json().get("confirm")})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Todo, todo_a.id).done_by_user_id == user_a2.id
