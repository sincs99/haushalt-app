"""
Tests für Kalender-Zeiten in Haushaltszeit.

Stellt sicher, dass:
- Uhrzeiten ohne Offset als Wanduhrzeit des Haushalts gelten (09:00 bleibt 09:00)
- Antworten den Offset des Haushalts tragen und beim Zurücksenden nicht wandern
- der Bereichsfilter den letzten Tag und überlappende mehrtägige Termine liefert
- gemischte naive/aware Zeiten keinen 500er auslösen
"""

from datetime import date, datetime, timezone
from unittest.mock import patch

from app.services.event_times import household_tz, range_bounds, to_household_time, to_utc


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _url(household_id, suffix=""):
    return f"/api/households/{household_id}/events/{suffix}"


def _create(client, household, token, calendar, **fields):
    body = {"title": "Termin", "calendar_id": str(calendar.id), **fields}
    resp = client.post(_url(household.id), headers=_auth(token), json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _list(client, household, token, from_date, to_date):
    resp = client.get(
        _url(household.id), headers=_auth(token), params={"from_date": from_date, "to_date": to_date}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Wanduhrzeit des Haushalts
# ---------------------------------------------------------------------------


def test_naive_time_is_household_wall_clock(client, household_a, token_a, calendar_a):
    ev = _create(client, household_a, token_a, calendar_a, starts_at="2026-10-07T09:00:00")
    assert household_a.timezone == "Europe/Zurich"
    assert ev["starts_at"] == "2026-10-07T09:00:00+02:00"


def test_winter_time_offset(client, household_a, token_a, calendar_a):
    ev = _create(client, household_a, token_a, calendar_a, starts_at="2026-12-07T09:00:00")
    assert ev["starts_at"] == "2026-12-07T09:00:00+01:00"


def test_aware_time_is_converted(client, household_a, token_a, calendar_a):
    ev = _create(client, household_a, token_a, calendar_a, starts_at="2026-10-07T09:00:00Z")
    assert ev["starts_at"] == "2026-10-07T11:00:00+02:00"


def test_edit_round_trip_does_not_drift(client, household_a, token_a, calendar_a):
    """Das Frontend schickt beim Bearbeiten die angezeigte Wanduhrzeit zurück."""
    ev = _create(
        client, household_a, token_a, calendar_a,
        starts_at="2026-10-07T09:00:00", ends_at="2026-10-07T10:30:00",
    )
    for _ in range(3):
        wall_start = ev["starts_at"][:19]
        wall_end = ev["ends_at"][:19]
        resp = client.patch(
            _url(household_a.id, ev["id"]), headers=_auth(token_a),
            json={"title": "Umbenannt", "starts_at": wall_start, "ends_at": wall_end},
        )
        assert resp.status_code == 200
        ev = resp.json()
    assert ev["starts_at"] == "2026-10-07T09:00:00+02:00"
    assert ev["ends_at"] == "2026-10-07T10:30:00+02:00"
    # GET liefert dasselbe
    got = client.get(_url(household_a.id, ev["id"]), headers=_auth(token_a)).json()
    assert got["starts_at"] == "2026-10-07T09:00:00+02:00"


def test_mixed_naive_and_aware_times_no_500(client, household_a, token_a, calendar_a):
    ev = _create(
        client, household_a, token_a, calendar_a,
        starts_at="2026-10-07T09:00:00", ends_at="2026-10-07T08:00:00Z",
    )
    assert ev["ends_at"] == "2026-10-07T10:00:00+02:00"
    resp = client.patch(
        _url(household_a.id, ev["id"]), headers=_auth(token_a), json={"ends_at": "2026-10-07T06:00:00Z"}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "EVENT_END_BEFORE_START"


def test_socket_payload_uses_household_time(client, household_a, token_a, calendar_a, _mock_socket_emit):
    _create(client, household_a, token_a, calendar_a, starts_at="2026-10-07T09:00:00")
    payloads = [c.args[2] for c in _mock_socket_emit.call_args_list if c.args[1] == "event_created"]
    assert payloads[-1]["starts_at"] == "2026-10-07T09:00:00+02:00"


# ---------------------------------------------------------------------------
# Bereichsfilter
# ---------------------------------------------------------------------------


def test_week_range_includes_sunday(client, household_a, token_a, calendar_a):
    _create(client, household_a, token_a, calendar_a, title="Sonntag", starts_at="2026-10-11T09:00:00")
    _create(client, household_a, token_a, calendar_a, title="Sonntag spät", starts_at="2026-10-11T23:30:00")
    _create(client, household_a, token_a, calendar_a, title="Nächster Montag", starts_at="2026-10-12T00:30:00")
    titles = [e["title"] for e in _list(client, household_a, token_a, "2026-10-05", "2026-10-11")]
    assert titles == ["Sonntag", "Sonntag spät"]


def test_early_morning_event_on_first_day(client, household_a, token_a, calendar_a):
    """00:30 Haushaltszeit ist in UTC noch der Vortag — muss trotzdem dazugehören."""
    _create(client, household_a, token_a, calendar_a, title="Früh", starts_at="2026-10-05T00:30:00")
    titles = [e["title"] for e in _list(client, household_a, token_a, "2026-10-05", "2026-10-11")]
    assert titles == ["Früh"]


def test_multi_day_event_starting_before_range(client, household_a, token_a, calendar_a):
    _create(
        client, household_a, token_a, calendar_a, title="Ferien", all_day=True,
        starts_at="2026-10-01T00:00:00", ends_at="2026-10-10T23:59:00",
    )
    _create(
        client, household_a, token_a, calendar_a, title="Vorbei", all_day=True,
        starts_at="2026-09-20T00:00:00", ends_at="2026-10-04T23:59:00",
    )
    titles = [e["title"] for e in _list(client, household_a, token_a, "2026-10-05", "2026-10-11")]
    assert titles == ["Ferien"]


def test_all_day_event_keeps_its_date(client, household_a, token_a, calendar_a):
    ev = _create(client, household_a, token_a, calendar_a, all_day=True, starts_at="2026-10-07T00:00:00")
    assert ev["starts_at"].startswith("2026-10-07T00:00:00")
    titles = [e["id"] for e in _list(client, household_a, token_a, "2026-10-07", "2026-10-07")]
    assert titles == [ev["id"]]
    assert _list(client, household_a, token_a, "2026-10-06", "2026-10-06") == []


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def test_dashboard_today_events_in_household_time(client, household_a, token_a, calendar_a):
    _create(client, household_a, token_a, calendar_a, title="Früh", starts_at="2026-10-07T00:30:00")
    _create(client, household_a, token_a, calendar_a, title="Morgen", starts_at="2026-10-08T00:30:00")
    with patch("app.routers.dashboard.today_in_tz", return_value=date(2026, 10, 7)):
        resp = client.get(f"/api/households/{household_a.id}/dashboard", headers=_auth(token_a))
    assert resp.status_code == 200
    items = resp.json()["events"]["items"]
    assert [i["title"] for i in items] == ["Früh"]
    assert items[0]["starts_at"] == "2026-10-07T00:30:00+02:00"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def test_helpers():
    tz = household_tz("Europe/Zurich")
    assert to_utc(datetime(2026, 10, 7, 9), tz) == datetime(2026, 10, 7, 7, tzinfo=timezone.utc)
    assert to_household_time(datetime(2026, 10, 7, 7), tz).isoformat() == "2026-10-07T09:00:00+02:00"
    start, end = range_bounds(date(2026, 10, 5), date(2026, 10, 11), tz)
    assert start == datetime(2026, 10, 4, 22, tzinfo=timezone.utc)
    assert end == datetime(2026, 10, 11, 22, tzinfo=timezone.utc)
