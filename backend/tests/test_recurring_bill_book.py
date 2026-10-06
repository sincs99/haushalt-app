"""Idempotenz-Tests für POST /recurring-bills/{id}/book."""


def test_book_creates_expense(client, household_a, token_a, user_a, bill_a):
    resp = client.post(
        f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}/book",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["description"] == "Miete"
    assert data["amount_rappen"] == 150000
    assert data["category"] == "housing"
    assert data["recurring_bill_id"] == str(bill_a.id)


def test_book_idempotent_409(client, household_a, token_a, user_a, bill_a):
    # Erster Book
    resp1 = client.post(
        f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}/book",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp1.status_code == 201

    # Zweiter Book im selben Monat
    resp2 = client.post(
        f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}/book",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp2.status_code == 409


def test_book_inactive_bill_fails(client, household_a, token_a, user_a, inactive_bill_a):
    resp = client.post(
        f"/api/households/{household_a.id}/recurring-bills/{inactive_bill_a.id}/book",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 409


def test_book_other_household_bill_403(client, household_b, token_a, bill_b):
    resp = client.post(
        f"/api/households/{household_b.id}/recurring-bills/{bill_b.id}/book",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_book_creates_correct_shares(client, household_a, token_a, user_a, bill_a):
    resp = client.post(
        f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}/book",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    shares = data["shares"]
    assert len(shares) >= 1
    assert sum(s["amount_rappen"] for s in shares) == bill_a.amount_rappen


# ---------------------------------------------------------------------------
# Zahler
# ---------------------------------------------------------------------------


def _book(client, household, token, bill, json=None):
    return client.post(
        f"/api/households/{household.id}/recurring-bills/{bill.id}/book",
        headers={"Authorization": f"Bearer {token}"},
        json=json,
    )


def test_book_uses_default_payer(client, household_a, token_a, user_a, bill_a):
    resp = _book(client, household_a, token_a, bill_a)
    assert resp.status_code == 201
    assert resp.json()["paid_by_user_id"] == str(user_a.id)


def test_book_payer_override(client, household_a, token_a, user_a, user_a2, bill_a):
    resp = _book(client, household_a, token_a, bill_a, json={"paid_by_user_id": str(user_a2.id)})
    assert resp.status_code == 201
    assert resp.json()["paid_by_user_id"] == str(user_a2.id)


def test_book_without_any_payer_rejected(client, db, household_a, token_a, user_a, bill_a):
    bill_a.paid_by_user_id = None
    db.commit()
    resp = _book(client, household_a, token_a, bill_a)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "BILL_PAYER_REQUIRED"


def test_book_payer_must_be_member(client, household_a, token_a, user_a, user_b, bill_a):
    resp = _book(client, household_a, token_a, bill_a, json={"paid_by_user_id": str(user_b.id)})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "USERS_NOT_IN_HOUSEHOLD"


def test_booked_bill_keeps_balances_consistent(client, household_a, token_a, user_a, user_a2, bill_a):
    """Vorher: Rechnung ohne Zahler → Schulden ohne Gläubiger, Salden ≠ 0."""
    assert _book(client, household_a, token_a, bill_a).status_code == 201
    balances = client.get(
        f"/api/households/{household_a.id}/expenses/balances",
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()
    assert sum(b["saldo_rappen"] for b in balances["balances"]) == 0
    assert balances["unassigned_rappen"] == 0
    assert balances["settlements"] == [
        {"from_user_id": str(user_a2.id), "to_user_id": str(user_a.id), "amount_rappen": bill_a.amount_rappen // 2}
    ]


def test_bill_create_and_update_validate_payer(client, household_a, token_a, user_a, user_a2, user_b):
    url = f"/api/households/{household_a.id}/recurring-bills/"
    auth = {"Authorization": f"Bearer {token_a}"}
    body = {"name": "Internet", "amount_rappen": 5000, "day_of_month": 5}
    assert client.post(url, headers=auth, json={**body, "paid_by_user_id": str(user_b.id)}).status_code == 422
    created = client.post(url, headers=auth, json={**body, "paid_by_user_id": str(user_a.id)})
    assert created.status_code == 201
    assert created.json()["paid_by_user_id"] == str(user_a.id)
    bill_id = created.json()["id"]
    assert client.patch(f"{url}{bill_id}", headers=auth, json={"paid_by_user_id": str(user_b.id)}).status_code == 422
    updated = client.patch(f"{url}{bill_id}", headers=auth, json={"paid_by_user_id": str(user_a2.id)})
    assert updated.json()["paid_by_user_id"] == str(user_a2.id)
    summary = client.get(f"/api/households/{household_a.id}/finance-summary", headers=auth).json()
    assert {b["id"]: b["paid_by_user_id"] for b in summary["pending_bills"]}[bill_id] == str(user_a2.id)
