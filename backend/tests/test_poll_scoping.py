"""
Multi-Tenant Scoping Tests für Event Polls.

Stellt sicher, dass User NUR auf Polls ihres eigenen Households
zugreifen können. Cross-Household-Zugriffe müssen mit 403 abgelehnt werden.
Zusätzlich: Vote-Wechsel und Decide-Flow.
"""

import uuid

import pytest

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


def test_decide_emits_full_event_payload(client, household_a, token_a, poll_a, calendar_a, _mock_socket_emit):
    """Logik-Review L-03: Der Kalender fügt das `event_created`-Objekt direkt in seine Liste
    ein; ohne Zeiten und Kalender-ID stürzt die Ansicht beim Rendern ab."""
    headers = {"Authorization": f"Bearer {token_a}"}
    options = client.get(f"/api/households/{household_a.id}/polls/{poll_a.id}", headers=headers).json()["options"]
    resp = client.post(
        f"/api/households/{household_a.id}/polls/{poll_a.id}/decide",
        headers=headers,
        json={"option_id": options[0]["id"], "event_title": "Treffen", "calendar_id": str(calendar_a.id)},
    )
    assert resp.status_code == 200

    payloads = [c.args[2] for c in _mock_socket_emit.call_args_list if c.args[1] == "event_created"]
    assert len(payloads) == 1
    event = payloads[0]
    assert event["id"] == resp.json()["decided_event_id"]
    assert event["calendar_id"] == str(calendar_a.id)
    # poll_a hat Optionen ohne Uhrzeit (Altbestand) → ganztägig am heutigen Datum (PD-K2)
    assert event["all_day"] is True
    assert event["participant_ids"] == []
    # Zeiten wie bei POST /events: in Haushaltszeit mit Offset
    assert event["starts_at"].endswith(("+01:00", "+02:00"))
    assert event["ends_at"] is None


@pytest.mark.parametrize("recipe_kind", ["own", "foreign", "missing"])
def test_event_poll_rejects_recipe_references_without_existence_oracle(
    client, household_a, token_a, recipe_a, recipe_b, recipe_kind
):
    recipe_id = {"own": recipe_a.id, "foreign": recipe_b.id, "missing": uuid.uuid4()}[recipe_kind]
    response = client.post(
        f"/api/households/{household_a.id}/polls/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"question": "Meet?", "poll_type": "event", "options": [
            {"label": "One", "recipe_id": str(recipe_id)}, {"label": "Two"},
        ]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "POLL_OPTION_INVALID", "message": "recipe_id is only supported for meal polls",
    }


def test_legacy_event_recipe_hidden_on_list_detail_and_socket(
    client, db, household_a, token_a, poll_a, recipe_b, _mock_socket_emit
):
    option = poll_a.options[0]
    option.recipe_id = recipe_b.id  # Pre-fix invalid data, deliberately bypass API.
    db.commit()
    headers = {"Authorization": f"Bearer {token_a}"}
    url = f"/api/households/{household_a.id}/polls/"
    detail = client.get(url + str(poll_a.id), headers=headers).json()
    listing = client.get(url, headers=headers).json()
    assert all(opt["recipe_id"] is None for opt in detail["options"])
    assert all(opt["recipe_id"] is None for poll in listing for opt in poll["options"])
    voted = client.post(url + f"{poll_a.id}/vote", headers=headers, json={"option_id": str(option.id)})
    assert voted.status_code == 200
    assert all(opt["recipe_id"] is None for opt in voted.json()["options"])
    payloads = [call.args[2] for call in _mock_socket_emit.call_args_list if call.args[1] == "poll_voted"]
    assert payloads
    assert all(opt["recipe_id"] is None for payload in payloads for opt in payload["options"])
    db.delete(recipe_b)
    db.commit()
    after_delete = client.get(url + str(poll_a.id), headers=headers).json()
    assert [opt["recipe_id"] for opt in after_delete["options"]] == [opt["recipe_id"] for opt in detail["options"]]
