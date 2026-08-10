"""
Multi-Tenant Scoping Tests für Event Polls.

Stellt sicher, dass User NUR auf Polls ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
Zusätzlich: Vote-Wechsel und Decide-Flow.
"""

import uuid


# ---------------------------------------------------------------------------
# Positiv: User A liest eigene Polls → 200
# ---------------------------------------------------------------------------


def test_user_a_can_read_own_polls(client, household_a, token_a, poll_a):
    """GET eigene Polls liefert 200 und enthält den eigenen Poll."""
    resp = client.get(
        f"/api/households/{household_a.id}/polls/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(p["id"] == str(poll_a.id) for p in data)


# ---------------------------------------------------------------------------
# Negativ: User A liest Polls von Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_read_other_household_polls(
    client, household_b, token_a, poll_b
):
    """GET fremde Polls liefert 403 Forbidden."""
    resp = client.get(
        f"/api/households/{household_b.id}/polls/",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A erstellt Poll in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_create_poll_in_other_household(
    client, household_b, token_a, user_b
):
    """POST in fremden Household liefert 403 Forbidden."""
    resp = client.post(
        f"/api/households/{household_b.id}/polls/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "question": "Hacker-Frage",
            "options": [
                {"label": "Option A"},
                {"label": "Option B"},
            ],
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A voted in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_vote_in_other_household(
    client, household_b, token_a, poll_b
):
    """POST vote in fremden Household liefert 403 Forbidden."""
    option_id = str(uuid.uuid4())  # egal, 403 kommt vorher
    resp = client.post(
        f"/api/households/{household_b.id}/polls/{poll_b.id}/vote",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"option_id": option_id},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A entscheidet Poll in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_decide_in_other_household(
    client, household_b, token_a, poll_b
):
    """POST decide in fremden Household liefert 403 Forbidden."""
    option_id = str(uuid.uuid4())
    resp = client.post(
        f"/api/households/{household_b.id}/polls/{poll_b.id}/decide",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "option_id": option_id,
            "event_title": "Hacker-Event",
            "event_category": "sonstiges",
        },
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Negativ: User A löscht Poll in Household B → 403
# ---------------------------------------------------------------------------


def test_user_a_cannot_delete_poll_in_other_household(
    client, household_b, token_a, poll_b
):
    """DELETE auf fremden Poll liefert 403 Forbidden."""
    resp = client.delete(
        f"/api/households/{household_b.id}/polls/{poll_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Positiv: Vote wechseln funktioniert
# ---------------------------------------------------------------------------


def test_vote_switches_existing_vote(client, household_a, token_a, poll_a, db):
    """Wenn User bereits für Option A gestimmt hat und dann für B stimmt,
    wird die alte Stimme gelöscht und eine neue erstellt."""
    # Poll-Optionen laden
    resp = client.get(
        f"/api/households/{household_a.id}/polls/{poll_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    options = resp.json()["options"]
    opt_a_id = options[0]["id"]
    opt_b_id = options[1]["id"]

    # Erste Stimme für Option A
    resp1 = client.post(
        f"/api/households/{household_a.id}/polls/{poll_a.id}/vote",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"option_id": opt_a_id},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    # Option A hat 1 Vote
    opt_a_votes = [o for o in data1["options"] if o["id"] == opt_a_id][0]["votes"]
    assert len(opt_a_votes) == 1

    # Wechsel auf Option B
    resp2 = client.post(
        f"/api/households/{household_a.id}/polls/{poll_a.id}/vote",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"option_id": opt_b_id},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    # Option A hat 0 Votes, Option B hat 1 Vote
    opt_a_votes2 = [o for o in data2["options"] if o["id"] == opt_a_id][0]["votes"]
    opt_b_votes2 = [o for o in data2["options"] if o["id"] == opt_b_id][0]["votes"]
    assert len(opt_a_votes2) == 0
    assert len(opt_b_votes2) == 1


# ---------------------------------------------------------------------------
# Positiv: Decide erstellt Event und schliesst Poll
# ---------------------------------------------------------------------------


def test_decide_creates_event_and_closes_poll(
    client, household_a, token_a, poll_a, calendar_a, db
):
    """POST decide erstellt ein Event, setzt status=entschieden und decided_event_id."""
    # Poll-Optionen laden
    resp = client.get(
        f"/api/households/{household_a.id}/polls/{poll_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 200
    options = resp.json()["options"]
    opt_id = options[0]["id"]

    # Decide
    resp2 = client.post(
        f"/api/households/{household_a.id}/polls/{poll_a.id}/decide",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "option_id": opt_id,
            "event_title": "Treffen am Montag",
            "calendar_id": str(calendar_a.id),
        },
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["status"] == "entschieden"
    assert data["decided_event_id"] is not None

    # Nochmal decide → Fehler (already decided)
    resp3 = client.post(
        f"/api/households/{household_a.id}/polls/{poll_a.id}/decide",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "option_id": opt_id,
            "event_title": "Nochmal",
            "calendar_id": str(calendar_a.id),
        },
    )
    assert resp3.status_code == 400
    assert resp3.json()["detail"]["code"] == "POLL_ALREADY_DECIDED"
