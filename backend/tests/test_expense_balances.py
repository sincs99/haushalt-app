"""Tests für Saldo-Endpoint und Settlement-Algorithmus."""
import uuid
from datetime import date

import pytest

from app.routers.expenses import compute_settlements


# ---------------------------------------------------------------------------
# Unit-Tests: compute_settlements
# ---------------------------------------------------------------------------

class TestComputeSettlements:
    def test_empty_input(self):
        assert compute_settlements({}) == []

    def test_all_zero(self):
        ids = [uuid.uuid4() for _ in range(3)]
        result = compute_settlements({uid: 0 for uid in ids})
        assert result == []

    def test_two_users_simple(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        result = compute_settlements({a: 500, b: -500})
        assert len(result) == 1
        s = result[0]
        assert s["from_user_id"] == b
        assert s["to_user_id"] == a
        assert s["amount_rappen"] == 500

    def test_three_users(self):
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        # A bekommt 700, B schuldet 300, C schuldet 400
        result = compute_settlements({a: 700, b: -300, c: -400})
        assert len(result) <= 2
        # Invariante: nach Anwendung alle Salden 0
        net = {a: 700, b: -300, c: -400}
        for s in result:
            net[s["from_user_id"]] += s["amount_rappen"]
            net[s["to_user_id"]] -= s["amount_rappen"]
        assert all(v == 0 for v in net.values())

    def test_four_users_chain(self):
        a, b, c, d = (
            uuid.UUID(f"00000000-0000-0000-0000-{i:012d}") for i in range(4)
        )
        saldi = {a: 1000, b: 500, c: -800, d: -700}
        result = compute_settlements(saldi)
        assert len(result) <= 3
        # Invariante prüfen
        net = dict(saldi)
        for s in result:
            net[s["from_user_id"]] += s["amount_rappen"]
            net[s["to_user_id"]] -= s["amount_rappen"]
        assert all(v == 0 for v in net.values())
        # Kein Settlement mit Betrag 0
        assert all(s["amount_rappen"] > 0 for s in result)

    def test_deterministic(self):
        ids = [uuid.UUID(f"00000000-0000-0000-0000-{i:012d}") for i in range(3)]
        saldi = {ids[0]: 500, ids[1]: -200, ids[2]: -300}
        r1 = compute_settlements(saldi)
        r2 = compute_settlements(dict(reversed(list(saldi.items()))))
        assert r1 == r2

    def test_unbalanced_saldi(self):
        """SUM(saldi) != 0 → kein Fehler, gleicht aus was geht."""
        a, b = uuid.uuid4(), uuid.uuid4()
        # a hat +500 Guthaben, b schuldet -300, Rest 200 bleibt
        result = compute_settlements({a: 500, b: -300})
        assert len(result) == 1
        assert result[0]["amount_rappen"] == 300


# ---------------------------------------------------------------------------
# Integration-Tests: GET /balances Endpoint
# ---------------------------------------------------------------------------

class TestBalancesEndpoint:
    def test_balances_with_expenses(self, client, household_a, token_a, user_a, user_a2):
        """2 Expenses, Salden von Hand nachgerechnet."""
        # Expense 1: user_a zahlt 3000 (even split: 1500 + 1500)
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Pizza",
                "amount_rappen": 3000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "even",
            },
        )
        assert resp.status_code == 201

        # Expense 2: user_a2 zahlt 1000 (custom: user_a 600, user_a2 400)
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Getränke",
                "amount_rappen": 1000,
                "paid_by_user_id": str(user_a2.id),
                "split_type": "custom",
                "shares": [
                    {"user_id": str(user_a.id), "amount_rappen": 600},
                    {"user_id": str(user_a2.id), "amount_rappen": 400},
                ],
            },
        )
        assert resp.status_code == 201

        # Salden berechnen:
        # user_a: paid=3000, owed=1500+600=2100, saldo=+900
        # user_a2: paid=1000, owed=1500+400=1900, saldo=-900
        resp = client.get(
            f"/api/households/{household_a.id}/expenses/balances",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["unassigned_rappen"] == 0

        balances_by_id = {b["user_id"]: b for b in data["balances"]}
        ba = balances_by_id[str(user_a.id)]
        ba2 = balances_by_id[str(user_a2.id)]

        assert ba["paid_rappen"] == 3000
        assert ba["owed_rappen"] == 2100
        assert ba["settled_out_rappen"] == 0
        assert ba["settled_in_rappen"] == 0
        assert ba["saldo_rappen"] == 900

        assert ba2["paid_rappen"] == 1000
        assert ba2["owed_rappen"] == 1900
        assert ba2["settled_out_rappen"] == 0
        assert ba2["settled_in_rappen"] == 0
        assert ba2["saldo_rappen"] == -900

        # SUM(saldi) == 0
        total_saldo = sum(b["saldo_rappen"] for b in data["balances"])
        assert total_saldo == 0

        # Genau 1 Settlement
        assert len(data["settlements"]) == 1
        s = data["settlements"][0]
        assert s["from_user_id"] == str(user_a2.id)
        assert s["to_user_id"] == str(user_a.id)
        assert s["amount_rappen"] == 900

    def test_balances_empty_household(self, client, household_a, token_a, user_a, user_a2):
        """Keine Expenses → alle Salden 0, keine Settlements."""
        resp = client.get(
            f"/api/households/{household_a.id}/expenses/balances",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["unassigned_rappen"] == 0
        assert len(data["balances"]) == 2  # 2 Mitglieder
        assert all(b["saldo_rappen"] == 0 for b in data["balances"])
        assert all(b["settled_out_rappen"] == 0 for b in data["balances"])
        assert all(b["settled_in_rappen"] == 0 for b in data["balances"])
        assert data["settlements"] == []

    def test_balances_unassigned_payer(self, db, client, household_a, token_a, user_a, user_a2):
        """Expense mit paid_by_user_id=NULL → unassigned_rappen korrekt."""
        from app.models import Expense, ExpenseShare

        # Direkt in DB anlegen: Expense ohne Payer
        expense = Expense(
            id=uuid.uuid4(),
            household_id=household_a.id,
            description="Alte Ausgabe",
            amount_rappen=2000,
            paid_by_user_id=None,
            expense_date=date.today(),
        )
        db.add(expense)
        db.flush()
        for uid, amt in [(user_a.id, 1000), (user_a2.id, 1000)]:
            db.add(ExpenseShare(
                id=uuid.uuid4(),
                expense_id=expense.id,
                household_id=household_a.id,
                user_id=uid,
                amount_rappen=amt,
            ))
        db.commit()

        resp = client.get(
            f"/api/households/{household_a.id}/expenses/balances",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["unassigned_rappen"] == 2000

        # Shares zählen weiter als owed
        balances_by_id = {b["user_id"]: b for b in data["balances"]}
        assert balances_by_id[str(user_a.id)]["owed_rappen"] == 1000
        assert balances_by_id[str(user_a2.id)]["owed_rappen"] == 1000
        # paid = 0 für beide → saldo = -1000 jeweils
        assert balances_by_id[str(user_a.id)]["saldo_rappen"] == -1000


class TestBalancesScoping:
    def test_balances_cross_household_403(self, client, household_b, token_a):
        """User aus Household A bekommt für Household B ein 403."""
        resp = client.get(
            f"/api/households/{household_b.id}/expenses/balances",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403
