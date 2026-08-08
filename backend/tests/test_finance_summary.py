"""Tests für GET /households/{id}/finance-summary."""


def test_finance_summary_basic(client, household_a, token_a, user_a, budget_a, expense_a):
    resp = client.get(
        f"/api/households/{household_a.id}/finance-summary",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "budget_rappen" in data
    assert "total_spent_rappen" in data
    assert "by_category" in data
    assert "pending_bills" in data
    assert data["days_in_month"] > 0


def test_finance_summary_no_budget(client, household_a, token_a, user_a):
    resp = client.get(
        f"/api/households/{household_a.id}/finance-summary",
        headers={"Authorization": f"Bearer {token_a}"},
        params={"month": "2025-01-01"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["budget_rappen"] is None
    assert data["remaining_rappen"] is None


def test_finance_summary_scoping(client, household_b, token_a):
    resp = client.get(
        f"/api/households/{household_b.id}/finance-summary",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_finance_summary_shows_pending_bills(client, household_a, token_a, user_a, bill_a):
    resp = client.get(
        f"/api/households/{household_a.id}/finance-summary",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    pending = data["pending_bills"]
    assert any(b["id"] == str(bill_a.id) for b in pending)


def test_finance_summary_booked_bill_marked(client, household_a, token_a, user_a, bill_a):
    # Book the bill
    client.post(
        f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}/book",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    # Check summary
    resp = client.get(
        f"/api/households/{household_a.id}/finance-summary",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    pending = resp.json()["pending_bills"]
    bill_info = next((b for b in pending if b["id"] == str(bill_a.id)), None)
    assert bill_info is not None
    assert bill_info["is_booked_this_month"] is True
