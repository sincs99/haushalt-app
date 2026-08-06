"""Tests für Socket.IO-Events bei Expense-Operationen."""
import uuid


class TestExpenseSocketEvents:
    def test_create_emits_expense_created(
        self, client, household_a, token_a, user_a, user_a2, _mock_socket_emit
    ):
        """POST erzeugt genau ein expense_created Event."""
        _mock_socket_emit.reset_mock()
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Testausgabe",
                "amount_rappen": 2000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "even",
            },
        )
        assert resp.status_code == 201

        # Genau ein Event
        calls = _mock_socket_emit.call_args_list
        expense_calls = [c for c in calls if c[0][1] == "expense_created"]
        assert len(expense_calls) == 1

        call_args = expense_calls[0][0]
        assert call_args[0] == household_a.id  # household_id
        assert call_args[1] == "expense_created"  # event name
        payload = call_args[2]
        assert payload["amount_rappen"] == 2000
        assert "shares" in payload
        assert len(payload["shares"]) == 2

    def test_patch_emits_expense_updated(
        self, client, household_a, token_a, expense_a, _mock_socket_emit
    ):
        """PATCH erzeugt expense_updated mit aktualisierten Daten."""
        _mock_socket_emit.reset_mock()
        resp = client.patch(
            f"/api/households/{household_a.id}/expenses/{expense_a.id}",
            headers={"Authorization": f"Bearer {token_a}"},
            json={"description": "Geändert"},
        )
        assert resp.status_code == 200

        calls = _mock_socket_emit.call_args_list
        update_calls = [c for c in calls if c[0][1] == "expense_updated"]
        assert len(update_calls) == 1
        payload = update_calls[0][0][2]
        assert payload["description"] == "Geändert"
        assert "shares" in payload

    def test_delete_emits_expense_deleted(
        self, client, household_a, token_a, expense_a, _mock_socket_emit
    ):
        """DELETE erzeugt expense_deleted mit korrekter id."""
        _mock_socket_emit.reset_mock()
        expense_id = str(expense_a.id)
        resp = client.delete(
            f"/api/households/{household_a.id}/expenses/{expense_a.id}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 204

        calls = _mock_socket_emit.call_args_list
        delete_calls = [c for c in calls if c[0][1] == "expense_deleted"]
        assert len(delete_calls) == 1
        payload = delete_calls[0][0][2]
        assert payload["id"] == expense_id
        assert payload["household_id"] == str(household_a.id)

    def test_failed_create_no_event(
        self, client, household_a, token_a, user_a, user_a2, _mock_socket_emit
    ):
        """422 bei fehlgeschlagenem POST → kein Event."""
        _mock_socket_emit.reset_mock()
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Falsch",
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
        # Kein expense_* Event
        expense_calls = [
            c for c in _mock_socket_emit.call_args_list
            if c[0][1].startswith("expense_")
        ]
        assert len(expense_calls) == 0

    def test_event_targets_correct_room(
        self, client, household_a, token_a, user_a, user_a2, _mock_socket_emit
    ):
        """Event geht an den richtigen Household-Room."""
        _mock_socket_emit.reset_mock()
        resp = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers={"Authorization": f"Bearer {token_a}"},
            json={
                "description": "Room-Test",
                "amount_rappen": 1000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "even",
            },
        )
        assert resp.status_code == 201

        calls = _mock_socket_emit.call_args_list
        for call in calls:
            if call[0][1].startswith("expense_"):
                # Erstes Argument ist household_id — muss household_a sein
                assert call[0][0] == household_a.id
