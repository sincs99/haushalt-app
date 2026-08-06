"""Tests für Register mit invite_code / household_name."""
import pytest
from app.models import Household, HouseholdMember, User
from app.core.security import hash_password
from app.core.error_codes import ErrorCode


class TestRegisterWithHouseholdName:
    def test_register_creates_household(self, client, db):
        """Standard-Registrierung mit household_name."""
        resp = client.post("/api/auth/register", json={
            "email": "new@test.com",
            "password": "password123",
            "display_name": "Newbie",
            "household_name": "Mein Haushalt",
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

        # User ist Admin des neuen Haushalts
        user = db.query(User).filter_by(email="new@test.com").first()
        assert user is not None
        m = db.query(HouseholdMember).filter_by(user_id=user.id).first()
        assert m is not None
        assert m.role == "admin"


class TestRegisterWithInviteCode:
    def test_register_with_valid_code(self, client, db, household_a):
        """Registrierung mit gültigem Invite-Code → Member in bestehendem Haushalt."""
        resp = client.post("/api/auth/register", json={
            "email": "invited@test.com",
            "password": "password123",
            "display_name": "Invited",
            "invite_code": household_a.invite_code,
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

        user = db.query(User).filter_by(email="invited@test.com").first()
        assert user is not None
        m = db.query(HouseholdMember).filter_by(
            user_id=user.id, household_id=household_a.id
        ).first()
        assert m is not None
        assert m.role == "member"

    def test_register_with_invalid_code(self, client, db):
        """Registrierung mit ungültigem Invite-Code → 404."""
        resp = client.post("/api/auth/register", json={
            "email": "bad@test.com",
            "password": "password123",
            "display_name": "Bad",
            "invite_code": "INVALID9",
        })
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == ErrorCode.INVITE_CODE_NOT_FOUND


class TestRegisterValidation:
    def test_both_fields_set(self, client, db):
        """household_name UND invite_code gesetzt → 422."""
        resp = client.post("/api/auth/register", json={
            "email": "both@test.com",
            "password": "password123",
            "display_name": "Both",
            "household_name": "Test",
            "invite_code": "ABCD1234",
        })
        assert resp.status_code == 422

    def test_neither_field_set(self, client, db):
        """Weder household_name noch invite_code → 422."""
        resp = client.post("/api/auth/register", json={
            "email": "neither@test.com",
            "password": "password123",
            "display_name": "Neither",
        })
        assert resp.status_code == 422

    def test_empty_strings_count_as_unset(self, client, db):
        """Leere Strings → 422 (wie nicht gesetzt)."""
        resp = client.post("/api/auth/register", json={
            "email": "empty@test.com",
            "password": "password123",
            "display_name": "Empty",
            "household_name": "",
            "invite_code": "",
        })
        assert resp.status_code == 422
