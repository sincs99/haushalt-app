"""
Tests für die Shopping-Store Endpoints:
  - GET  /stores          → distinct Store-Werte
  - POST /reassign-store  → Store-Wert umbenennen / auflösen
"""


# ===========================================================================
# GET /stores
# ===========================================================================


def test_get_stores_returns_distinct_values(
    client, household_a, token_a, shopping_list_a
):
    """GET /stores liefert distinct + alphabetisch sortierte Store-Namen."""
    headers = {"Authorization": f"Bearer {token_a}"}
    base = f"/api/households/{household_a.id}/shopping-items"

    # Items mit verschiedenen Stores anlegen
    for name, store in [
        ("Milch", "Migros"),
        ("Brot", "Coop"),
        ("Käse", "Migros"),
        ("Wasser", "Aldi"),
    ]:
        resp = client.post(
            f"{base}/",
            headers=headers,
            json={"name": name, "list_id": str(shopping_list_a.id), "store": store},
        )
        assert resp.status_code == 201

    resp = client.get(f"{base}/stores", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data == ["Aldi", "Coop", "Migros"]


def test_get_stores_excludes_null(
    client, household_a, token_a, shopping_list_a
):
    """Items ohne Store-Wert tauchen nicht in /stores auf."""
    headers = {"Authorization": f"Bearer {token_a}"}
    base = f"/api/households/{household_a.id}/shopping-items"

    # Item OHNE Store
    resp = client.post(
        f"{base}/",
        headers=headers,
        json={"name": "Tofu", "list_id": str(shopping_list_a.id)},
    )
    assert resp.status_code == 201

    # Item MIT Store
    resp = client.post(
        f"{base}/",
        headers=headers,
        json={"name": "Reis", "list_id": str(shopping_list_a.id), "store": "Migros"},
    )
    assert resp.status_code == 201

    resp = client.get(f"{base}/stores", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data == ["Migros"]


def test_get_stores_cross_tenant_forbidden(
    client, household_b, token_a, shopping_list_b, user_b
):
    """User A kann nicht Stores von Household B lesen → 403."""
    resp = client.get(
        f"/api/households/{household_b.id}/shopping-items/stores",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ===========================================================================
# POST /reassign-store
# ===========================================================================


def test_reassign_store_rename(
    client, household_a, token_a, shopping_list_a
):
    """Store von 'Migros' auf 'Coop' umbenennen — updated count + neuer Wert."""
    headers = {"Authorization": f"Bearer {token_a}"}
    base = f"/api/households/{household_a.id}/shopping-items"

    # 2 Items mit "Migros", 1 Item mit "Aldi"
    for name, store in [("Milch", "Migros"), ("Käse", "Migros"), ("Wasser", "Aldi")]:
        r = client.post(
            f"{base}/",
            headers=headers,
            json={"name": name, "list_id": str(shopping_list_a.id), "store": store},
        )
        assert r.status_code == 201

    resp = client.post(
        f"{base}/reassign-store",
        headers=headers,
        json={"from_store": "Migros", "to_store": "Coop"},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 2

    # Verifiziere: kein Item hat mehr "Migros", 2 haben "Coop"
    items_resp = client.get(
        f"{base}/?include_checked=true", headers=headers
    )
    items = items_resp.json()
    stores = [i["store"] for i in items]
    assert stores.count("Migros") == 0
    assert stores.count("Coop") == 2
    assert stores.count("Aldi") == 1


def test_reassign_store_dissolve(
    client, household_a, token_a, shopping_list_a
):
    """Store von 'Migros' auf null auflösen."""
    headers = {"Authorization": f"Bearer {token_a}"}
    base = f"/api/households/{household_a.id}/shopping-items"

    client.post(
        f"{base}/",
        headers=headers,
        json={"name": "Milch", "list_id": str(shopping_list_a.id), "store": "Migros"},
    )

    resp = client.post(
        f"{base}/reassign-store",
        headers=headers,
        json={"from_store": "Migros", "to_store": None},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1

    # Verifiziere: Item hat store=null
    items = client.get(
        f"{base}/?include_checked=true", headers=headers
    ).json()
    assert all(i["store"] is None for i in items)


def test_reassign_store_affects_checked_items(
    client, household_a, token_a, shopping_list_a
):
    """Auch erledigte (is_checked=true) Items werden umbenannt."""
    headers = {"Authorization": f"Bearer {token_a}"}
    base = f"/api/households/{household_a.id}/shopping-items"

    # Item erstellen
    r = client.post(
        f"{base}/",
        headers=headers,
        json={"name": "Milch", "list_id": str(shopping_list_a.id), "store": "Migros"},
    )
    item_id = r.json()["id"]

    # Item abhaken
    client.patch(
        f"{base}/{item_id}",
        headers=headers,
        json={"is_checked": True},
    )

    # Reassign
    resp = client.post(
        f"{base}/reassign-store",
        headers=headers,
        json={"from_store": "Migros", "to_store": "Coop"},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1

    # Verifiziere über include_checked=true
    items = client.get(
        f"{base}/?include_checked=true", headers=headers
    ).json()
    checked_item = next(i for i in items if i["id"] == item_id)
    assert checked_item["store"] == "Coop"
    assert checked_item["is_checked"] is True


def test_reassign_store_cross_tenant_forbidden(
    client, household_b, token_a, shopping_list_b, user_b
):
    """User A kann nicht in Household B reassignen → 403."""
    resp = client.post(
        f"/api/households/{household_b.id}/shopping-items/reassign-store",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"from_store": "Migros", "to_store": "Coop"},
    )
    assert resp.status_code == 403


def test_reassign_store_empty_from_store(
    client, household_a, token_a, shopping_list_a
):
    """Leerer from_store → 422 (Pydantic min_length=1 Validierung)."""
    resp = client.post(
        f"/api/households/{household_a.id}/shopping-items/reassign-store",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"from_store": "", "to_store": "Coop"},
    )
    assert resp.status_code == 422


def test_reassign_store_no_matching_items(
    client, household_a, token_a, shopping_list_a
):
    """Nicht existierender Store → 200 mit updated=0."""
    resp = client.post(
        f"/api/households/{household_a.id}/shopping-items/reassign-store",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"from_store": "GibtEsNicht", "to_store": "Coop"},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 0
