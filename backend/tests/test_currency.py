"""Tests für Household-Currency-Enforcement bei Expenses und Settlements."""
import uuid


# ---------------------------------------------------------------------------
# 1. Expense mit falscher Währung → 422 CURRENCY_MISMATCH
# ---------------------------------------------------------------------------


def test_expense_with_wrong_currency_rejected(client, household_a, token_a, user_a, user_a2):
    """EUR-Expense in CHF-Haushalt → 422 CURRENCY_MISMATCH."""
    resp = client.post(
        f"/api/households/{household_a.id}/expenses/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "description": "Hotel in Berlin",
            "amount_rappen": 15000,
            "currency": "EUR",
            "paid_by_user_id": str(user_a.id),
            "split_type": "even",
        },
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["detail"]["code"] == "CURRENCY_MISMATCH"


# ---------------------------------------------------------------------------
# 2. Expense ohne Currency → bekommt Household-Currency
# ---------------------------------------------------------------------------


def test_expense_without_currency_gets_household_currency(client, household_a, token_a, user_a, user_a2):
    """Expense ohne Currency-Feld → bekommt automatisch Household-Currency (CHF)."""
    resp = client.post(
        f"/api/households/{household_a.id}/expenses/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "description": "Einkauf",
            "amount_rappen": 5000,
            "paid_by_user_id": str(user_a.id),
            "split_type": "even",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["currency"] == "CHF"


# ---------------------------------------------------------------------------
# 3. Settlement mit falscher Währung → 422 CURRENCY_MISMATCH
# ---------------------------------------------------------------------------


def test_settlement_with_wrong_currency_rejected(client, household_a, token_a, user_a, user_a2):
    """EUR-Settlement in CHF-Haushalt → 422 CURRENCY_MISMATCH."""
    resp = client.post(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_a2.id),
            "to_user_id": str(user_a.id),
            "amount_rappen": 3000,
            "currency": "EUR",
        },
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["detail"]["code"] == "CURRENCY_MISMATCH"


# ---------------------------------------------------------------------------
# 4. Settlement ohne Currency → bekommt Household-Currency
# ---------------------------------------------------------------------------


def test_settlement_without_currency_gets_household_currency(client, household_a, token_a, user_a, user_a2):
    """Settlement ohne Currency-Feld → bekommt automatisch Household-Currency (CHF)."""
    resp = client.post(
        f"/api/households/{household_a.id}/settlements/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "from_user_id": str(user_a2.id),
            "to_user_id": str(user_a.id),
            "amount_rappen": 2000,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["currency"] == "CHF"


# ---------------------------------------------------------------------------
# 5. /api/auth/me enthält Household-Currency
# ---------------------------------------------------------------------------


def test_me_includes_household_currency(client, token_a, user_a, household_a):
    """/api/auth/me Response enthält currency im Household-Objekt."""
    resp = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["households"]) >= 1
    household = data["households"][0]
    assert "currency" in household
    assert household["currency"] == "CHF"


# ---------------------------------------------------------------------------
# 6. Update-Expense mit falscher Währung → 422 CURRENCY_MISMATCH
# ---------------------------------------------------------------------------


def test_update_expense_with_wrong_currency_rejected(client, household_a, token_a, user_a, user_a2, expense_a):
    """PATCH mit EUR auf CHF-Expense → 422 CURRENCY_MISMATCH."""
    resp = client.patch(
        f"/api/households/{household_a.id}/expenses/{expense_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"currency": "EUR"},
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["detail"]["code"] == "CURRENCY_MISMATCH"
