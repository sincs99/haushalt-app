"""Haustiere auf PostgreSQL: Füttern-Races (CASA-13) und Medikamentengabe (CASA-14)."""

import uuid

from app.models import FeedingLog
from tests.pg.harness import run_parallel, status_codes


def _create_pets(client, hh, names):
    return [
        client.post(hh.url("/pets/"), json={"name": n}, headers=hh.headers()).json()["id"]
        for n in names
    ]


def test_feed_all_racing_single_feeding_feeds_every_pet(client, household, db):
    """CASA-13: „Alle gefüttert“ parallel zu einer Einzelfütterung.

    Vorher: IntegrityError → Rollback der ganzen Transaktion → ``[]`` und nur das
    eine Tier gefüttert. Jetzt: jedes Tier ist danach gefüttert und feed-all meldet
    genau die Fütterungen, die es selbst angelegt hat.
    """
    pets = _create_pets(client, household, ["Mia", "Leo", "Nemo", "Rex"])

    for trial in range(10):
        slot = "morning" if trial % 2 == 0 else "evening"

        def act(i, slot=slot):
            if i == 0:
                return client.post(
                    household.url(f"/pets/{pets[0]}/feedings"),
                    json={"slot": slot},
                    headers=household.headers(0),
                )
            return client.post(
                household.url("/pets/feed-all"), json={"slot": slot}, headers=household.headers(1)
            )

        single, feed_all = run_parallel(act, 2)
        assert single.status_code in (201, 409), single.text
        assert feed_all.status_code == 200, feed_all.text

        db.expire_all()
        rows = (
            db.query(FeedingLog)
            .filter(FeedingLog.household_id == household.id, FeedingLog.slot == slot)
            .all()
        )
        assert {str(r.pet_id) for r in rows} == set(pets), f"trial {trial}: not all pets fed"
        by_ben = {str(r.id) for r in rows if r.fed_by_user_id == household.user_ids[1]}
        assert {f["id"] for f in feed_all.json()} == by_ben

        # Aufräumen für den nächsten Durchgang
        db.query(FeedingLog).filter(
            FeedingLog.household_id == household.id, FeedingLog.slot == slot
        ).delete()
        db.commit()


def test_feed_all_parallel_feed_all_never_duplicates(client, household, db):
    """Zwei „Alle gefüttert“ gleichzeitig: jedes Tier genau einmal, kein 500."""
    pets = _create_pets(client, household, ["A", "B", "C"])

    results = run_parallel(
        lambda i: client.post(
            household.url("/pets/feed-all"), json={"slot": "evening"}, headers=household.headers(i)
        ),
        2,
    )
    assert status_codes(results) == [200, 200]
    returned = [f["pet_id"] for r in results for f in r.json()]
    assert sorted(returned) == sorted(pets)
    db.expire_all()
    assert (
        db.query(FeedingLog)
        .filter(FeedingLog.household_id == household.id, FeedingLog.slot == "evening")
        .count()
        == 3
    )



def test_parallel_give_with_same_client_id_logs_once(client, household, db):
    """CASA-14: dieselbe Gabe von zwei Geräten/Retries (gleiche Client-ID) → ein Log-Eintrag."""
    from app.models import MedicationLog

    pet = _create_pets(client, household, ["Mia"])[0]
    med = client.post(
        household.url(f"/pets/{pet}/medications"), json={"name": "Antibiotikum"}, headers=household.headers()
    ).json()
    client_id = str(uuid.uuid4())

    results = run_parallel(
        lambda i: client.post(
            household.url(f"/pets/{pet}/medications/{med['id']}/give"),
            json={"id": client_id},
            headers=household.headers(0),
        ),
        4,
    )
    codes = status_codes(results)
    assert 500 not in codes, codes
    assert set(codes) <= {200, 201}, codes
    assert {r.json()["id"] for r in results} == {client_id}
    db.expire_all()
    assert db.query(MedicationLog).filter(MedicationLog.medication_id == uuid.UUID(med["id"])).count() == 1
