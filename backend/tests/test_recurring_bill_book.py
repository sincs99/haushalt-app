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
