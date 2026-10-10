"""Haustiere: Füttern, Medikamente, Archiv, Pflegeintervalle (CASA-13/14/15, PD-P1–P4)."""

import uuid

from app.models import Pet


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _pet(db, household, name="Mia", **kw):
    pet = Pet(id=uuid.uuid4(), household_id=household.id, name=name, species="cat", **kw)
    db.add(pet)
    db.commit()
    return pet


# ---------------------------------------------------------------------------
# CASA-13: feed-all meldet genau die eigenen Fütterungen
# ---------------------------------------------------------------------------


def test_feed_all_returns_only_created_feedings(client, db, household_a, token_a, pet_a):
    other = _pet(db, household_a, "Leo")
    base = f"/api/households/{household_a.id}/pets"
    assert client.post(f"{base}/{pet_a.id}/feedings", json={"slot": "morning"}, headers=_h(token_a)).status_code == 201

    resp = client.post(f"{base}/feed-all", json={"slot": "morning"}, headers=_h(token_a))
    assert resp.status_code == 200
    assert [f["pet_id"] for f in resp.json()] == [str(other.id)]

    status = client.get(f"{base}/feeding-status", headers=_h(token_a)).json()
    assert all(s["morning"] is not None for s in status)
    # Zweiter Aufruf: nichts mehr zu tun
    assert client.post(f"{base}/feed-all", json={"slot": "morning"}, headers=_h(token_a)).json() == []
