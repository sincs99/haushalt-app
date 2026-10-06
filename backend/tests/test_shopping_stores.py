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


# ===========================================================================
# Store-Normalisierung (case-insensitive, Whitespace)
# ===========================================================================


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _create(client, household, token, shopping_list, name, store):
    resp = client.post(
        f"/api/households/{household.id}/shopping-items/",
        headers=_headers(token),
        json={"name": name, "list_id": str(shopping_list.id), "store": store},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_normalizes_store_whitespace(
    client, household_a, token_a, shopping_list_a
):
    """Create: Whitespace wird getrimmt und Mehrfach-Leerzeichen zusammengefasst."""
    item = _create(client, household_a, token_a, shopping_list_a, "Milch", "  Coop   City  ")
    assert item["store"] == "Coop City"


def test_create_blank_store_becomes_null(
    client, household_a, token_a, shopping_list_a
):
    """Create: Nur-Whitespace-Store wird zu null."""
    item = _create(client, household_a, token_a, shopping_list_a, "Milch", "   ")
    assert item["store"] is None


def test_create_adopts_existing_spelling(
    client, household_a, token_a, shopping_list_a
):
    """Create: 'coop' übernimmt die vorhandene Schreibweise 'Coop' des Haushalts."""
    _create(client, household_a, token_a, shopping_list_a, "Brot", "Coop")
    item = _create(client, household_a, token_a, shopping_list_a, "Milch", "coop")
    assert item["store"] == "Coop"

    item = _create(client, household_a, token_a, shopping_list_a, "Käse", " COOP ")
    assert item["store"] == "Coop"

    stores = client.get(
        f"/api/households/{household_a.id}/shopping-items/stores",
        headers=_headers(token_a),
    ).json()
    assert stores == ["Coop"]


def test_update_adopts_existing_spelling(
    client, household_a, token_a, shopping_list_a
):
    """Update: Store-Wert wird normalisiert und an bestehende Schreibweise angeglichen."""
    base = f"/api/households/{household_a.id}/shopping-items"
    _create(client, household_a, token_a, shopping_list_a, "Brot", "Migros")
    item = _create(client, household_a, token_a, shopping_list_a, "Milch", None)

    resp = client.patch(
        f"{base}/{item['id']}",
        headers=_headers(token_a),
        json={"store": "  migros "},
    )
    assert resp.status_code == 200
    assert resp.json()["store"] == "Migros"

    # Leerer String → null
    resp = client.patch(
        f"{base}/{item['id']}", headers=_headers(token_a), json={"store": "  "}
    )
    assert resp.status_code == 200
    assert resp.json()["store"] is None


def test_update_only_item_of_store_can_change_case(
    client, household_a, token_a, shopping_list_a
):
    """Update: Das einzige Item eines Stores darf seine Schreibweise ändern."""
    base = f"/api/households/{household_a.id}/shopping-items"
    item = _create(client, household_a, token_a, shopping_list_a, "Milch", "coop")

    resp = client.patch(
        f"{base}/{item['id']}", headers=_headers(token_a), json={"store": "Coop"}
    )
    assert resp.status_code == 200
    assert resp.json()["store"] == "Coop"


def test_get_stores_case_insensitive_distinct(
    client, household_a, token_a, shopping_list_a, db
):
    """GET /stores: Altdaten mit abweichender Schreibweise → eine kanonische Gruppe."""
    from app.models import ShoppingItem

    # Altdaten direkt in die DB schreiben (umgeht die Normalisierung beim Create)
    for name, store in [
        ("Milch", "Coop"),
        ("Brot", "coop"),
        ("Käse", "Coop"),
        ("Wasser", "COOP "),
        ("Reis", "migros"),
        ("Tee", "Aldi"),
    ]:
        db.add(
            ShoppingItem(
                household_id=household_a.id,
                list_id=shopping_list_a.id,
                name=name,
                store=store,
            )
        )
    db.commit()

    resp = client.get(
        f"/api/households/{household_a.id}/shopping-items/stores",
        headers=_headers(token_a),
    )
    assert resp.status_code == 200
    # "Coop" ist die häufigste Schreibweise (2x) → kanonisch; Sortierung case-insensitive
    assert resp.json() == ["Aldi", "Coop", "migros"]


def test_get_stores_canonical_tie_is_deterministic(
    client, household_a, token_a, shopping_list_a, db
):
    """GET /stores: Bei Gleichstand gewinnt die alphabetisch kleinste Schreibweise."""
    from app.models import ShoppingItem

    for name, store in [("Milch", "coop"), ("Brot", "Coop")]:
        db.add(
            ShoppingItem(
                household_id=household_a.id,
                list_id=shopping_list_a.id,
                name=name,
                store=store,
            )
        )
    db.commit()

    resp = client.get(
        f"/api/households/{household_a.id}/shopping-items/stores",
        headers=_headers(token_a),
    )
    assert resp.json() == ["Coop"]


def test_reassign_store_matches_source_case_insensitive(
    client, household_a, token_a, shopping_list_a, db
):
    """POST /reassign-store: Quell-Store wird case-insensitive gematcht (inkl. Altdaten)."""
    from app.models import ShoppingItem

    base = f"/api/households/{household_a.id}/shopping-items"
    for name, store in [("Milch", "Coop"), ("Brot", "coop"), ("Käse", "COOP "), ("Tee", "Aldi")]:
        db.add(
            ShoppingItem(
                household_id=household_a.id,
                list_id=shopping_list_a.id,
                name=name,
                store=store,
            )
        )
    db.commit()

    resp = client.post(
        f"{base}/reassign-store",
        headers=_headers(token_a),
        json={"from_store": "cOOp", "to_store": "Migros"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 3, "to_store": "Migros"}

    items = client.get(f"{base}/?include_checked=true", headers=_headers(token_a)).json()
    stores = sorted(i["store"] for i in items)
    assert stores == ["Aldi", "Migros", "Migros", "Migros"]


def test_reassign_store_case_only_rename(
    client, household_a, token_a, shopping_list_a
):
    """POST /reassign-store: Reine Gross-/Kleinschreibungs-Änderung wird übernommen."""
    base = f"/api/households/{household_a.id}/shopping-items"
    _create(client, household_a, token_a, shopping_list_a, "Milch", "coop")
    _create(client, household_a, token_a, shopping_list_a, "Brot", "coop")

    resp = client.post(
        f"{base}/reassign-store",
        headers=_headers(token_a),
        json={"from_store": "coop", "to_store": "Coop"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 2, "to_store": "Coop"}

    stores = client.get(f"{base}/stores", headers=_headers(token_a)).json()
    assert stores == ["Coop"]


def test_reassign_store_merges_into_existing_spelling(
    client, household_a, token_a, shopping_list_a
):
    """POST /reassign-store: Ziel existiert case-insensitive → Merge in dessen Schreibweise."""
    base = f"/api/households/{household_a.id}/shopping-items"
    _create(client, household_a, token_a, shopping_list_a, "Milch", "Migros")
    _create(client, household_a, token_a, shopping_list_a, "Brot", "Coop")

    resp = client.post(
        f"{base}/reassign-store",
        headers=_headers(token_a),
        json={"from_store": "Migros", "to_store": " coop "},
    )
    assert resp.status_code == 200
    # Response meldet den tatsächlich verwendeten Ziel-Namen
    assert resp.json() == {"updated": 1, "to_store": "Coop"}

    items = client.get(f"{base}/?include_checked=true", headers=_headers(token_a)).json()
    assert all(i["store"] == "Coop" for i in items)

    stores = client.get(f"{base}/stores", headers=_headers(token_a)).json()
    assert stores == ["Coop"]


def test_reassign_store_normalizes_new_target(
    client, household_a, token_a, shopping_list_a
):
    """POST /reassign-store: Neuer Ziel-Store wird whitespace-normalisiert."""
    base = f"/api/households/{household_a.id}/shopping-items"
    _create(client, household_a, token_a, shopping_list_a, "Milch", "Migros")

    resp = client.post(
        f"{base}/reassign-store",
        headers=_headers(token_a),
        json={"from_store": "Migros", "to_store": "  Coop   City "},
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 1, "to_store": "Coop City"}


def test_reassign_store_dissolve_reports_null_target(
    client, household_a, token_a, shopping_list_a
):
    """POST /reassign-store: Auflösen meldet to_store=null."""
    base = f"/api/households/{household_a.id}/shopping-items"
    _create(client, household_a, token_a, shopping_list_a, "Milch", "Migros")

    resp = client.post(
        f"{base}/reassign-store",
        headers=_headers(token_a),
        json={"from_store": "MIGROS", "to_store": ""},
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 1, "to_store": None}


def test_reassign_store_blank_from_store_rejected(
    client, household_a, token_a, shopping_list_a
):
    """POST /reassign-store: Nur-Whitespace from_store → 422."""
    resp = client.post(
        f"/api/households/{household_a.id}/shopping-items/reassign-store",
        headers=_headers(token_a),
        json={"from_store": "   ", "to_store": "Coop"},
    )
    assert resp.status_code == 422


def test_store_normalization_is_tenant_scoped(
    client, household_a, household_b, token_a, token_b, shopping_list_a, shopping_list_b
):
    """Cross-Tenant: 'Coop' in Haushalt A beeinflusst Schreibweise/Reassign in Haushalt B nicht."""
    base_a = f"/api/households/{household_a.id}/shopping-items"
    base_b = f"/api/households/{household_b.id}/shopping-items"

    _create(client, household_a, token_a, shopping_list_a, "Milch", "Coop")

    # Haushalt B darf seine eigene Schreibweise behalten
    item_b = _create(client, household_b, token_b, shopping_list_b, "Brot", "coop")
    assert item_b["store"] == "coop"

    assert client.get(f"{base_a}/stores", headers=_headers(token_a)).json() == ["Coop"]
    assert client.get(f"{base_b}/stores", headers=_headers(token_b)).json() == ["coop"]

    # Reassign in B trifft nur Items von B
    resp = client.post(
        f"{base_b}/reassign-store",
        headers=_headers(token_b),
        json={"from_store": "COOP", "to_store": "Migros"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"updated": 1, "to_store": "Migros"}

    items_a = client.get(f"{base_a}/?include_checked=true", headers=_headers(token_a)).json()
    assert [i["store"] for i in items_a] == ["Coop"]
    assert client.get(f"{base_a}/stores", headers=_headers(token_a)).json() == ["Coop"]
