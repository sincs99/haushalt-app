"""Tests für Haushalt verlassen und Mitglied entfernen."""
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest
from app.models import Household, HouseholdMember, User, Expense, ExpenseShare
from app.core.security import create_access_token, hash_password
from app.core.error_codes import ErrorCode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def shared_household(db):
    """Haushalt mit Admin + 2 Members für Leave/Remove-Tests."""
    h = Household(id=uuid.uuid4(), name="Shared", invite_code="SHARED01", currency="CHF")
    db.add(h)
    db.flush()

    admin = User(id=uuid.uuid4(), email="admin@test.com", password_hash=hash_password("pw123456"), display_name="Admin")
    member1 = User(id=uuid.uuid4(), email="m1@test.com", password_hash=hash_password("pw123456"), display_name="Member1")
    member2 = User(id=uuid.uuid4(), email="m2@test.com", password_hash=hash_password("pw123456"), display_name="Member2")
    db.add_all([admin, member1, member2])
    db.flush()

    # Admin zuerst, dann member1, dann member2 (mit Zeitabstand für joined_at)
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    m_admin = HouseholdMember(household_id=h.id, user_id=admin.id, role="admin", joined_at=t0)
    m_m1 = HouseholdMember(household_id=h.id, user_id=member1.id, role="member", joined_at=t0 + timedelta(hours=1))
    m_m2 = HouseholdMember(household_id=h.id, user_id=member2.id, role="member", joined_at=t0 + timedelta(hours=2))
    db.add_all([m_admin, m_m1, m_m2])
    db.commit()

    return {
        "household": h,
        "admin": admin,
        "member1": member1,
        "member2": member2,
        "m_admin": m_admin,
        "m_m1": m_m1,
        "m_m2": m_m2,
    }


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _leave_url(household_id: uuid.UUID) -> str:
    return f"/api/households/{household_id}/leave"


def _remove_url(household_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"/api/households/{household_id}/members/{user_id}"


# ---------------------------------------------------------------------------
# 1. test_leave_normal — Member verlässt → 204, danach 403
# ---------------------------------------------------------------------------


def test_leave_normal(client, db, shared_household):
    """Member verlässt normal → 204, danach 403 auf Members-Endpoint."""
    sh = shared_household
    token = create_access_token(str(sh["member1"].id))

    resp = client.post(_leave_url(sh["household"].id), headers=_auth(token))
    assert resp.status_code == 204

    # Danach kein Zugriff mehr
    resp2 = client.get(
        f"/api/households/{sh['household'].id}/members",
        headers=_auth(token),
    )
    assert resp2.status_code == 403


# ---------------------------------------------------------------------------
# 2. test_leave_admin_auto_promote — Admin verlässt → ältestes Member wird Admin
# ---------------------------------------------------------------------------


def test_leave_admin_auto_promote(client, db, shared_household):
    """Admin verlässt → member1 (frühestes joined_at) wird Admin, NICHT member2."""
    sh = shared_household
    token_admin = create_access_token(str(sh["admin"].id))

    resp = client.post(_leave_url(sh["household"].id), headers=_auth(token_admin))
    assert resp.status_code == 204

    # member1 sollte jetzt Admin sein
    db.expire_all()
    m1_membership = db.query(HouseholdMember).filter_by(
        household_id=sh["household"].id, user_id=sh["member1"].id
    ).first()
    assert m1_membership is not None
    assert m1_membership.role == "admin"

    # member2 bleibt member
    m2_membership = db.query(HouseholdMember).filter_by(
        household_id=sh["household"].id, user_id=sh["member2"].id
    ).first()
    assert m2_membership is not None
    assert m2_membership.role == "member"


# ---------------------------------------------------------------------------
# 3. test_leave_last_member_deletes_household — Letztes Mitglied → Haushalt gelöscht
# ---------------------------------------------------------------------------


def test_leave_last_member_deletes_household(client, db):
    """Einziges Mitglied verlässt → Haushalt + CASCADE-Daten weg."""
    h = Household(id=uuid.uuid4(), name="Solo", invite_code="SOLO0001", currency="CHF")
    db.add(h)
    db.flush()

    user = User(id=uuid.uuid4(), email="solo@test.com", password_hash=hash_password("pw123456"), display_name="Solo")
    db.add(user)
    db.flush()

    m = HouseholdMember(household_id=h.id, user_id=user.id, role="admin")
    db.add(m)
    db.flush()

    # Expense + Share erstellen, um CASCADE zu testen
    expense = Expense(
        id=uuid.uuid4(),
        household_id=h.id,
        description="Test-Expense",
        amount_rappen=1000,
        paid_by_user_id=user.id,
        split_type="even",
    )
    db.add(expense)
    db.flush()

    share = ExpenseShare(
        id=uuid.uuid4(),
        expense_id=expense.id,
        household_id=h.id,
        user_id=user.id,
        amount_rappen=1000,
    )
    db.add(share)
    db.commit()

    hid = h.id
    eid = expense.id
    token = create_access_token(str(user.id))

    resp = client.post(_leave_url(hid), headers=_auth(token))
    assert resp.status_code == 204

    # Haushalt muss weg sein
    db.expire_all()
    assert db.get(Household, hid) is None
    assert db.get(Expense, eid) is None


# ---------------------------------------------------------------------------
# 4. test_leave_emits_event — Event household_member_left wird emittiert
# ---------------------------------------------------------------------------


def test_leave_emits_event(client, db, shared_household, _mock_socket_emit):
    """Event household_member_left wird nach Verlassen emittiert."""
    sh = shared_household
    token = create_access_token(str(sh["member2"].id))

    client.post(_leave_url(sh["household"].id), headers=_auth(token))

    _mock_socket_emit.assert_called_with(
        sh["household"].id,
        "household_member_left",
        {"household_id": str(sh["household"].id), "user_id": str(sh["member2"].id)},
    )


# ---------------------------------------------------------------------------
# 5. test_remove_member_as_admin — Admin entfernt Member → 204
# ---------------------------------------------------------------------------


def test_remove_member_as_admin(client, db, shared_household):
    """Admin entfernt Member → 204."""
    sh = shared_household
    token_admin = create_access_token(str(sh["admin"].id))

    resp = client.delete(
        _remove_url(sh["household"].id, sh["member1"].id),
        headers=_auth(token_admin),
    )
    assert resp.status_code == 204

    # member1 ist nicht mehr Mitglied
    db.expire_all()
    m = db.query(HouseholdMember).filter_by(
        household_id=sh["household"].id, user_id=sh["member1"].id
    ).first()
    assert m is None


# ---------------------------------------------------------------------------
# 6. test_remove_admin_as_admin_rejected — Admin versucht anderen Admin zu entfernen → 403
# ---------------------------------------------------------------------------


def test_remove_admin_as_admin_rejected(client, db, shared_household):
    """Admin versucht anderen Admin zu entfernen → 403 CANNOT_REMOVE_ADMIN."""
    sh = shared_household

    # member1 zum Admin machen
    m1_membership = db.query(HouseholdMember).filter_by(
        household_id=sh["household"].id, user_id=sh["member1"].id
    ).first()
    m1_membership.role = "admin"
    db.commit()

    token_admin = create_access_token(str(sh["admin"].id))

    resp = client.delete(
        _remove_url(sh["household"].id, sh["member1"].id),
        headers=_auth(token_admin),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == ErrorCode.CANNOT_REMOVE_ADMIN


# ---------------------------------------------------------------------------
# 7. test_remove_as_non_admin_rejected — Member versucht zu entfernen → 403
# ---------------------------------------------------------------------------


def test_remove_as_non_admin_rejected(client, db, shared_household):
    """Member versucht jemanden zu entfernen → 403 ADMIN_REQUIRED."""
    sh = shared_household
    token_member = create_access_token(str(sh["member1"].id))

    resp = client.delete(
        _remove_url(sh["household"].id, sh["member2"].id),
        headers=_auth(token_member),
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == ErrorCode.ADMIN_REQUIRED


# ---------------------------------------------------------------------------
# 8. test_remove_self_rejected — Admin versucht sich selbst zu entfernen → 422
# ---------------------------------------------------------------------------


def test_remove_self_rejected(client, db, shared_household):
    """Admin versucht sich selbst über DELETE zu entfernen → 422 CANNOT_REMOVE_SELF."""
    sh = shared_household
    token_admin = create_access_token(str(sh["admin"].id))

    resp = client.delete(
        _remove_url(sh["household"].id, sh["admin"].id),
        headers=_auth(token_admin),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == ErrorCode.CANNOT_REMOVE_SELF


# ---------------------------------------------------------------------------
# 9. test_removed_member_loses_access — Entfernter bekommt 403
# ---------------------------------------------------------------------------


def test_removed_member_loses_access(client, db, shared_household):
    """Entferntes Mitglied bekommt auf alle Endpoints 403."""
    sh = shared_household
    token_admin = create_access_token(str(sh["admin"].id))
    token_member = create_access_token(str(sh["member1"].id))

    # Admin entfernt member1
    resp = client.delete(
        _remove_url(sh["household"].id, sh["member1"].id),
        headers=_auth(token_admin),
    )
    assert resp.status_code == 204

    # member1 kann keine Members mehr abrufen
    resp2 = client.get(
        f"/api/households/{sh['household'].id}/members",
        headers=_auth(token_member),
    )
    assert resp2.status_code == 403

    # member1 kann keine Expenses mehr abrufen
    resp3 = client.get(
        f"/api/households/{sh['household'].id}/expenses/",
        headers=_auth(token_member),
    )
    assert resp3.status_code == 403


# ---------------------------------------------------------------------------
# 10. test_balances_show_ex_member — Balances zeigen Ex-Mitglied korrekt
# ---------------------------------------------------------------------------


def test_balances_show_ex_member(client, db, shared_household):
    """Expense eines Ex-Mitglieds bleibt in den Balances sichtbar."""
    sh = shared_household

    # Expense: member1 bezahlt 2000 Rappen, geteilt auf member1 + admin
    expense = Expense(
        id=uuid.uuid4(),
        household_id=sh["household"].id,
        description="Pizza",
        amount_rappen=2000,
        paid_by_user_id=sh["member1"].id,
        split_type="even",
    )
    db.add(expense)
    db.flush()

    share1 = ExpenseShare(
        id=uuid.uuid4(),
        expense_id=expense.id,
        household_id=sh["household"].id,
        user_id=sh["member1"].id,
        amount_rappen=1000,
    )
    share2 = ExpenseShare(
        id=uuid.uuid4(),
        expense_id=expense.id,
        household_id=sh["household"].id,
        user_id=sh["admin"].id,
        amount_rappen=1000,
    )
    db.add_all([share1, share2])
    db.commit()

    # Admin entfernt member1
    token_admin = create_access_token(str(sh["admin"].id))
    resp = client.delete(
        _remove_url(sh["household"].id, sh["member1"].id),
        headers=_auth(token_admin),
    )
    assert resp.status_code == 204

    # Balances als Admin abrufen → member1 sollte weiterhin drin sein
    resp2 = client.get(
        f"/api/households/{sh['household'].id}/expenses/balances",
        headers=_auth(token_admin),
    )
    assert resp2.status_code == 200
    data = resp2.json()

    # member1 muss in den Balances auftauchen (paid + owed)
    user_ids_in_balances = [b["user_id"] for b in data["balances"]]
    assert str(sh["member1"].id) in user_ids_in_balances

    # member1 hat 2000 bezahlt, 1000 Anteil → Saldo +1000
    member1_balance = next(b for b in data["balances"] if b["user_id"] == str(sh["member1"].id))
    assert member1_balance["paid_rappen"] == 2000
    assert member1_balance["owed_rappen"] == 1000
    assert member1_balance["saldo_rappen"] == 1000
