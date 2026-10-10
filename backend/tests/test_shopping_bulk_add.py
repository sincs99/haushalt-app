"""
CASA-53 / CASA-34 / PD-M2: Ein Bulk-Endpunkt für "Fehlende Zutaten" (Rezept UND KI).

POST /shopping-items/bulk-add {list_id, items}
- Ziel ist die vom Client übergebene (aktive) Liste.
- Dedupe case-insensitiv gegen OFFENE Items auf ALLEN Listen des Haushalts,
  führende Mengenangaben ignoriert ("500 g Mehl" == "Mehl"); auch innerhalb der Anfrage.
- Wiederholen derselben Anfrage legt nichts doppelt an (idempotent).
- Liste gelöscht/fremd → 404 statt 500 (CASA-24).
"""

import uuid

import pytest

from app.models import ShoppingItem, ShoppingList
from app.routers.shopping import ingredient_key


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _bulk(client, household, token, list_id, items):
    return client.post(
        f"/api/households/{household.id}/shopping-items/bulk-add",
        headers=_auth(token),
        json={"list_id": str(list_id), "items": items},
    )


@pytest.fixture()
def second_list(db, household_a) -> ShoppingList:
    lst = ShoppingList(id=uuid.uuid4(), household_id=household_a.id, name="Migros", position=1)
    db.add(lst)
    db.commit()
    return lst


def _item(db, household, lst, name, checked=False, quantity=None):
    item = ShoppingItem(
        id=uuid.uuid4(), household_id=household.id, list_id=lst.id, name=name,
        is_checked=checked, quantity=quantity,
    )
    db.add(item)
    db.commit()
    return item


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        ("Mehl", "mehl"),
        ("500 g Mehl", "mehl"),
        ("500g Mehl", "mehl"),
        ("2 EL Olivenöl", "olivenöl"),
        ("1/2 Zitrone", "zitrone"),
        ("1,5 l Milch", "milch"),
        ("ca. 200 ml Rahm", "rahm"),
        ("3 Eier", "eier"),
        ("  Salz  ", "salz"),
        ("1 Prise Salz", "salz"),
        ("Gewürze", "gewürze"),
        ("7Up", "7up"),
    ],
)
def test_ingredient_key(raw, key):
    assert ingredient_key(raw) == key


def test_bulk_add_dedupes_against_open_items_on_all_lists(
    client, db, household_a, token_a, shopping_list_a, second_list
):
    _item(db, household_a, second_list, "Mehl")          # offen, andere Liste
    _item(db, household_a, shopping_list_a, "milch")     # offen, Zielliste, andere Schreibweise
    _item(db, household_a, shopping_list_a, "Eier", checked=True)  # abgehakt → zählt nicht

    resp = _bulk(client, household_a, token_a, shopping_list_a.id,
                 ["500 g Mehl", "1 l Milch", "Eier", "Zucker", "zucker"])
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert [i["name"] for i in data["added"]] == ["Eier", "Zucker"]
    assert all(i["list_id"] == str(shopping_list_a.id) for i in data["added"])
    assert data["skipped"] == ["500 g Mehl", "1 l Milch", "zucker"]
    assert data["list_id"] == str(shopping_list_a.id)


def test_bulk_add_is_idempotent_on_retry(client, db, household_a, token_a, shopping_list_a):
    items = ["Spaghetti", "Tomaten"]
    first = _bulk(client, household_a, token_a, shopping_list_a.id, items).json()
    second = _bulk(client, household_a, token_a, shopping_list_a.id, items).json()
    assert len(first["added"]) == 2
    assert second["added"] == []
    assert second["skipped"] == items
    assert db.query(ShoppingItem).filter_by(household_id=household_a.id).count() == 2


def test_bulk_add_emits_created_items(client, household_a, token_a, shopping_list_a, _mock_socket_emit):
    _bulk(client, household_a, token_a, shopping_list_a.id, ["Brot"])
    names = [c.args[2]["name"] for c in _mock_socket_emit.call_args_list if c.args[1] == "shopping_item_created"]
    assert names == ["Brot"]


def test_bulk_add_foreign_or_missing_list_404(client, household_a, token_a, shopping_list_b):
    assert _bulk(client, household_a, token_a, shopping_list_b.id, ["Brot"]).status_code == 404
    assert _bulk(client, household_a, token_a, uuid.uuid4(), ["Brot"]).status_code == 404


def test_bulk_add_validates_items(client, household_a, token_a, shopping_list_a):
    assert _bulk(client, household_a, token_a, shopping_list_a.id, []).status_code == 422
    assert _bulk(client, household_a, token_a, shopping_list_a.id, ["x" * 201]).status_code == 422


def test_bulk_add_skips_blank_items(client, household_a, token_a, shopping_list_a):
    data = _bulk(client, household_a, token_a, shopping_list_a.id, ["  ", "Brot"]).json()
    assert [i["name"] for i in data["added"]] == ["Brot"]


def test_meal_plan_add_missing_uses_given_list_and_global_dedupe(
    client, db, household_a, token_a, meal_plan_entry_a, shopping_list_a, second_list
):
    _item(db, household_a, shopping_list_a, "Spaghetti")
    resp = client.post(
        f"/api/households/{household_a.id}/meal-plan/{meal_plan_entry_a.id}/add-missing-to-shopping",
        headers=_auth(token_a),
        json={"list_id": str(second_list.id)},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["list_id"] == str(second_list.id)
    assert data["skipped"] == ["Spaghetti"]
    assert set(data["added"]) == {"Hackfleisch", "Tomaten", "Zwiebeln"}


def test_create_item_in_missing_list_404(client, household_a, token_a):
    resp = client.post(
        f"/api/households/{household_a.id}/shopping-items/",
        headers=_auth(token_a),
        json={"name": "Brot", "list_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404
