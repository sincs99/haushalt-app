"""
Tests für Datenbank-Integrität: Löschregeln, eindeutige Stimmen und Buchungen.

Stellt sicher, dass:
- ein Termin aus einer entschiedenen Abstimmung gelöscht werden kann
- das letzte Mitglied einen Haushalt mit entschiedener Abstimmung verlassen kann
- Abstimmungen nur einmal entschieden werden und abgeschlossen bleiben
- eine Person pro Abstimmung genau eine Stimme hat
- eine wiederkehrende Rechnung pro Monat nur einmal gebucht wird
- die Alembic-Migrationen genau einen Head haben
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from app.models import Event, EventPoll, EventPollVote, Expense, Household


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _polls(household):
    return f"/api/households/{household.id}/polls/"


def _decide(client, household, token, poll, calendar, option_id):
    return client.post(
        f"{_polls(household)}{poll.id}/decide",
        headers=_auth(token),
        json={"option_id": option_id, "event_title": "Treffen", "calendar_id": str(calendar.id)},
    )


def _options(poll):
    return [str(o.id) for o in poll.options]


# ---------------------------------------------------------------------------
# Löschregeln
# ---------------------------------------------------------------------------


def test_delete_event_created_by_poll(client, db, household_a, token_a, poll_a, calendar_a):
    resp = _decide(client, household_a, token_a, poll_a, calendar_a, _options(poll_a)[0])
    event_id = resp.json()["decided_event_id"]

    resp = client.delete(f"/api/households/{household_a.id}/events/{event_id}", headers=_auth(token_a))
    assert resp.status_code == 204

    db.expire_all()
    poll = db.get(EventPoll, poll_a.id)
    assert poll.status == "entschieden"
    assert poll.decided_event_id is None


def test_last_member_can_leave_household_with_decided_poll(
    client, db, household_a, token_a, user_a, poll_a, calendar_a
):
    assert _decide(client, household_a, token_a, poll_a, calendar_a, _options(poll_a)[0]).status_code == 200
    resp = client.post(f"/api/households/{household_a.id}/leave", headers=_auth(token_a))
    assert resp.status_code == 204

    db.expire_all()
    assert db.get(Household, household_a.id) is None
    assert db.query(EventPoll).count() == 0
    assert db.query(Event).count() == 0


# ---------------------------------------------------------------------------
# Abstimmungen
# ---------------------------------------------------------------------------


def test_decided_poll_cannot_be_decided_again(client, household_a, token_a, poll_a, calendar_a):
    opt = _options(poll_a)[0]
    assert _decide(client, household_a, token_a, poll_a, calendar_a, opt).status_code == 200
    resp = _decide(client, household_a, token_a, poll_a, calendar_a, opt)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "POLL_ALREADY_DECIDED"


def test_vote_on_decided_poll_rejected(client, household_a, token_a, poll_a, calendar_a):
    opt = _options(poll_a)[0]
    assert _decide(client, household_a, token_a, poll_a, calendar_a, opt).status_code == 200
    resp = client.post(f"{_polls(household_a)}{poll_a.id}/vote", headers=_auth(token_a), json={"option_id": opt})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "POLL_ALREADY_DECIDED"


def test_event_decide_on_meal_poll_rejected(client, db, household_a, token_a, poll_a, calendar_a):
    poll_a.poll_type = "meal"
    db.commit()
    resp = _decide(client, household_a, token_a, poll_a, calendar_a, _options(poll_a)[0])
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "POLL_TYPE_MISMATCH"
    db.expire_all()
    assert db.get(EventPoll, poll_a.id).status == "offen"


def test_one_vote_per_user_and_poll(client, db, household_a, token_a, user_a, poll_a):
    first, second = _options(poll_a)
    url = f"{_polls(household_a)}{poll_a.id}/vote"
    for opt in (first, second, second, first):
        assert client.post(url, headers=_auth(token_a), json={"option_id": opt}).status_code == 200

    votes = db.query(EventPollVote).filter_by(user_id=user_a.id).all()
    assert len(votes) == 1
    assert votes[0].poll_id == poll_a.id
    assert str(votes[0].option_id) == first


# ---------------------------------------------------------------------------
# Buchungen wiederkehrender Rechnungen
# ---------------------------------------------------------------------------


def test_moving_booked_expense_date_does_not_allow_rebooking(client, db, household_a, token_a, user_a, bill_a):
    url = f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}/book"
    resp = client.post(url, headers=_auth(token_a))
    assert resp.status_code == 201
    expense_id = resp.json()["id"]

    # Datum der Buchung in den Vormonat verschieben
    resp = client.patch(
        f"/api/households/{household_a.id}/expenses/{expense_id}",
        headers=_auth(token_a), json={"expense_date": "2020-01-15"},
    )
    assert resp.status_code == 200

    resp = client.post(url, headers=_auth(token_a))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "BILL_ALREADY_BOOKED"
    assert db.query(Expense).filter_by(recurring_bill_id=bill_a.id).count() == 1

    summary = client.get(f"/api/households/{household_a.id}/finance-summary", headers=_auth(token_a)).json()
    assert {b["id"]: b["is_booked_this_month"] for b in summary["pending_bills"]}[str(bill_a.id)] is True


def test_duplicate_booking_blocked_by_constraint(client, db, household_a, token_a, user_a, bill_a):
    """Simuliert den Race: die Vorab-Prüfung sieht nichts, die DB lehnt ab → 409."""
    from unittest.mock import patch
    from datetime import date

    url = f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}/book"
    assert client.post(url, headers=_auth(token_a)).status_code == 201

    real_query = db.query

    def query_hiding_existing_booking(*entities):
        q = real_query(*entities)
        if len(entities) == 1 and entities[0] is Expense.id:
            return real_query(Expense.id).filter(Expense.booked_month == date(1900, 1, 1))
        return q

    with patch.object(db, "query", side_effect=query_hiding_existing_booking):
        resp = client.post(url, headers=_auth(token_a))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "BILL_ALREADY_BOOKED"
    assert db.query(Expense).filter_by(recurring_bill_id=bill_a.id).count() == 1


# ---------------------------------------------------------------------------
# Migrationen
# ---------------------------------------------------------------------------


def test_alembic_has_single_head():
    """Zwei parallel entstandene Migrationen ergeben zwei Heads — dann bricht
    `alembic upgrade head` beim Deployment ab. Die Tests nutzen create_all und
    würden das sonst nicht bemerken."""
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "migrations"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"Mehrere Alembic-Heads: {heads}"
