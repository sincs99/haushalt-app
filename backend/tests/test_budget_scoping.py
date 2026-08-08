"""Multi-Tenant Scoping Tests für Budget."""


def test_user_a_can_upsert_own_budget(client, household_a, token_a):
    resp = client.put(
        f"/api/households/{household_a.id}/budget",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"month": "2026-08-01", "amount_rappen": 500000},
    )
    assert resp.status_code in (200, 201)
    data = resp.json()
    assert data["amount_rappen"] == 500000
    assert data["month"] == "2026-08-01"


def test_budget_upsert_updates_existing(client, household_a, token_a, budget_a):
    resp = client.put(
        f"/api/households/{household_a.id}/budget",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"month": "2026-08-01", "amount_rappen": 600000},
    )
    assert resp.status_code == 200
    assert resp.json()["amount_rappen"] == 600000


def test_user_a_cannot_upsert_budget_in_other_household(client, household_b, token_a):
    resp = client.put(
        f"/api/households/{household_b.id}/budget",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"month": "2026-08-01", "amount_rappen": 500000},
    )
    assert resp.status_code == 403


def test_budget_month_must_be_first(client, household_a, token_a):
    resp = client.put(
        f"/api/households/{household_a.id}/budget",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"month": "2026-08-15", "amount_rappen": 500000},
    )
    assert resp.status_code == 422


def test_user_a_can_read_own_budget(client, household_a, token_a, budget_a):
    resp = client.get(
        f"/api/households/{household_a.id}/budget",
        headers={"Authorization": f"Bearer {token_a}"},
        params={"month": "2026-08-01"},
    )
    assert resp.status_code == 200
    assert resp.json()["amount_rappen"] == 500000


def test_user_a_cannot_read_other_household_budget(client, household_b, token_a):
    resp = client.get(
        f"/api/households/{household_b.id}/budget",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_budget_returns_null_when_not_set(client, household_a, token_a):
    resp = client.get(
        f"/api/households/{household_a.id}/budget",
        headers={"Authorization": f"Bearer {token_a}"},
        params={"month": "2025-01-01"},
    )
    assert resp.status_code == 200
    assert resp.json() is None
