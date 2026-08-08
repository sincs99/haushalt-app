"""Multi-Tenant Scoping Tests für RecurringBill."""


def test_user_a_can_list_own_bills(client, household_a, token_a, bill_a):
    resp = client.get(
        f"/api/households/{household_a.id}/recurring-bills/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(b["id"] == str(bill_a.id) for b in data)


def test_user_a_cannot_list_other_household_bills(client, household_b, token_a):
    resp = client.get(
        f"/api/households/{household_b.id}/recurring-bills/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_user_a_can_create_bill(client, household_a, token_a):
    resp = client.post(
        f"/api/households/{household_a.id}/recurring-bills/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Strom",
            "amount_rappen": 8000,
            "day_of_month": 20,
            "category": "housing",
        },
    )
    assert resp.status_code == 201


def test_user_a_cannot_create_bill_in_other_household(client, household_b, token_a):
    resp = client.post(
        f"/api/households/{household_b.id}/recurring-bills/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Hack", "amount_rappen": 1000, "day_of_month": 1},
    )
    assert resp.status_code == 403


def test_user_a_can_patch_own_bill(client, household_a, token_a, bill_a):
    resp = client.patch(
        f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Miete (neu)"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Miete (neu)"


def test_user_a_cannot_patch_other_household_bill(client, household_b, token_a, bill_b):
    resp = client.patch(
        f"/api/households/{household_b.id}/recurring-bills/{bill_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Hack"},
    )
    assert resp.status_code == 403


def test_user_a_can_delete_own_bill(client, household_a, token_a, bill_a):
    resp = client.delete(
        f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 204


def test_inactive_bills_hidden_by_default(client, household_a, token_a, bill_a, inactive_bill_a):
    resp = client.get(
        f"/api/households/{household_a.id}/recurring-bills/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    ids = [b["id"] for b in resp.json()]
    assert str(bill_a.id) in ids
    assert str(inactive_bill_a.id) not in ids


def test_inactive_bills_shown_with_flag(client, household_a, token_a, bill_a, inactive_bill_a):
    resp = client.get(
        f"/api/households/{household_a.id}/recurring-bills/",
        headers={"Authorization": f"Bearer {token_a}"},
        params={"include_inactive": "true"},
    )
    assert resp.status_code == 200
    ids = [b["id"] for b in resp.json()]
    assert str(inactive_bill_a.id) in ids
