"""
Multi-Tenant Scoping Tests für Notes.

Stellt sicher, dass User NUR auf Notizen ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
"""

import uuid


# ---------------------------------------------------------------------------
# Positiv: User A liest eigene Notizen → 200
# ---------------------------------------------------------------------------


def test_user_a_can_read_own_notes(client, household_a, token_a, note_a):
    """GET eigene Notizen liefert 200 und enthält die eigene Notiz."""
    resp = client.get(
        f"/api/households/{household_a.id}/notes/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(n["id"] == str(note_a.id) for n in data)


# ---------------------------------------------------------------------------
# Negativ: User A liest Notizen von Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_read_other_household_notes(
    client, household_b, token_a, note_b
):
    """GET fremde Notizen liefert 403 Forbidden."""
    resp = client.get(
        f"/api/households/{household_b.id}/notes/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A erstellt Notiz in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_create_in_other_household(
    client, household_b, token_a, user_b
):
    """POST in fremden Household liefert 403 Forbidden."""
    resp = client.post(
        f"/api/households/{household_b.id}/notes/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Hacker-Notiz"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A patcht Notiz in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_patch_other_household_note(
    client, household_b, token_a, note_b
):
    """PATCH auf fremde Notiz liefert 403 Forbidden."""
    resp = client.patch(
        f"/api/households/{household_b.id}/notes/{note_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"title": "Gehackte Notiz"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A löscht Notiz in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_delete_other_household_note(
    client, household_b, token_a, note_b
):
    """DELETE auf fremde Notiz liefert 403 Forbidden."""
    resp = client.delete(
        f"/api/households/{household_b.id}/notes/{note_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403
