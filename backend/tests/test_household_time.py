"""Kalenderdaten in Haushaltszeit statt Server-Uhr (Logik-Review L-01).

Der Server läuft in UTC. Um 00:30 Uhr Schweizer Zeit am 1. November ist es in UTC
noch der 31. Oktober. Buchungen, Budgets und Standard-Daten müssen trotzdem im
November landen.
"""

import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

from app.models import Expense

# 31.10.2026 23:30 UTC = 01.11.2026 00:30 Europe/Zurich (Winterzeit, UTC+1)
LATE_UTC = datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc)
_NOW = "app.services.household_time._utc_now"


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_today_in_timezone_crosses_midnight():
    from app.services.household_time import today_in_timezone

    with patch(_NOW, return_value=LATE_UTC):
        assert today_in_timezone("Europe/Zurich") == date(2026, 11, 1)
        assert today_in_timezone("UTC") == date(2026, 10, 31)
        assert today_in_timezone(None) == date(2026, 11, 1)  # Default Europe/Zurich


def test_book_bill_uses_household_month(client, db, household_a, token_a, user_a, bill_a):
    with patch(_NOW, return_value=LATE_UTC):
        resp = client.post(
            f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}/book",
            headers=_auth(token_a),
        )
    assert resp.status_code == 201
    assert resp.json()["expense_date"].startswith("2026-11-")
    expense = db.get(Expense, uuid.UUID(resp.json()["id"]))
    assert expense.booked_month == date(2026, 11, 1)


def test_october_booking_does_not_block_november_after_midnight(
    client, household_a, token_a, user_a, bill_a
):
    """Oktober am 31.10. (Nachmittag UTC) gebucht, November um 00:30 Uhr lokal → 201, nicht 409."""
    url = f"/api/households/{household_a.id}/recurring-bills/{bill_a.id}/book"
    with patch(_NOW, return_value=datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc)):
        assert client.post(url, headers=_auth(token_a)).status_code == 201
    with patch(_NOW, return_value=LATE_UTC):
        resp = client.post(url, headers=_auth(token_a))
    assert resp.status_code == 201
    # und im November ist der zweite Versuch idempotent
    with patch(_NOW, return_value=datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)):
        assert client.post(url, headers=_auth(token_a)).status_code == 409


def test_budget_default_month_is_household_month(client, household_a, token_a, budget_a):
    with patch(_NOW, return_value=LATE_UTC):
        client.put(
            f"/api/households/{household_a.id}/budget",
            headers=_auth(token_a),
            json={"month": "2026-11-01", "amount_rappen": 70000},
        )
        resp = client.get(f"/api/households/{household_a.id}/budget", headers=_auth(token_a))
    assert resp.status_code == 200
    assert resp.json()["month"] == "2026-11-01"


def test_finance_summary_default_month_and_days_elapsed(client, household_a, token_a, user_a):
    with patch(_NOW, return_value=LATE_UTC):
        resp = client.get(f"/api/households/{household_a.id}/finance-summary", headers=_auth(token_a))
    data = resp.json()
    assert data["month"] == "2026-11-01"
    assert data["days_elapsed"] == 1
    assert data["days_in_month"] == 30


def test_expense_and_settlement_default_date_is_household_today(
    client, household_a, token_a, user_a, user_a2
):
    with patch(_NOW, return_value=LATE_UTC):
        expense = client.post(
            f"/api/households/{household_a.id}/expenses/",
            headers=_auth(token_a),
            json={
                "description": "Pizza",
                "amount_rappen": 3000,
                "paid_by_user_id": str(user_a.id),
                "split_type": "even",
            },
        )
        settlement = client.post(
            f"/api/households/{household_a.id}/settlements/",
            headers=_auth(token_a),
            json={"from_user_id": str(user_a2.id), "to_user_id": str(user_a.id), "amount_rappen": 1500},
        )
    assert expense.status_code == 201
    assert expense.json()["expense_date"] == "2026-11-01"
    assert settlement.status_code == 201
    assert settlement.json()["settled_date"] == "2026-11-01"


def test_meal_plan_default_week_is_household_week(client, household_a, token_a, user_a):
    """31.10.2026 ist ein Samstag (KW 44), der 1.11. ein Sonntag derselben Woche —
    deshalb mit einer Sonntag-Nacht prüfen: 01.11. 23:30 UTC = Montag 02.11. 00:30 lokal."""
    sunday_night_utc = datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc)
    client.put(
        f"/api/households/{household_a.id}/meal-plan/2026-11-02",
        headers=_auth(token_a),
        json={"free_text": "Risotto"},
    )
    client.put(
        f"/api/households/{household_a.id}/meal-plan/2026-11-01",
        headers=_auth(token_a),
        json={"free_text": "Fondue"},
    )
    with patch(_NOW, return_value=sunday_night_utc):
        resp = client.get(f"/api/households/{household_a.id}/meal-plan/", headers=_auth(token_a))
    dates = [e["date"] for e in resp.json()]
    assert dates == ["2026-11-02"]
