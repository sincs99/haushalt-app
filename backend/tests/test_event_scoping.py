"""
Multi-Tenant Scoping Tests für Events.

Stellt sicher, dass User NUR auf Events ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Positiv: User A liest eigene Events → 200
# ---------------------------------------------------------------------------


def test_user_a_can_read_own_events(client, household_a, token_a, event_a):
    """GET eigene Events liefert 200 und enthält das eigene Event."""
    resp = client.get(
        f"/api/households/{household_a.id}/events/"
        f"?from_date=2026-01-01T00:00:00Z&to_date=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(e["id"] == str(event_a.id) for e in data)


# ---------------------------------------------------------------------------
# Negativ: User A liest Events von Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_read_other_household_events(
    client, household_b, token_a, event_b
):
    """GET fremde Events liefert 403 Forbidden."""
    resp = client.get(
        f"/api/households/{household_b.id}/events/"
        f"?from_date=2026-01-01T00:00:00Z&to_date=2026-12-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A erstellt Event in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_create_in_other_household(
    client, household_b, token_a, user_b
):
    """POST in fremden Household liefert 403 Forbidden."""
    resp = client.post(
        f"/api/households/{household_b.id}/events/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "title": "Hacker-Event",
            "starts_at": "2026-08-15T10:00:00Z",
            "category": "sonstiges",
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A patcht Event in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_patch_other_household_event(
    client, household_b, token_a, event_b
):
    """PATCH auf fremdes Event liefert 403 Forbidden."""
    resp = client.patch(
        f"/api/households/{household_b.id}/events/{event_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Gehacktes Event"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A löscht Event in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_delete_other_household_event(
    client, household_b, token_a, event_b
):
    """DELETE auf fremdes Event liefert 403 Forbidden."""
    resp = client.delete(
        f"/api/households/{household_b.id}/events/{event_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: from_date / to_date Filter funktioniert korrekt
# ---------------------------------------------------------------------------


def test_from_to_filter_works(client, household_a, token_a, event_a):
    """Events ausserhalb des Zeitfensters werden nicht zurückgegeben."""
    # event_a starts_at = 2026-08-07T10:00:00Z
    # Anfrage mit Range VOR dem Event → leere Liste
    resp = client.get(
        f"/api/households/{household_a.id}/events/"
        f"?from_date=2026-01-01T00:00:00Z&to_date=2026-01-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 0

    # Anfrage mit Range die das Event enthält → 1 Ergebnis
    resp2 = client.get(
        f"/api/households/{household_a.id}/events/"
        f"?from_date=2026-08-01T00:00:00Z&to_date=2026-08-31T23:59:59Z",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2) == 1
    assert data2[0]["id"] == str(event_a.id)
