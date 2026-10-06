"""
Tests für Datenkorrektheit im Finanzbereich.

Stellt sicher, dass:
- doppelte Teilnehmer abgelehnt werden (Anteile ergeben immer den Gesamtbetrag)
- Schulden von Ex-Mitgliedern beglichen werden können
- alte Ausgaben mit Ex-Mitgliedern bearbeitbar bleiben
- nur neu hinzukommende Personen aktuelle Mitglieder sein müssen
- eine reine Betragsänderung auf die bisherigen Teilnehmer verteilt
"""

import uuid

import pytest

from app.core.security import hash_password
from app.models import HouseholdMember, User


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _expenses(household):
    return f"/api/households/{household.id}/expenses/"


def _settlements(household):
    return f"/api/households/{household.id}/settlements/"


def _make_user(db, email, household=None) -> User:
    user = User(id=uuid.uuid4(), email=email, password_hash=hash_password("password123"), display_name=email)
    db.add(user)
    db.flush()
    if household is not None:
        db.add(HouseholdMember(id=uuid.uuid4(), household_id=household.id, user_id=user.id, role="member"))
    db.commit()
    return user


def _remove_member(db, household, user):
    db.query(HouseholdMember).filter_by(household_id=household.id, user_id=user.id).delete()
    db.commit()


def _create_expense(client, household, token, payer, participants, amount=1000):
    resp = client.post(_expenses(household), headers=_auth(token), json={
        "description": "Einkauf", "amount_rappen": amount, "paid_by_user_id": str(payer.id),
        "split_type": "even", "participant_ids": [str(p.id) for p in participants],
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


def _shares(expense):
    return {s["user_id"]: s["amount_rappen"] for s in expense["shares"]}


# ---------------------------------------------------------------------------
# Doppelte Teilnehmer
# ---------------------------------------------------------------------------


def test_duplicate_participants_rejected_on_create(client, household_a, token_a, user_a, user_a2):
    resp = client.post(_expenses(household_a), headers=_auth(token_a), json={
        "description": "Doppelt", "amount_rappen": 1000, "paid_by_user_id": str(user_a.id),
        "split_type": "even", "participant_ids": [str(user_a2.id), str(user_a2.id)],
    })
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "DUPLICATE_SHARE_USER"


def test_duplicate_participants_rejected_on_update(client, household_a, token_a, user_a, user_a2):
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2])
    resp = client.patch(f"{_expenses(household_a)}{exp['id']}", headers=_auth(token_a), json={
        "participant_ids": [str(user_a.id), str(user_a.id)],
    })
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "DUPLICATE_SHARE_USER"


def test_shares_always_sum_to_amount(client, household_a, token_a, user_a, user_a2):
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2], amount=1001)
    assert sum(_shares(exp).values()) == 1001


# ---------------------------------------------------------------------------
# Ex-Mitglieder: Ausgleich
# ---------------------------------------------------------------------------


@pytest.fixture()
def ex_member_debt(client, db, household_a, token_a, user_a, user_a2):
    """user_a zahlt 1000 für sich und user_a2; danach verlässt user_a2 den Haushalt."""
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2])
    _remove_member(db, household_a, user_a2)
    return exp


def test_ex_member_debt_shows_in_suggestions_and_can_be_settled(
    client, household_a, token_a, user_a, user_a2, ex_member_debt
):
    balances = client.get(f"{_expenses(household_a)}balances", headers=_auth(token_a)).json()
    suggestion = balances["settlements"][0]
    assert suggestion == {"from_user_id": str(user_a2.id), "to_user_id": str(user_a.id), "amount_rappen": 500}

    resp = client.post(_settlements(household_a), headers=_auth(token_a), json=suggestion)
    assert resp.status_code == 201, resp.text

    balances = client.get(f"{_expenses(household_a)}balances", headers=_auth(token_a)).json()
    assert balances["settlements"] == []
    assert all(b["saldo_rappen"] == 0 for b in balances["balances"])


def test_settlement_with_stranger_rejected(client, db, household_a, token_a, user_a, ex_member_debt):
    stranger = _make_user(db, "stranger@example.com")
    resp = client.post(_settlements(household_a), headers=_auth(token_a), json={
        "from_user_id": str(stranger.id), "to_user_id": str(user_a.id), "amount_rappen": 100,
    })
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "USERS_NOT_IN_HOUSEHOLD"


def test_settlement_between_two_ex_members_rejected(
    client, db, household_a, token_a, user_a, user_a2, ex_member_debt
):
    other = _make_user(db, "other@example.com", household_a)
    _create_expense(client, household_a, token_a, other, [user_a, other])
    _remove_member(db, household_a, other)
    resp = client.post(_settlements(household_a), headers=_auth(token_a), json={
        "from_user_id": str(user_a2.id), "to_user_id": str(other.id), "amount_rappen": 100,
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Ex-Mitglieder: alte Ausgaben bearbeiten
# ---------------------------------------------------------------------------


def test_old_expense_with_ex_member_editable_with_full_payload(
    client, household_a, token_a, user_a, user_a2, ex_member_debt
):
    """Das UI sendet beim Speichern immer Betrag, Zahler und Teilnehmer mit."""
    resp = client.patch(f"{_expenses(household_a)}{ex_member_debt['id']}", headers=_auth(token_a), json={
        "description": "Einkauf Migros", "amount_rappen": 1000, "paid_by_user_id": str(user_a.id),
        "split_type": "even", "participant_ids": [str(user_a.id), str(user_a2.id)],
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "Einkauf Migros"
    assert _shares(resp.json()) == {str(user_a.id): 500, str(user_a2.id): 500}


def test_ex_member_as_payer_stays_editable(client, db, household_a, token_a, user_a, user_a2):
    exp = _create_expense(client, household_a, token_a, user_a2, [user_a, user_a2])
    _remove_member(db, household_a, user_a2)
    resp = client.patch(f"{_expenses(household_a)}{exp['id']}", headers=_auth(token_a), json={
        "description": "Neu", "paid_by_user_id": str(user_a2.id),
    })
    assert resp.status_code == 200, resp.text


def test_adding_new_non_member_still_rejected(client, db, household_a, token_a, user_a, ex_member_debt):
    stranger = _make_user(db, "stranger2@example.com")
    resp = client.patch(f"{_expenses(household_a)}{ex_member_debt['id']}", headers=_auth(token_a), json={
        "participant_ids": [str(user_a.id), str(stranger.id)],
    })
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "USERS_NOT_IN_HOUSEHOLD"

    resp = client.patch(f"{_expenses(household_a)}{ex_member_debt['id']}", headers=_auth(token_a), json={
        "paid_by_user_id": str(stranger.id),
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Betrag ändern ohne Teilnehmerliste
# ---------------------------------------------------------------------------


def test_amount_change_keeps_participant_subset(client, db, household_a, token_a, user_a, user_a2):
    third = _make_user(db, "third@example.com", household_a)
    exp = _create_expense(client, household_a, token_a, user_a, [user_a, user_a2])
    resp = client.patch(f"{_expenses(household_a)}{exp['id']}", headers=_auth(token_a), json={"amount_rappen": 1200})
    assert resp.status_code == 200
    assert _shares(resp.json()) == {str(user_a.id): 600, str(user_a2.id): 600}
    assert str(third.id) not in _shares(resp.json())
