"""
Tests für Household-Beitritt per Invite-Code.
"""
import uuid

import pytest

from app.models import Household, HouseholdMember


# ---------------------------------------------------------------------------
# 1. Join mit gültigem Code → 200, HouseholdMember existiert danach
# ---------------------------------------------------------------------------
def test_join_with_valid_code(client, db, household_a, user_a, user_b, token_b):
    """User B tritt Household A bei → 200, Membership existiert."""
    resp = client.post(
        "/api/households/join",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"invite_code": household_a.invite_code},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(household_a.id)
    assert data["name"] == household_a.name

    # Membership in DB prüfen
    membership = (
        db.query(HouseholdMember)
        .filter_by(household_id=household_a.id, user_id=user_b.id)
        .first()
    )
    assert membership is not None
    assert membership.role == "member"


# ---------------------------------------------------------------------------
# 2. Join mit unbekanntem Code → 404
# ---------------------------------------------------------------------------
def test_join_with_unknown_code(client, token_a):
    """Unbekannter Invite-Code → 404."""
    resp = client.post(
        "/api/households/join",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"invite_code": "XXXXXXXX"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 3. Join wenn bereits Mitglied → 409, kein Duplikat
# ---------------------------------------------------------------------------
def test_join_already_member(client, db, household_a, user_a, token_a):
    """User A ist bereits Mitglied von Household A → 409."""
    resp = client.post(
        "/api/households/join",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"invite_code": household_a.invite_code},
    )
    assert resp.status_code == 409

    # Kein zweiter Eintrag
    count = (
        db.query(HouseholdMember)
        .filter_by(household_id=household_a.id, user_id=user_a.id)
        .count()
    )
    assert count == 1


# ---------------------------------------------------------------------------
# 4. Join ohne Token → 401
# ---------------------------------------------------------------------------
def test_join_without_token(client, household_a):
    """Ohne Auth-Token → 401."""
    resp = client.post(
        "/api/households/join",
        json={"invite_code": household_a.invite_code},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 5. Nach Join: User kann Shopping-Items des neuen Households lesen → 200
# ---------------------------------------------------------------------------
def test_after_join_can_read_new_household_shopping(
    client, db, household_a, user_b, token_b, shopping_item_a
):
    """Nach Beitritt kann User B die Shopping-Items von Household A lesen."""
    # Beitreten
    resp = client.post(
        "/api/households/join",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"invite_code": household_a.invite_code},
    )
    assert resp.status_code == 200

    # Shopping-Items lesen
    resp = client.get(
        f"/api/households/{household_a.id}/shopping-items/?include_checked=true",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(item["id"] == str(shopping_item_a.id) for item in data)


# ---------------------------------------------------------------------------
# 6. Nach Join: Drittes Household weiterhin gesperrt → 403
# ---------------------------------------------------------------------------
def test_after_join_still_no_access_to_third_household(
    client, db, household_a, user_a, user_b, token_b
):
    """Nach Beitritt zu A hat User B keinen Zugriff auf ein drittes Household."""
    # Drittes Household anlegen
    household_c = Household(
        id=uuid.uuid4(),
        name="Haushalt Gamma",
        invite_code="GAMMA789",
    )
    db.add(household_c)
    db.commit()

    # User B tritt Household A bei
    resp = client.post(
        "/api/households/join",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"invite_code": household_a.invite_code},
    )
    assert resp.status_code == 200

    # Zugriff auf Household C → 403
    resp = client.get(
        f"/api/households/{household_c.id}/shopping-items/",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 7. GET invite-code des eigenen Households → 200
# ---------------------------------------------------------------------------
def test_get_invite_code_own_household(client, household_a, token_a):
    """Eigener Invite-Code → 200."""
    resp = client.get(
        f"/api/households/{household_a.id}/invite-code",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["invite_code"] == household_a.invite_code


# ---------------------------------------------------------------------------
# 8. GET invite-code eines fremden Households → 403
# ---------------------------------------------------------------------------
def test_get_invite_code_other_household(client, household_b, token_a):
    """Fremder Invite-Code → 403."""
    resp = client.get(
        f"/api/households/{household_b.id}/invite-code",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 9. Unique-Constraint: Kein Duplikat möglich
# ---------------------------------------------------------------------------
def test_two_households_cannot_have_same_invite_code(db):
    """Zwei Households mit demselben invite_code → IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    h1 = Household(id=uuid.uuid4(), name="H1", invite_code="TESTCODE")
    db.add(h1)
    db.commit()

    h2 = Household(id=uuid.uuid4(), name="H2", invite_code="TESTCODE")
    db.add(h2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ---------------------------------------------------------------------------
# 10. Join mit Kleinbuchstaben + Whitespace → 200 (Normalisierung)
# ---------------------------------------------------------------------------
def test_join_with_lowercase_and_whitespace(client, db, household_a, user_a, user_b, token_b):
    """Join mit Kleinbuchstaben und Whitespace → 200 (Normalisierung)."""
    # household_a.invite_code ist "ALPHA123"
    messy_code = "  alpha123  "
    resp = client.post(
        "/api/households/join",
        headers={"Authorization": f"Bearer {token_b}"},
        json={"invite_code": messy_code},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(household_a.id)


# ---------------------------------------------------------------------------
# Ablauf von Einladungscodes (H-12)
# ---------------------------------------------------------------------------
from datetime import datetime, timedelta, timezone  # noqa: E402

from app.services.invite_code import INVITE_CODE_TTL  # noqa: E402


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_join_with_not_yet_expired_code(client, db, household_a, user_a, token_b):
    household_a.invite_code_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()
    resp = client.post(
        "/api/households/join", headers=_auth(token_b), json={"invite_code": household_a.invite_code}
    )
    assert resp.status_code == 200


def test_join_with_expired_code_is_rejected(client, db, household_a, user_a, user_b, token_b):
    household_a.invite_code_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    resp = client.post(
        "/api/households/join", headers=_auth(token_b), json={"invite_code": household_a.invite_code}
    )
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "INVITE_CODE_EXPIRED"
    assert (
        db.query(HouseholdMember).filter_by(household_id=household_a.id, user_id=user_b.id).first()
        is None
    )


def test_register_with_expired_code_is_rejected(client, db, household_a, user_a):
    household_a.invite_code_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    resp = client.post(
        "/api/auth/register",
        json={
            "email": "new@example.com",
            "password": "password123",
            "display_name": "Neu",
            "invite_code": household_a.invite_code,
        },
    )
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "INVITE_CODE_EXPIRED"


def test_create_household_sets_expiry(client, db, token_a):
    resp = client.post("/api/households/", headers=_auth(token_a), json={"name": "Neu"})
    assert resp.status_code == 201
    h = db.get(Household, uuid.UUID(resp.json()["id"]))
    exp = h.invite_code_expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    delta = exp - datetime.now(timezone.utc)
    assert INVITE_CODE_TTL - timedelta(minutes=1) < delta <= INVITE_CODE_TTL


def test_rotate_sets_new_expiry_and_revives_expired_code(client, db, household_a, token_a, user_a):
    household_a.invite_code_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    url = f"/api/households/{household_a.id}/invite-code"
    got = client.get(url, headers=_auth(token_a)).json()
    assert got["expired"] is True

    rotated = client.post(f"{url}/rotate", headers=_auth(token_a)).json()
    assert rotated["expired"] is False
    exp = datetime.fromisoformat(rotated["expires_at"])
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    assert exp > datetime.now(timezone.utc) + INVITE_CODE_TTL - timedelta(minutes=1)


def test_code_without_expiry_never_expires(client, household_a, token_a):
    got = client.get(f"/api/households/{household_a.id}/invite-code", headers=_auth(token_a)).json()
    assert got["expires_at"] is None
    assert got["expired"] is False
