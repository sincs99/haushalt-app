"""Einkauf auf PostgreSQL: parallele "Fehlende Zutaten" und Items in gelöschte Listen (CASA-53, CASA-24)."""

import uuid

from app.models import ShoppingItem, ShoppingList
from tests.pg.harness import run_parallel, status_codes


def _list(client, hh, name="Einkauf"):
    resp = client.post(hh.url("/shopping-lists/"), json={"name": name}, headers=hh.headers())
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_parallel_bulk_add_no_duplicates(client, household, db):
    target = _list(client, household)
    other = _list(client, household, "Andere")

    def add(i):
        return client.post(
            household.url("/shopping-items/bulk-add"),
            json={"list_id": target if i % 2 == 0 else other, "items": ["500 g Mehl", "Eier", "Milch"]},
            headers=household.headers(i % 2),
        )

    codes = status_codes(run_parallel(add, 6))
    assert 500 not in codes, codes
    db.expire_all()
    names = [i.name for i in db.query(ShoppingItem).filter_by(household_id=household.id).all()]
    assert sorted(names) == ["500 g Mehl", "Eier", "Milch"], names


def test_parallel_add_missing_without_list_creates_one_list(client, household, db):
    recipe = client.post(
        household.url("/recipes/"), json={"name": "Zopf", "ingredients": ["Mehl", "Butter"]},
        headers=household.headers(),
    ).json()
    entry = client.put(
        household.url("/meal-plan/2026-10-17"), json={"recipe_id": recipe["id"]}, headers=household.headers()
    ).json()

    def add(i):
        return client.post(
            household.url(f"/meal-plan/{entry['id']}/add-missing-to-shopping"), headers=household.headers(i % 2)
        )

    codes = status_codes(run_parallel(add, 4))
    assert 500 not in codes, codes
    db.expire_all()
    assert db.query(ShoppingList).filter_by(household_id=household.id).count() == 1
    assert db.query(ShoppingItem).filter_by(household_id=household.id).count() == 2


def test_item_into_concurrently_deleted_list_never_500(client, make_household, db):
    for _ in range(5):
        hh = make_household(["Anna", "Ben"])
        doomed = _list(client, hh)
        client.post(hh.url("/shopping-items/"), json={"name": "Alt", "list_id": doomed}, headers=hh.headers())

        def act(i, hh=hh, doomed=doomed):
            if i == 0:
                return client.delete(hh.url(f"/shopping-lists/{doomed}?force=true"), headers=hh.headers(0))
            return client.post(
                hh.url("/shopping-items/"), json={"name": f"Neu {i}", "list_id": doomed}, headers=hh.headers(1)
            )

        results = run_parallel(act, 4)
        codes = status_codes(results)
        assert 500 not in codes, codes
        assert codes[0] == 204, codes
        assert set(codes[1:]) <= {201, 404}, codes
        db.expire_all()
        assert db.get(ShoppingList, uuid.UUID(doomed)) is None
        # Kein bestätigtes Item zeigt auf eine gelöschte Liste
        assert db.query(ShoppingItem).filter_by(list_id=uuid.UUID(doomed)).count() == 0
