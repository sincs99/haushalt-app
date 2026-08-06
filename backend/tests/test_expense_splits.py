"""Tests für Expense Split-Logik und API-Integration."""
import uuid

import pytest

# Import der Service-Funktionen für Unit-Tests
from app.routers.expenses import split_evenly


# ---------------------------------------------------------------------------
# Unit-Tests: split_evenly
# ---------------------------------------------------------------------------


class TestSplitEvenly:
    def test_even_split_no_remainder(self):
        ids = [uuid.uuid4() for _ in range(4)]
        result = split_evenly(1000, ids)
        assert sum(result.values()) == 1000
        assert all(v == 250 for v in result.values())

    def test_even_split_with_remainder(self):
        ids = [uuid.uuid4() for _ in range(3)]
        result = split_evenly(1000, ids)
        assert sum(result.values()) == 1000
        values = sorted(result.values(), reverse=True)
        assert values == [334, 333, 333]

    def test_one_rappen_two_people(self):
        ids = [uuid.uuid4() for _ in range(2)]
        result = split_evenly(1, ids)
        assert sum(result.values()) == 1
        values = sorted(result.values(), reverse=True)
        assert values == [1, 0]

    def test_deterministic_order(self):
        """Gleiche IDs ergeben gleiche Verteilung."""
        ids = [uuid.UUID(f"00000000-0000-0000-0000-{i:012d}") for i in range(3)]
        r1 = split_evenly(1000, ids)
        r2 = split_evenly(1000, list(reversed(ids)))
        assert r1 == r2


# ---------------------------------------------------------------------------
# API-Integrationstests: POST mit split_type
# ---------------------------------------------------------------------------


class TestCreateExpenseEvenSplit:
    def test_even_split_all_members(self, client, household_a, token_a, user_a, user_a2):
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Abendessen",
                "amount_rappen": 5000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "even",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["amount_rappen"] == 5000
        assert len(data["shares"]) == 2
        assert sum(s["amount_rappen"] for s in data["shares"]) == 5000

    def test_even_split_specific_participants(
        self, client, household_a, token_a, user_a, user_a2
    ):
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Taxi nur für mich",
                "amount_rappen": 2000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "even",
                "participant_ids": [str(user_a.id)],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert len(data["shares"]) == 1
        assert data["shares"][0]["amount_rappen"] == 2000


class TestCreateExpenseCustomSplit:
    def test_custom_split_valid(self, client, household_a, token_a, user_a, user_a2):
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Ungleich aufgeteilt",
                "amount_rappen": 3000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "custom",
                "shares": [
                    {"user_id": str(user_a.id), "amount_rappen": 1000},
                    {"user_id": str(user_a2.id), "amount_rappen": 2000},
                ],
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert sum(s["amount_rappen"] for s in data["shares"]) == 3000

    def test_custom_split_wrong_sum_422(self, client, household_a, token_a, user_a, user_a2):
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Falsche Summe",
                "amount_rappen": 3000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "custom",
                "shares": [
                    {"user_id": str(user_a.id), "amount_rappen": 1000},
                    {"user_id": str(user_a2.id), "amount_rappen": 1000},
                ],
            },
        )
        assert resp.status_code == 422

    def test_custom_split_duplicate_user_422(self, client, household_a, token_a, user_a):
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Doppelt",
                "amount_rappen": 2000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "custom",
                "shares": [
                    {"user_id": str(user_a.id), "amount_rappen": 1000},
                    {"user_id": str(user_a.id), "amount_rappen": 1000},
                ],
            },
        )
        assert resp.status_code == 422


class TestCreateExpenseValidation:
    def test_paid_by_non_member_422(self, client, household_a, token_a, user_b):
        """paid_by_user_id zeigt auf User aus anderem Household → 422."""
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Fremder Zahler",
                "amount_rappen": 1000,
                "paid_by_user_id": str(user_b.id),
                "split_type": "even",
            },
        )
        assert resp.status_code == 422

    def test_participant_non_member_422(self, client, household_a, token_a, user_a, user_b):
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Fremder Teilnehmer",
                "amount_rappen": 1000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "even",
                "participant_ids": [str(user_a.id), str(user_b.id)],
            },
        )
        assert resp.status_code == 422

    def test_shares_with_even_split_rejected(
        self, client, household_a, token_a, user_a, user_a2
    ):
        """shares sind bei split_type='even' verboten → 422."""
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Falsch",
                "amount_rappen": 1000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "even",
                "shares": [{"user_id": str(user_a.id), "amount_rappen": 1000}],
            },
        )
        assert resp.status_code == 422


class TestPatchExpense:
    def test_patch_description(self, client, household_a, token_a, expense_a):
        resp = client.patch(
            f"/api/households/{household_a.id}/expenses/{expense_a.id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"description": "Pizza geändert"},
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Pizza geändert"

    def test_patch_reshare_even(
        self, client, household_a, token_a, user_a, user_a2, expense_a
    ):
        """PATCH mit neuem amount + split_type: Shares neu berechnet."""
        resp = client.patch(
            f"/api/households/{household_a.id}/expenses/{expense_a.id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "amount_rappen": 5000,
                "split_type": "even",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount_rappen"] == 5000
        assert sum(s["amount_rappen"] for s in data["shares"]) == 5000


    def test_patch_amount_with_stored_even_reshares(
        self, client, household_a, token_a, user_a, user_a2, expense_a
    ):
        """PATCH nur amount_rappen bei gespeichertem even → Shares werden neu berechnet."""
        resp = client.patch(
            f"/api/households/{household_a.id}/expenses/{expense_a.id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"amount_rappen": 5000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount_rappen"] == 5000
        assert data["split_type"] == "even"
        assert sum(s["amount_rappen"] for s in data["shares"]) == 5000

    def test_patch_amount_with_stored_custom_requires_shares(
        self, client, household_a, token_a, user_a, user_a2
    ):
        """PATCH nur amount_rappen bei gespeichertem custom → 422."""
        # Zuerst custom-Expense anlegen
        create_resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Custom",
                "amount_rappen": 3000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "custom",
                "shares": [
                    {"user_id": str(user_a.id), "amount_rappen": 1000},
                    {"user_id": str(user_a2.id), "amount_rappen": 2000},
                ],
            },
        )
        assert create_resp.status_code == 201
        expense_id = create_resp.json()["id"]

        # PATCH nur amount → 422
        resp = client.patch(
            f"/api/households/{household_a.id}/expenses/{expense_id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"amount_rappen": 5000},
        )
        assert resp.status_code == 422

    def test_patch_shares_without_split_type_uses_stored_custom(
        self, client, household_a, token_a, user_a, user_a2
    ):
        """PATCH shares ohne split_type bei gespeichertem custom → Reshare wird durchgeführt."""
        # Zuerst custom-Expense anlegen
        create_resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Custom Reshare",
                "amount_rappen": 3000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "custom",
                "shares": [
                    {"user_id": str(user_a.id), "amount_rappen": 1000},
                    {"user_id": str(user_a2.id), "amount_rappen": 2000},
                ],
            },
        )
        assert create_resp.status_code == 201
        expense_id = create_resp.json()["id"]

        # PATCH shares ohne split_type → nutzt gespeicherten custom
        resp = client.patch(
            f"/api/households/{household_a.id}/expenses/{expense_id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "shares": [
                    {"user_id": str(user_a.id), "amount_rappen": 2000},
                    {"user_id": str(user_a2.id), "amount_rappen": 1000},
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        shares = {s["user_id"]: s["amount_rappen"] for s in data["shares"]}
        assert shares[str(user_a.id)] == 2000
        assert shares[str(user_a2.id)] == 1000

    def test_patch_shares_with_effective_even_rejected(
        self, client, household_a, token_a, user_a, user_a2, expense_a
    ):
        """PATCH shares bei effektivem even → 422."""
        resp = client.patch(
            f"/api/households/{household_a.id}/expenses/{expense_a.id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "shares": [
                    {"user_id": str(user_a.id), "amount_rappen": 2000},
                    {"user_id": str(user_a2.id), "amount_rappen": 1000},
                ],
            },
        )
        assert resp.status_code == 422

    def test_create_expense_stores_split_type(
        self, client, household_a, token_a, user_a
    ):
        """split_type wird bei create gespeichert und in Response zurückgegeben."""
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Test Split Type",
                "amount_rappen": 1000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "even",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["split_type"] == "even"


class TestDeleteExpense:
    def test_delete_expense(self, client, household_a, token_a, expense_a):
        resp = client.delete(
            f"/api/households/{household_a.id}/expenses/{expense_a.id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 204

    def test_delete_nonexistent_404(self, client, household_a, token_a):
        fake_id = uuid.uuid4()
        resp = client.delete(
            f"/api/households/{household_a.id}/expenses/{fake_id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 404


class TestListExpensesPagination:
    def test_limit_exceeds_max_422(self, client, household_a, token_a, user_a):
        """limit=10000 → 422 Validation Error."""
        resp = client.get(
            f"/api/households/{household_a.id}/expenses/?limit=10000",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 422
