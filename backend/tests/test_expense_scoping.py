# Konsistenz-Check (05.08.2026): Alle Scoping-Tests erwarten 403 (verify_household_access).
# Das ist korrekt und konsistent mit shopping/todos/expenses — kein 404-Pattern nötig.

"""Multi-Tenant Scoping Tests für Expenses."""
import uuid


def test_user_a_can_read_own_expenses(client, household_a, token_a, expense_a):
    resp = client.get(
        f"/api/households/{household_a.id}/expenses/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(e["id"] == str(expense_a.id) for e in data)


def test_user_a_cannot_read_other_household_expenses(client, household_b, token_a, expense_b):
    resp = client.get(
        f"/api/households/{household_b.id}/expenses/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_create_in_other_household(client, household_b, token_a, user_b):
    resp = client.post(
        f"/api/households/{household_b.id}/expenses/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "description": "Hack",
            "amount_rappen": 1000,
            "paid_by_user_id": str(user_b.id),
            "split_type": "even",
        },
    )
    assert resp.status_code == 403


def test_user_a_cannot_patch_other_household_expense(client, household_b, token_a, expense_b):
    resp = client.patch(
        f"/api/households/{household_b.id}/expenses/{expense_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"description": "Gehackt"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_delete_other_household_expense(client, household_b, token_a, expense_b):
    resp = client.delete(
        f"/api/households/{household_b.id}/expenses/{expense_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


def test_user_a_cannot_read_other_household_balances(client, household_b, token_a):
    """Balances von fremdem Household → 403."""
    resp = client.get(
        f"/api/households/{household_b.id}/expenses/balances",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403
