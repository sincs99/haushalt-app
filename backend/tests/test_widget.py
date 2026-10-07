"""
Homescreen-Widget: Nur-Lese-Schlüssel verwalten und Widget-Daten abrufen.
"""

from datetime import datetime, timedelta, timezone

from app.models import HouseholdMember, ShoppingItem, ShoppingList, Todo, WidgetToken


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _url(household):
    return f"/api/households/{household.id}/widget-token"


def _create(client, household, token):
    r = client.post(_url(household), headers=_auth(token))
    assert r.status_code == 201
    return r.json()["token"]


def test_status_without_token(client, household_a, token_a):
    r = client.get(_url(household_a), headers=_auth(token_a))
    assert r.status_code == 200
    assert r.json() == {"exists": False, "token_prefix": None, "created_at": None, "last_used_at": None}


def test_create_stores_only_hash(client, db, household_a, token_a, user_a):
    plain = _create(client, household_a, token_a)
    assert plain.startswith("hw_") and len(plain) > 40

    row = db.query(WidgetToken).one()
    assert row.user_id == user_a.id
    assert plain not in (row.token_hash, row.token_prefix)
    assert plain.startswith(row.token_prefix)

    r = client.get(_url(household_a), headers=_auth(token_a))
    assert r.json()["exists"] is True
    assert r.json()["token_prefix"] == row.token_prefix


def test_recreate_replaces_old_key(client, db, household_a, token_a):
    old = _create(client, household_a, token_a)
    new = _create(client, household_a, token_a)
    assert old != new
    assert db.query(WidgetToken).count() == 1
    assert client.get("/api/widget/summary", headers=_auth(old)).status_code == 401
    assert client.get("/api/widget/summary", headers=_auth(new)).status_code == 200


def test_delete_revokes(client, household_a, token_a):
    plain = _create(client, household_a, token_a)
    assert client.delete(_url(household_a), headers=_auth(token_a)).status_code == 204
    assert client.get("/api/widget/summary", headers=_auth(plain)).status_code == 401
    # Idempotent
    assert client.delete(_url(household_a), headers=_auth(token_a)).status_code == 204


def test_manage_requires_membership(client, household_a, token_b):
    assert client.post(_url(household_a), headers=_auth(token_b)).status_code in (403, 404)


def test_summary_rejects_missing_or_wrong_keys(client, household_a, token_a):
    assert client.get("/api/widget/summary").status_code == 401
    assert client.get("/api/widget/summary", headers=_auth("hw_wrong")).status_code == 401
    # Ein normales Login-Token ist kein Widget-Schlüssel
    r = client.get("/api/widget/summary", headers=_auth(token_a))
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "WIDGET_TOKEN_INVALID"


def test_widget_key_cannot_use_normal_api(client, household_a, token_a):
    plain = _create(client, household_a, token_a)
    r = client.get(f"/api/households/{household_a.id}/dashboard", headers=_auth(plain))
    assert r.status_code == 401


def test_summary_content(client, db, household_a, user_a, token_a):
    now = datetime.now(timezone.utc)
    db.add(Todo(household_id=household_a.id, title="Steuern", created_by_user_id=user_a.id,
                due_date=now - timedelta(days=2)))
    shopping_list = ShoppingList(household_id=household_a.id, name="Wocheneinkauf")
    db.add(shopping_list)
    db.flush()
    db.add_all([
        ShoppingItem(household_id=household_a.id, list_id=shopping_list.id, name="Milch", quantity="2"),
        ShoppingItem(household_id=household_a.id, list_id=shopping_list.id, name="Brot"),
        ShoppingItem(household_id=household_a.id, list_id=shopping_list.id, name="Alt", is_checked=True),
    ])
    db.commit()

    plain = _create(client, household_a, token_a)
    r = client.get("/api/widget/summary", headers=_auth(plain))
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    data = r.json()
    assert data["household"] == household_a.name
    assert data["user"] == user_a.display_name
    assert data["due_count"] == 1
    assert data["due"] == [{"kind": "todo", "title": "Steuern", "overdue": True, "mine": False}]
    assert data["shopping"] == {"open_count": 2, "items": ["2 Milch", "Brot"]}
    assert data["events"] == []

    row = db.query(WidgetToken).one()
    db.refresh(row)
    assert row.last_used_at is not None


def test_key_dies_when_user_leaves_household(client, db, household_a, user_a, token_a):
    plain = _create(client, household_a, token_a)
    db.query(HouseholdMember).filter(HouseholdMember.user_id == user_a.id).delete()
    db.commit()
    assert client.get("/api/widget/summary", headers=_auth(plain)).status_code == 401
    assert db.query(WidgetToken).count() == 0
