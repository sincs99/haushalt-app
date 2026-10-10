"""Tests für Register mit invite_code / household_name."""
from unittest.mock import patch

from app.core.error_codes import ErrorCode
from app.models import Calendar, Household, HouseholdMember, User


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

    def test_register_household_matches_households_endpoint(self, client, db):
        """Register und POST /households/ nutzen denselben Helfer: Default-Kalender + Code-Ablauf."""
        resp = client.post("/api/auth/register", json={
            "email": "cal@test.com",
            "password": "password123",
            "display_name": "Cal",
            "household_name": "  Kalender-Haushalt  ",
        })
        assert resp.status_code == 200
        user = db.query(User).filter_by(email="cal@test.com").first()
        m = db.query(HouseholdMember).filter_by(user_id=user.id).first()
        household = db.get(Household, m.household_id)
        assert household.name == "Kalender-Haushalt"
        assert household.invite_code_expires_at is not None
        calendars = db.query(Calendar).filter_by(household_id=household.id).all()
        assert [c.name for c in calendars] == ["Allgemein"]


class TestRegisterWithInviteCode:
    def test_register_with_valid_code(self, client, db, household_a, user_a):
        """Registrierung mit gültigem Invite-Code → Member in bestehendem Haushalt."""
        with patch("app.routers.auth.emit_to_household_sync") as emit:
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

        # Andere Mitglieder erfahren davon wie bei POST /households/join (CASA-46)
        emit.assert_called_once_with(
            household_a.id,
            "household_member_joined",
            {
                "household_id": str(household_a.id),
                "user_id": str(user.id),
                "display_name": "Invited",
                "role": "member",
            },
        )

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
