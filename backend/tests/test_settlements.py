"""Umfassende Tests für Settlements: Scoping, CRUD, Validierung, Balance-Integration, Socket-Events."""
import uuid


# ---------------------------------------------------------------------------
# 1. Scoping-Tests (Cross-Household-Isolation)
# ---------------------------------------------------------------------------


def test_user_a_cannot_list_settlements_in_other_household(client, household_b, token_a):
    """GET auf fremden Household → 403."""
    resp = client.get(
        f"/api/households/{household_b.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_create_settlement_in_other_household(client, household_b, token_a, user_b):
    """POST auf fremden Household → 403."""
    resp = client.post(
        f"/api/households/{household_b.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_b.id),
            "to_user_id": str(user_b.id),  # egal, kommt nicht so weit
            "amount_rappen": 1000,
        },
    )
    assert resp.status_code == 403


def test_user_a_cannot_delete_settlement_in_other_household(client, household_b, token_a):
    """DELETE auf fremden Household → 403."""
    resp = client.delete(
        f"/api/households/{household_b.id}/settlements/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 2. CRUD-Tests
# ---------------------------------------------------------------------------


def test_create_settlement_success(client, household_a, token_a, user_a, user_a2):
    """POST valid → 201, Felder korrekt."""
    resp = client.post(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_a2.id),
            "to_user_id": str(user_a.id),
            "amount_rappen": 5000,
            "note": "Ausgleich Monat Juli",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["amount_rappen"] == 5000
    assert data["from_user_id"] == str(user_a2.id)
    assert data["to_user_id"] == str(user_a.id)
    assert data["currency"] == "CHF"
    assert data["note"] == "Ausgleich Monat Juli"
    assert data["created_by_user_id"] == str(user_a.id)  # token_a = user_a
    assert "id" in data
    assert "settled_date" in data
    assert "created_at" in data


def test_created_settlement_appears_in_list(client, household_a, token_a, user_a, user_a2):
    """POST gefolgt von GET — Settlement in Liste."""
    client.post(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_a2.id),
            "to_user_id": str(user_a.id),
            "amount_rappen": 3000,
        },
    )
    resp = client.get(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["amount_rappen"] == 3000


def test_delete_settlement_success(client, household_a, token_a, user_a, user_a2):
    """DELETE → 204, danach nicht mehr in GET."""
    create_resp = client.post(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_a2.id),
            "to_user_id": str(user_a.id),
            "amount_rappen": 2000,
        },
    )
    settlement_id = create_resp.json()["id"]

    del_resp = client.delete(
        f"/api/households/{household_a.id}/settlements/{settlement_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert del_resp.status_code == 204

    list_resp = client.get(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert len(list_resp.json()) == 0


# ---------------------------------------------------------------------------
# 3. Validierungs-Tests
# ---------------------------------------------------------------------------


def test_create_settlement_from_equals_to_returns_422(client, household_a, token_a, user_a):
    """from_user_id == to_user_id → 422."""
    resp = client.post(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_a.id),
            "to_user_id": str(user_a.id),
            "amount_rappen": 1000,
        },
    )
    assert resp.status_code == 422


def test_create_settlement_user_not_in_household_returns_422(client, household_a, token_a, user_a, user_b):
    """User aus anderem Household → 422."""
    resp = client.post(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_b.id),
            "to_user_id": str(user_a.id),
            "amount_rappen": 1000,
        },
    )
    assert resp.status_code == 422


def test_create_settlement_zero_amount_returns_422(client, household_a, token_a, user_a, user_a2):
    """amount_rappen == 0 → 422 (Pydantic gt=0)."""
    resp = client.post(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_a2.id),
            "to_user_id": str(user_a.id),
            "amount_rappen": 0,
        },
    )
    assert resp.status_code == 422


def test_create_settlement_negative_amount_returns_422(client, household_a, token_a, user_a, user_a2):
    """amount_rappen < 0 → 422 (Pydantic gt=0)."""
    resp = client.post(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_a2.id),
            "to_user_id": str(user_a.id),
            "amount_rappen": -500,
        },
    )
    assert resp.status_code == 422


def test_delete_nonexistent_settlement_returns_404(client, household_a, token_a):
    """DELETE mit nicht-existierender ID → 404."""
    resp = client.delete(
        f"/api/households/{household_a.id}/settlements/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Balance-Integration-Test (WICHTIGSTER Test!)
# ---------------------------------------------------------------------------


def test_settlement_zeroes_out_balances(client, household_a, token_a, user_a, user_a2):
    """
    Szenario: Expense 100.00 CHF, even split A/A2, bezahlt von A.
    → Saldo A = +5000, A2 = -5000.
    Settlement A2→A über 5000 (A2 zahlt seine Schuld an A).
    → Beide Saldi = 0, compute_settlements liefert leere Liste.
    """
    # 1. Expense erstellen
    client.post(
        f"/api/households/{household_a.id}/expenses/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "description": "Grosseinkauf",
            "amount_rappen": 10000,
            "paid_by_user_id": str(user_a.id),
            "split_type": "even",
        },
    )

    # 2. Balances prüfen: A positiv, A2 negativ
    bal_resp = client.get(
        f"/api/households/{household_a.id}/expenses/balances",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    bal_data = bal_resp.json()
    balances_map = {b["user_id"]: b for b in bal_data["balances"]}
    assert balances_map[str(user_a.id)]["saldo_rappen"] == 5000
    assert balances_map[str(user_a2.id)]["saldo_rappen"] == -5000
    assert len(bal_data["settlements"]) == 1  # ein Vorschlag

    # 3. Settlement: A2 zahlt A 50.00 CHF
    client.post(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_a2.id),
            "to_user_id": str(user_a.id),
            "amount_rappen": 5000,
        },
    )

    # 4. Balances erneut prüfen: beide Saldi 0
    bal_resp2 = client.get(
        f"/api/households/{household_a.id}/expenses/balances",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    bal_data2 = bal_resp2.json()
    balances_map2 = {b["user_id"]: b for b in bal_data2["balances"]}
    assert balances_map2[str(user_a.id)]["saldo_rappen"] == 0
    assert balances_map2[str(user_a2.id)]["saldo_rappen"] == 0
    assert balances_map2[str(user_a.id)]["settled_in_rappen"] == 5000
    assert balances_map2[str(user_a2.id)]["settled_out_rappen"] == 5000
    assert len(bal_data2["settlements"]) == 0  # keine Vorschläge mehr


# ---------------------------------------------------------------------------
# 5. Socket-Event-Tests
# ---------------------------------------------------------------------------


class TestSettlementSocketEvents:
    def test_create_emits_settlement_created(
        self, client, household_a, token_a, user_a, user_a2, _mock_socket_emit
    ):
        _mock_socket_emit.reset_mock()
        resp = client.post(
            f"/api/households/{household_a.id}/settlements/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "from_user_id": str(user_a2.id),
                "to_user_id": str(user_a.id),
                "amount_rappen": 3000,
            },
        )
        assert resp.status_code == 201

        calls = _mock_socket_emit.call_args_list
        settlement_calls = [c for c in calls if c[0][1] == "settlement_created"]
        assert len(settlement_calls) == 1
        payload = settlement_calls[0][0][2]
        assert payload["amount_rappen"] == 3000
        assert settlement_calls[0][0][0] == household_a.id

    def test_delete_emits_settlement_deleted(
        self, client, household_a, token_a, user_a, user_a2, _mock_socket_emit
    ):
        create_resp = client.post(
            f"/api/households/{household_a.id}/settlements/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "from_user_id": str(user_a2.id),
                "to_user_id": str(user_a.id),
                "amount_rappen": 2000,
            },
        )
        settlement_id = create_resp.json()["id"]

        _mock_socket_emit.reset_mock()
        client.delete(
            f"/api/households/{household_a.id}/settlements/{settlement_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )

        calls = _mock_socket_emit.call_args_list
        delete_calls = [c for c in calls if c[0][1] == "settlement_deleted"]
        assert len(delete_calls) == 1
        payload = delete_calls[0][0][2]
        assert payload["id"] == settlement_id

    def test_failed_create_no_event(
        self, client, household_a, token_a, user_a, _mock_socket_emit
    ):
        """422 bei fehlgeschlagenem POST → kein Event."""
        _mock_socket_emit.reset_mock()
        resp = client.post(
            f"/api/households/{household_a.id}/settlements/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "from_user_id": str(user_a.id),
                "to_user_id": str(user_a.id),  # same user → 422
                "amount_rappen": 1000,
            },
        )
        assert resp.status_code == 422
        settlement_calls = [
            c for c in _mock_socket_emit.call_args_list
            if c[0][1].startswith("settlement_")
        ]
        assert len(settlement_calls) == 0
