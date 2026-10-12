"""
Zeiten von Termin-Abstimmungen (CASA-60, PD-K2, PD-K5).

- Optionszeiten werden wie Termine in Haushaltszeit ausgeliefert (nicht UTC).
- Termin-Optionen brauchen eine Uhrzeit (starts_at); Essens-Optionen nicht.
- Altbestand ohne Uhrzeit: Entscheiden legt einen ganztägigen Termin am heutigen
  Haushaltsdatum an statt "jetzt" mit Mikrosekunden.
"""

from datetime import date
from unittest.mock import patch

from app.models import Event


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_poll(client, household, token, options, **extra):
    return client.post(
        f"/api/households/{household.id}/polls/",
        headers=_auth(token),
        json={"question": "Wann?", "options": options, **extra},
    )


def test_option_times_in_household_time(client, household_a, token_a, _mock_socket_emit):
    resp = _create_poll(client, household_a, token_a, [
        {"label": "Sa früh", "starts_at": "2026-10-10T00:30:00"},
        {"label": "So", "starts_at": "2026-10-11T18:00:00"},
    ])
    assert resp.status_code == 201, resp.text
    starts = [o["starts_at"] for o in resp.json()["options"]]
    assert "2026-10-10T00:30:00+02:00" in starts
    # GET, Liste und Socket-Payload ebenso
    poll_id = resp.json()["id"]
    got = client.get(f"/api/households/{household_a.id}/polls/{poll_id}", headers=_auth(token_a)).json()
    assert "2026-10-10T00:30:00+02:00" in [o["starts_at"] for o in got["options"]]
    listed = client.get(f"/api/households/{household_a.id}/polls/", headers=_auth(token_a)).json()
    assert "2026-10-10T00:30:00+02:00" in [o["starts_at"] for o in listed[0]["options"]]
    payload = next(c.args[2] for c in _mock_socket_emit.call_args_list if c.args[1] == "poll_created")
    assert "2026-10-10T00:30:00+02:00" in [o["starts_at"] for o in payload["options"]]


def test_event_poll_option_requires_time(client, household_a, token_a):
    resp = _create_poll(client, household_a, token_a, [
        {"label": "Irgendwann"},
        {"label": "So", "starts_at": "2026-10-11T18:00:00"},
    ])
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "POLL_OPTION_TIME_REQUIRED"


def test_meal_poll_option_needs_no_time(client, household_a, token_a):
    resp = _create_poll(
        client, household_a, token_a, [{"label": "Pasta"}, {"label": "Pizza"}],
        poll_type="meal", meal_date="2026-10-12",
    )
    assert resp.status_code == 201


def test_event_poll_option_in_dst_gap_rejected(client, household_a, token_a):
    resp = _create_poll(client, household_a, token_a, [
        {"label": "Lücke", "starts_at": "2026-03-29T02:30:00"},
        {"label": "So", "starts_at": "2026-03-29T18:00:00"},
    ])
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "EVENT_TIME_NONEXISTENT"


def test_decide_legacy_option_without_time_creates_all_day_event(
    client, db, household_a, token_a, poll_a, calendar_a
):
    """poll_a (Fixture) hat Optionen ohne Uhrzeit (Altbestand)."""
    with patch("app.routers.polls.household_today", return_value=date(2026, 10, 9)):
        resp = client.post(
            f"/api/households/{household_a.id}/polls/{poll_a.id}/decide",
            headers=_auth(token_a),
            json={"option_id": str(poll_a.options[0].id), "event_title": "Treffen",
                  "calendar_id": str(calendar_a.id)},
        )
    assert resp.status_code == 200, resp.text
    event_id = resp.json()["decided_event_id"]
    got = client.get(f"/api/households/{household_a.id}/events/{event_id}", headers=_auth(token_a)).json()
    assert got["all_day"] is True
    assert got["starts_at"] == "2026-10-09T00:00:00+02:00"
    assert db.query(Event).filter_by(household_id=household_a.id).count() == 1
