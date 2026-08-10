"""
Multi-Tenant Scoping Tests für Calendars.

Stellt sicher, dass User NUR auf Kalender ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
Validierungen (LAST_CALENDAR, CALENDAR_NOT_EMPTY) werden ebenfalls geprüft.
"""

import uuid


# ---------------------------------------------------------------------------
# Positiv: User A liest eigene Kalender → 200
# ---------------------------------------------------------------------------


def test_user_a_can_read_own_calendars(client, household_a, token_a, calendar_a):
    """GET eigene Kalender liefert 200 und enthält den eigenen Kalender."""
    resp = client.get(
        f"/api/households/{household_a.id}/calendars/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(c["id"] == str(calendar_a.id) for c in data)


# ---------------------------------------------------------------------------
# Negativ: User A liest Kalender von Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_read_other_household_calendars(
    client, household_b, token_a, calendar_b
):
    """GET fremde Kalender liefert 403 Forbidden."""
    resp = client.get(
        f"/api/households/{household_b.id}/calendars/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: User A erstellt Kalender → 201
# ---------------------------------------------------------------------------


def test_user_a_can_create_calendar(client, household_a, token_a):
    """POST neuen Kalender liefert 201."""
    resp = client.post(
        f"/api/households/{household_a.id}/calendars/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Arbeit",
            "color": "#FF5733",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Arbeit"
    assert data["color"] == "#FF5733"
    assert data["position"] == 0
    assert data["household_id"] == str(household_a.id)


# ---------------------------------------------------------------------------
# Negativ: User A erstellt Kalender in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_create_in_other_household(
    client, household_b, token_a
):
    """POST in fremden Household liefert 403 Forbidden."""
    resp = client.post(
        f"/api/households/{household_b.id}/calendars/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Hacker-Kalender",
            "color": "#000000",
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: User A kann Kalender umbenennen / Farbe ändern → 200
# ---------------------------------------------------------------------------


def test_user_a_can_update_calendar(client, household_a, token_a, calendar_a):
    """PATCH eigenen Kalender liefert 200 mit aktualisierten Daten."""
    resp = client.patch(
        f"/api/households/{household_a.id}/calendars/{calendar_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Privat", "color": "#00FF00"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Privat"
    assert data["color"] == "#00FF00"


# ---------------------------------------------------------------------------
# Negativ: Letzten Kalender löschen → 422 LAST_CALENDAR
# ---------------------------------------------------------------------------


def test_cannot_delete_last_calendar(client, household_a, token_a, calendar_a):
    """DELETE des letzten Kalenders liefert 422 LAST_CALENDAR."""
    resp = client.delete(
        f"/api/households/{household_a.id}/calendars/{calendar_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail", {})
    assert detail.get("code") == "LAST_CALENDAR"


# ---------------------------------------------------------------------------
# Negativ: Kalender mit Events löschen → 422 CALENDAR_NOT_EMPTY
# ---------------------------------------------------------------------------


def test_cannot_delete_calendar_with_events(
    client, household_a, token_a, calendar_a, event_a
):
    """DELETE eines Kalenders mit Events liefert 422 CALENDAR_NOT_EMPTY."""
    # Zweiten Kalender erstellen, damit LAST_CALENDAR nicht greift
    resp_create = client.post(
        f"/api/households/{household_a.id}/calendars/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Zweiter", "color": "#AABBCC"},
    )
    assert resp_create.status_code == 201

    # calendar_a hat event_a → CALENDAR_NOT_EMPTY
    resp = client.delete(
        f"/api/households/{household_a.id}/calendars/{calendar_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 422
    detail = resp.json().get("detail", {})
    assert detail.get("code") == "CALENDAR_NOT_EMPTY"


# ---------------------------------------------------------------------------
# Positiv: Leeren Kalender löschen (wenn >1 existiert) → 204
# ---------------------------------------------------------------------------


def test_can_delete_empty_calendar(client, household_a, token_a, calendar_a):
    """DELETE eines leeren Kalenders (wenn >1 vorhanden) liefert 204."""
    # Zweiten Kalender erstellen
    resp_create = client.post(
        f"/api/households/{household_a.id}/calendars/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"name": "Temporär", "color": "#112233"},
    )
    assert resp_create.status_code == 201
    new_cal_id = resp_create.json()["id"]

    # Den neuen (leeren) Kalender löschen
    resp = client.delete(
        f"/api/households/{household_a.id}/calendars/{new_cal_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# Validierung: Ungültige Hex-Farbe → 422
# ---------------------------------------------------------------------------


def test_create_calendar_invalid_color_rejected(client, household_a, token_a):
    """POST mit ungültiger Hex-Farbe liefert 422."""
    resp = client.post(
        f"/api/households/{household_a.id}/calendars/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "name": "Test",
            "color": "rot",
        },
    )
    assert resp.status_code == 422
