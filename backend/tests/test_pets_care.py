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


# ---------------------------------------------------------------------------
# CASA-15 / PD-P2 / PD-P3: Tiere archivieren statt Verlauf löschen
# ---------------------------------------------------------------------------


def test_archive_and_unarchive_pet(client, db, household_a, token_a, pet_a):
    base = f"/api/households/{household_a.id}/pets"
    resp = client.post(f"{base}/{pet_a.id}/archive", headers=_h(token_a))
    assert resp.status_code == 200
    assert resp.json()["archived"] is True
    assert resp.json()["archived_at"] is not None

    # Liste enthält archivierte Tiere weiterhin (Archiv-Ansicht), Status/feed-all nicht
    assert [p["id"] for p in client.get(f"{base}/", headers=_h(token_a)).json()] == [str(pet_a.id)]
    assert client.get(f"{base}/feeding-status", headers=_h(token_a)).json() == []
    assert client.post(f"{base}/feed-all", json={"slot": "morning"}, headers=_h(token_a)).json() == []
    feed = client.post(f"{base}/{pet_a.id}/feedings", json={"slot": "morning"}, headers=_h(token_a))
    assert feed.status_code == 422
    assert feed.json()["detail"]["code"] == "PET_ARCHIVED"

    resp = client.post(f"{base}/{pet_a.id}/unarchive", headers=_h(token_a))
    assert resp.status_code == 200
    assert resp.json()["archived"] is False
    assert resp.json()["archived_at"] is None
    assert len(client.get(f"{base}/feeding-status", headers=_h(token_a)).json()) == 1


def test_feed_all_skips_archived_pets(client, db, household_a, token_a, pet_a):
    _pet(db, household_a, "Alt", archived=True)
    base = f"/api/households/{household_a.id}/pets"
    created = client.post(f"{base}/feed-all", json={"slot": "evening"}, headers=_h(token_a)).json()
    assert [f["pet_id"] for f in created] == [str(pet_a.id)]


def test_pet_history_counts(client, db, household_a, token_a, pet_a, medication_a):
    base = f"/api/households/{household_a.id}/pets/{pet_a.id}"
    client.post(f"{base}/feedings", json={"slot": "morning"}, headers=_h(token_a))
    client.post(f"{base}/medications/{medication_a.id}/give", headers=_h(token_a))
    client.post(f"{base}/care-tasks/", json={"name": "Impfung", "interval_days": 365, "next_due_at": "2027-01-01"},
                headers=_h(token_a))
    resp = client.get(f"{base}/history", headers=_h(token_a))
    assert resp.status_code == 200
    assert resp.json() == {"feedings": 1, "medications": 1, "medication_logs": 1, "care_tasks": 1}


def test_archived_pet_excluded_from_dashboard_push_and_attention(client, db, household_a, user_a, token_a):
    from datetime import date, datetime, timedelta, timezone

    from app.models import PetCareTask
    from app.services.attention import due_items
    from app.services.push_service import process_pet_care_tasks

    archived = _pet(db, household_a, "Alt", archived=True)
    db.add(PetCareTask(household_id=household_a.id, pet_id=archived.id, name="Impfung",
                       interval_days=30, next_due_at=date.today() - timedelta(days=3)))
    db.commit()

    dash = client.get(f"/api/households/{household_a.id}/dashboard", headers=_h(token_a)).json()
    assert dash["pet_care_due"] == []
    assert [i for i in due_items(db, household_a, user_a.id) if i.kind == "pet"] == []
    assert process_pet_care_tasks(db, datetime.now(timezone.utc).replace(hour=12)) == 0
    assert db.query(PetCareTask).one().notified_at is None


def test_archived_pet_not_offered_as_tag_target(client, db, household_a, token_a, pet_a):
    _pet(db, household_a, "Alt", archived=True)
    resp = client.get(f"/api/households/{household_a.id}/tags/targets", headers=_h(token_a))
    pet_targets = next(t for t in resp.json() if t["target_type"] == "pet")
    assert [o["name"] for o in pet_targets["options"]] == ["Luna"]


# ---------------------------------------------------------------------------
# CASA-14 / CASA-15 / PD-P1 / PD-P2: Medikamente
# ---------------------------------------------------------------------------


def test_delete_pet_with_history_requires_force(client, db, household_a, token_a, pet_a, medication_a):
    """Tier mit Verlauf: 409 PET_HAS_HISTORY mit Zahlen, erst ?force=true löscht (PD-P2)."""
    from app.models import FeedingLog, MedicationLog, PetCareTask

    base = f"/api/households/{household_a.id}/pets/{pet_a.id}"
    assert client.post(f"{base}/feedings", json={"slot": "morning"}, headers=_h(token_a)).status_code == 201
    assert client.post(f"{base}/medications/{medication_a.id}/give", headers=_h(token_a)).status_code == 201

    resp = client.delete(base, headers=_h(token_a))
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "PET_HAS_HISTORY"
    assert detail["history"] == {"feedings": 1, "medications": 1, "medication_logs": 1, "care_tasks": 0}
    assert db.query(FeedingLog).filter_by(pet_id=pet_a.id).count() == 1

    assert client.delete(f"{base}?force=true", headers=_h(token_a)).status_code == 204
    db.expire_all()
    assert db.get(Pet, pet_a.id) is None
    assert db.query(MedicationLog).count() == 0
    assert db.query(PetCareTask).filter_by(pet_id=pet_a.id).count() == 0


def test_delete_pet_with_completed_care_task_requires_force(client, db, household_a, token_a, pet_a):
    from datetime import date

    from app.models import PetCareTask

    db.add(PetCareTask(household_id=household_a.id, pet_id=pet_a.id, name="Wurmkur", interval_days=90,
                       next_due_at=date.today(), last_done_at=date.today()))
    db.commit()
    resp = client.delete(f"/api/households/{household_a.id}/pets/{pet_a.id}", headers=_h(token_a))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "PET_HAS_HISTORY"


def test_delete_pet_without_history_needs_no_force(client, db, household_a, token_a, pet_a, medication_a):
    """Nur Stammdaten (Medikament ohne Gabe, nie erledigte Pflege) → direkt löschbar."""
    from datetime import date

    from app.models import PetCareTask

    db.add(PetCareTask(household_id=household_a.id, pet_id=pet_a.id, name="Krallen", interval_days=30,
                       next_due_at=date.today()))
    db.commit()
    resp = client.delete(f"/api/households/{household_a.id}/pets/{pet_a.id}", headers=_h(token_a))
    assert resp.status_code == 204


def test_delete_medication_with_history_is_rejected(client, db, household_a, token_a, pet_a, medication_a):
    from app.models import MedicationLog

    base = f"/api/households/{household_a.id}/pets/{pet_a.id}/medications/{medication_a.id}"
    assert client.post(f"{base}/give", headers=_h(token_a)).status_code == 201

    resp = client.delete(base, headers=_h(token_a))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "MEDICATION_HAS_HISTORY"
    assert db.query(MedicationLog).filter_by(medication_id=medication_a.id).count() == 1

    # Deaktivieren bleibt möglich
    resp = client.patch(base, json={"active": False}, headers=_h(token_a))
    assert resp.status_code == 200 and resp.json()["active"] is False


def test_delete_medication_without_history(client, household_a, token_a, pet_a, medication_a):
    base = f"/api/households/{household_a.id}/pets/{pet_a.id}/medications/{medication_a.id}"
    assert client.delete(base, headers=_h(token_a)).status_code == 204


def test_give_inactive_medication_is_rejected(client, db, household_a, token_a, pet_a, medication_a):
    medication_a.active = False
    db.commit()
    resp = client.post(
        f"/api/households/{household_a.id}/pets/{pet_a.id}/medications/{medication_a.id}/give",
        headers=_h(token_a),
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "MEDICATION_INACTIVE"


def test_give_is_always_possible_and_idempotent_per_client_id(client, household_a, token_a, pet_a, medication_a):
    url = f"/api/households/{household_a.id}/pets/{pet_a.id}/medications/{medication_a.id}/give"
    # Zwei echte Gaben am selben Tag (z. B. 2x täglich) → zwei Einträge
    assert client.post(url, headers=_h(token_a)).status_code == 201
    assert client.post(url, json={}, headers=_h(token_a)).status_code == 201

    client_id = str(uuid.uuid4())
    first = client.post(url, json={"id": client_id}, headers=_h(token_a))
    retry = client.post(url, json={"id": client_id}, headers=_h(token_a))
    assert first.status_code == 201 and retry.status_code == 200
    assert first.json()["id"] == retry.json()["id"] == client_id

    log = client.get(url.replace("/give", "/log"), headers=_h(token_a)).json()
    assert len(log) == 3


def test_give_client_id_of_other_medication_conflicts(client, db, household_a, token_a, pet_a, medication_a):
    from app.models import Medication

    other = Medication(household_id=household_a.id, pet_id=pet_a.id, name="Tropfen", active=True)
    db.add(other)
    db.commit()
    base = f"/api/households/{household_a.id}/pets/{pet_a.id}/medications"
    client_id = str(uuid.uuid4())
    assert client.post(f"{base}/{medication_a.id}/give", json={"id": client_id}, headers=_h(token_a)).status_code == 201
    resp = client.post(f"{base}/{other.id}/give", json={"id": client_id}, headers=_h(token_a))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "ENTITY_ID_CONFLICT"
