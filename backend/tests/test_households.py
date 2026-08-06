"""Tests für Household CRUD + Events."""
import uuid

import pytest


class TestCreateHousehold:
    def test_create_success(self, client, db, user_a, token_a):
        """POST /api/households/ → 201, Ersteller ist admin."""
        resp = client.post(
            "/api/households/",
            json={"name": "Neuer Haushalt"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Neuer Haushalt"
        assert data["role"] == "admin"
        assert data["currency"] == "CHF"
        assert "id" in data

    def test_create_name_too_long(self, client, user_a, token_a):
        """Name > 100 Zeichen → 422."""
        resp = client.post(
            "/api/households/",
            json={"name": "x" * 101},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 422

    def test_create_empty_name(self, client, user_a, token_a):
        """Leerer Name → 422."""
        resp = client.post(
            "/api/households/",
            json={"name": ""},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 422


class TestRenameHousehold:
    def test_rename_as_admin(self, client, db, household_a, user_a, token_a, _mock_socket_emit):
        """Admin kann Haushalt umbenennen."""
        resp = client.patch(
            f"/api/households/{household_a.id}",
            json={"name": "Neuer Name"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Neuer Name"
        # Socket-Event geprüft
        _mock_socket_emit.assert_called()

    def test_rename_as_non_admin(self, client, db, household_a, user_a, token_a):
        """Nicht-Admin kann nicht umbenennen → 403."""
        from app.models import HouseholdMember

        # user_a auf member herabstufen
        m = db.query(HouseholdMember).filter_by(
            household_id=household_a.id, user_id=user_a.id
        ).first()
        m.role = "member"
        db.commit()

        resp = client.patch(
            f"/api/households/{household_a.id}",
            json={"name": "Neuer Name"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "ADMIN_REQUIRED"

    def test_rename_not_found(self, client, db, user_a, token_a):
        """Umbenennen eines nicht-existierenden Haushalts → 403 (kein Mitglied)."""
        fake_id = uuid.uuid4()
        resp = client.patch(
            f"/api/households/{fake_id}",
            json={"name": "Nope"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 403


class TestJoinEvent:
    def test_join_emits_event(self, client, db, household_a, user_a, user_b, token_b, _mock_socket_emit):
        """POST /join emittiert household_member_joined."""
        resp = client.post(
            "/api/households/join",
            json={"invite_code": "ALPHA123"},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp.status_code == 200
        # Prüfe, dass emit aufgerufen wurde mit dem richtigen Event
        calls = [c for c in _mock_socket_emit.call_args_list if c[0][1] == "household_member_joined"]
        assert len(calls) >= 1


class TestListMembersRole:
    def test_members_include_role(self, client, db, household_a, user_a, token_a):
        """GET /members gibt role pro Mitglied zurück."""
        resp = client.get(
            f"/api/households/{household_a.id}/members",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert "role" in data[0]
        assert data[0]["role"] == "admin"
