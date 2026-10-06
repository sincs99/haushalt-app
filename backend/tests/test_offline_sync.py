"""
Tests für die Offline-Sync-Grundlagen (docs/offline-first-phase2.md, Meilenstein M0).

- B1: Client-generierte IDs → idempotente Creates (Shopping-Items, -Listen, Todos)
- B2: updated_at + version auf Shopping-Listen/-Items, Todos, Chore-Assignments
"""

import uuid
from datetime import date

from app.models import Chore, ChoreAssignment, ShoppingItem, ShoppingList, Todo


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _items_url(household_id) -> str:
    return f"/api/households/{household_id}/shopping-items/"


def _lists_url(household_id) -> str:
    return f"/api/households/{household_id}/shopping-lists/"


def _todos_url(household_id) -> str:
    return f"/api/households/{household_id}/todos/"


def _emitted(mock_emit, event_name: str) -> list:
    return [c for c in mock_emit.call_args_list if c.args[1] == event_name]


# ===========================================================================
# B1 — Shopping-Items: idempotenter Create mit Client-ID
# ===========================================================================


def test_create_item_with_client_id_uses_that_id(
    client, household_a, token_a, shopping_list_a
):
    client_id = uuid.uuid4()
    resp = client.post(
        _items_url(household_a.id),
        headers=_auth(token_a),
        json={"id": str(client_id), "name": "Milch", "list_id": str(shopping_list_a.id)},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == str(client_id)
    assert data["version"] == 1
    assert data["updated_at"] is not None


def test_repeated_item_create_returns_existing_without_duplicate(
    client, db, household_a, token_a, shopping_list_a, _mock_socket_emit
):
    client_id = uuid.uuid4()
    body = {"id": str(client_id), "name": "Milch", "list_id": str(shopping_list_a.id)}

    first = client.post(_items_url(household_a.id), headers=_auth(token_a), json=body)
    # Retry, z.B. nach verlorener Antwort — auch mit abweichendem Payload
    second = client.post(
        _items_url(household_a.id),
        headers=_auth(token_a),
        json={**body, "name": "Milch (Retry)"},
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert db.query(ShoppingItem).filter(ShoppingItem.id == client_id).count() == 1
    # Nur der erste Create erzeugt ein Socket-Event
    assert len(_emitted(_mock_socket_emit, "shopping_item_created")) == 1


def test_item_create_with_id_of_other_household_is_rejected(
    client, db, household_a, token_a, shopping_list_a, shopping_item_b
):
    resp = client.post(
        _items_url(household_a.id),
        headers=_auth(token_a),
        json={
            "id": str(shopping_item_b.id),
            "name": "Übernahme",
            "list_id": str(shopping_list_a.id),
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "ENTITY_ID_CONFLICT"
    # Kein Leak: Antwort enthält keine Daten des fremden Items
    assert "household_id" not in resp.text
    db.refresh(shopping_item_b)
    assert shopping_item_b.name != "Übernahme"


def test_item_create_without_id_still_generates_server_id(
    client, household_a, token_a, shopping_list_a
):
    resp = client.post(
        _items_url(household_a.id),
        headers=_auth(token_a),
        json={"name": "Brot", "list_id": str(shopping_list_a.id)},
    )
    assert resp.status_code == 201
    uuid.UUID(resp.json()["id"])


def test_item_create_with_invalid_id_is_422(
    client, household_a, token_a, shopping_list_a
):
    resp = client.post(
        _items_url(household_a.id),
        headers=_auth(token_a),
        json={"id": "not-a-uuid", "name": "Brot", "list_id": str(shopping_list_a.id)},
    )
    assert resp.status_code == 422


def test_item_delete_twice_is_204_then_404(
    client, household_a, token_a, shopping_item_a
):
    """Dokumentiert das Verhalten, auf das die Outbox baut (404 bei Delete = Erfolg)."""
    url = f"{_items_url(household_a.id)}{shopping_item_a.id}"
    assert client.delete(url, headers=_auth(token_a)).status_code == 204
    assert client.delete(url, headers=_auth(token_a)).status_code == 404


# ===========================================================================
# B1 — Shopping-Listen
# ===========================================================================


def test_repeated_list_create_returns_existing(
    client, db, household_a, token_a, _mock_socket_emit
):
    client_id = uuid.uuid4()
    body = {"id": str(client_id), "name": "Baumarkt"}

    first = client.post(_lists_url(household_a.id), headers=_auth(token_a), json=body)
    second = client.post(_lists_url(household_a.id), headers=_auth(token_a), json=body)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == str(client_id)
    assert second.json() == first.json()
    assert db.query(ShoppingList).filter(ShoppingList.id == client_id).count() == 1
    assert len(_emitted(_mock_socket_emit, "shopping_list_created")) == 1


def test_list_create_with_id_of_other_household_is_rejected(
    client, household_a, token_a, shopping_list_b
):
    resp = client.post(
        _lists_url(household_a.id),
        headers=_auth(token_a),
        json={"id": str(shopping_list_b.id), "name": "Fremd"},
    )
    assert resp.status_code == 409


# ===========================================================================
# B1 — Todos
# ===========================================================================


def test_repeated_todo_create_returns_existing(
    client, db, household_a, token_a, _mock_socket_emit
):
    client_id = uuid.uuid4()
    body = {"id": str(client_id), "title": "Velo flicken", "tags": ["draussen"]}

    first = client.post(_todos_url(household_a.id), headers=_auth(token_a), json=body)
    second = client.post(_todos_url(household_a.id), headers=_auth(token_a), json=body)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == str(client_id)
    assert second.json() == first.json()
    assert second.json()["reminders"] == []
    assert db.query(Todo).filter(Todo.id == client_id).count() == 1
    assert len(_emitted(_mock_socket_emit, "todo_created")) == 1


def test_todo_create_with_id_of_other_household_is_rejected(
    client, db, household_a, household_b, token_a, user_b
):
    foreign = Todo(household_id=household_b.id, title="Fremd", created_by_user_id=user_b.id)
    db.add(foreign)
    db.commit()

    resp = client.post(
        _todos_url(household_a.id),
        headers=_auth(token_a),
        json={"id": str(foreign.id), "title": "Übernahme"},
    )
    assert resp.status_code == 409


# ===========================================================================
# B2 — version / updated_at
# ===========================================================================


def test_item_patch_increments_version_and_updated_at(
    client, household_a, token_a, shopping_item_a, _mock_socket_emit
):
    url = f"{_items_url(household_a.id)}{shopping_item_a.id}"
    before = client.get(
        _items_url(household_a.id) + "?include_checked=true", headers=_auth(token_a)
    ).json()[0]
    assert before["version"] == 1

    resp = client.patch(url, headers=_auth(token_a), json={"is_checked": True})
    assert resp.status_code == 200
    after = resp.json()
    assert after["version"] == 2
    assert after["updated_at"] >= before["updated_at"]

    # Socket-Payload trägt die neue Version (Client verwirft damit veraltete Events)
    payload = _emitted(_mock_socket_emit, "shopping_item_updated")[-1].args[2]
    assert payload["version"] == 2

    resp = client.patch(url, headers=_auth(token_a), json={"name": "Hafermilch"})
    assert resp.json()["version"] == 3


def test_patch_without_net_change_keeps_version(
    client, household_a, token_a, todo_a
):
    url = f"{_todos_url(household_a.id)}{todo_a.id}"
    resp = client.patch(url, headers=_auth(token_a), json={"title": todo_a.title})
    assert resp.status_code == 200
    assert resp.json()["version"] == 1


def test_todo_patch_and_claim_increment_version(
    client, household_a, token_a, todo_a
):
    url = f"{_todos_url(household_a.id)}{todo_a.id}"
    resp = client.patch(url, headers=_auth(token_a), json={"is_done": True})
    assert resp.json()["version"] == 2

    # Claim nutzt ein Core-UPDATE und muss version selbst erhöhen
    resp = client.post(f"{url}/claim", headers=_auth(token_a))
    assert resp.status_code == 200
    assert resp.json()["version"] == 3


def test_list_patch_increments_version(
    client, household_a, token_a, shopping_list_a
):
    resp = client.patch(
        f"{_lists_url(household_a.id)}{shopping_list_a.id}",
        headers=_auth(token_a),
        json={"name": "Wocheneinkauf"},
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 2


def test_assignment_complete_increments_version_once(
    client, db, household_a, token_a, user_a
):
    chore = Chore(
        household_id=household_a.id,
        title="Bad putzen",
        recurrence="weekly",
        weekday=0,
        rotation_order=[str(user_a.id)],
        anchor_date=date(2026, 8, 3),
    )
    db.add(chore)
    db.flush()
    assignment = ChoreAssignment(
        household_id=household_a.id,
        chore_id=chore.id,
        assigned_user_id=user_a.id,
        due_date=date(2026, 8, 10),
    )
    db.add(assignment)
    db.commit()

    url = f"/api/households/{household_a.id}/chores/assignments/{assignment.id}"
    first = client.post(f"{url}/complete", headers=_auth(token_a))
    assert first.status_code == 200
    assert first.json()["version"] == 2

    # Idempotent: zweites complete ändert nichts, auch nicht die Version
    second = client.post(f"{url}/complete", headers=_auth(token_a))
    assert second.status_code == 200
    assert second.json()["version"] == 2

    third = client.post(f"{url}/uncomplete", headers=_auth(token_a))
    assert third.json()["version"] == 3


def test_concurrent_item_create_with_same_id_returns_existing(
    client, db, household_a, token_a, shopping_item_a, shopping_list_a, _mock_socket_emit
):
    """Race: Vorab-Check findet nichts, ein paralleler Request hat aber schon
    committet → PK-Kollision beim Commit → bestehendes Item statt 500."""
    from unittest.mock import patch

    existing_id, existing_name = shopping_item_a.id, shopping_item_a.name
    # Wie ein paralleler Request: die Session kennt das bestehende Item nicht
    db.expunge(shopping_item_a)

    with patch("app.routers.shopping.get_existing_by_client_id", return_value=None):
        resp = client.post(
            _items_url(household_a.id),
            headers=_auth(token_a),
            json={
                "id": str(existing_id),
                "name": "Parallel",
                "list_id": str(shopping_list_a.id),
            },
        )
    assert resp.status_code == 200
    assert resp.json()["id"] == str(existing_id)
    assert resp.json()["name"] == existing_name
    assert len(_emitted(_mock_socket_emit, "shopping_item_created")) == 0
