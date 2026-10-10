"""
PD-K3: "Heute"-Termine auf Dashboard und Widget enthalten auch mehrtägige Termine,
die vor heute begonnen haben und heute noch laufen (wie der Kalender).
"""

from datetime import date
from unittest.mock import patch


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create(client, household, token, calendar, **fields):
    body = {"title": "Termin", "calendar_id": str(calendar.id), **fields}
    resp = client.post(f"/api/households/{household.id}/events/", headers=_auth(token), json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _seed(client, household, token, calendar):
    _create(client, household, token, calendar, title="Ferien", all_day=True,
            starts_at="2026-10-05T00:00:00", ends_at="2026-10-09T00:00:00")
    _create(client, household, token, calendar, title="Messe",
            starts_at="2026-10-06T09:00:00", ends_at="2026-10-07T17:00:00")
    _create(client, household, token, calendar, title="Heute", starts_at="2026-10-07T12:00:00")
    _create(client, household, token, calendar, title="Vorbei",
            starts_at="2026-10-05T09:00:00", ends_at="2026-10-06T10:00:00")
    _create(client, household, token, calendar, title="Morgen", starts_at="2026-10-08T09:00:00")


def test_dashboard_includes_multi_day_events_spanning_today(client, household_a, token_a, calendar_a):
    _seed(client, household_a, token_a, calendar_a)
    with patch("app.routers.dashboard.today_in_tz", return_value=date(2026, 10, 7)):
        resp = client.get(f"/api/households/{household_a.id}/dashboard", headers=_auth(token_a))
    assert resp.status_code == 200
    titles = [i["title"] for i in resp.json()["events"]["items"]]
    assert titles == ["Ferien", "Messe", "Heute"]


def test_widget_includes_multi_day_events_spanning_today(client, household_a, token_a, calendar_a):
    _seed(client, household_a, token_a, calendar_a)
    plain = client.post(f"/api/households/{household_a.id}/widget-token", headers=_auth(token_a)).json()["token"]
    with patch("app.routers.widget.household_today", return_value=date(2026, 10, 7)):
        resp = client.get("/api/widget/summary", headers=_auth(plain))
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert [e["title"] for e in events] == ["Ferien", "Messe", "Heute"]
    # Läuft seit gestern → keine (gestrige) Startzeit anzeigen
    assert events[1]["time"] is None
    assert events[2]["time"] == "12:00"
