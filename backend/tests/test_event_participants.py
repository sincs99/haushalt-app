"""
CASA-21 (Kalender-Teil): Teilnehmer eines Termins und Rezepte einer Abstimmung
müssen zum Haushalt gehören.

- Teilnehmer: nur aktuelle Mitglieder; Duplikate werden entfernt; Ex-Mitglieder,
  die bereits auf dem Termin stehen, dürfen beim Bearbeiten bleiben.
- Abstimmungen: recipe_id wird für ALLE Abstimmungstypen geprüft (auch "event").
"""

import uuid

from app.models import HouseholdMember


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create(client, household, token, calendar, participant_ids):
    return client.post(
        f"/api/households/{household.id}/events/",
        headers=_auth(token),
        json={
            "title": "Termin",
            "starts_at": "2026-10-07T09:00:00",
            "calendar_id": str(calendar.id),
            "participant_ids": [str(p) for p in participant_ids],
        },
    )


def test_create_rejects_foreign_participant(client, household_a, token_a, calendar_a, user_b):
    resp = _create(client, household_a, token_a, calendar_a, [user_b.id])
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "USERS_NOT_IN_HOUSEHOLD"


def test_create_rejects_random_participant(client, household_a, token_a, calendar_a):
    resp = _create(client, household_a, token_a, calendar_a, [uuid.uuid4()])
    assert resp.status_code == 422


def test_create_dedupes_participants(client, household_a, token_a, calendar_a, user_a, user_a2):
    resp = _create(client, household_a, token_a, calendar_a, [user_a.id, user_a2.id, user_a.id])
    assert resp.status_code == 201
    assert resp.json()["participant_ids"] == [str(user_a.id), str(user_a2.id)]


def test_update_rejects_foreign_participant(client, household_a, token_a, calendar_a, user_a, user_b):
    ev = _create(client, household_a, token_a, calendar_a, [user_a.id]).json()
    resp = client.patch(
        f"/api/households/{household_a.id}/events/{ev['id']}",
        headers=_auth(token_a),
        json={"participant_ids": [str(user_a.id), str(user_b.id)]},
    )
    assert resp.status_code == 422


def test_update_keeps_ex_member_already_on_record(
    client, db, household_a, token_a, calendar_a, user_a, user_a2
):
    ev = _create(client, household_a, token_a, calendar_a, [user_a.id, user_a2.id]).json()
    # user_a2 verlässt den Haushalt
    db.query(HouseholdMember).filter_by(household_id=household_a.id, user_id=user_a2.id).delete()
    db.commit()

    resp = client.patch(
        f"/api/households/{household_a.id}/events/{ev['id']}",
        headers=_auth(token_a),
        json={"title": "Neu", "participant_ids": [str(user_a.id), str(user_a2.id), str(user_a2.id)]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["participant_ids"] == [str(user_a.id), str(user_a2.id)]


def test_event_poll_rejects_foreign_recipe(client, household_a, token_a, recipe_b):
    resp = client.post(
        f"/api/households/{household_a.id}/polls/",
        headers=_auth(token_a),
        json={
            "question": "Wann?",
            "poll_type": "event",
            "options": [
                {"label": "A", "starts_at": "2026-10-10T18:00:00", "recipe_id": str(recipe_b.id)},
                {"label": "B", "starts_at": "2026-10-11T18:00:00"},
            ],
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "POLL_OPTION_INVALID"
