"""Pflegeaufgaben: Intervall-Änderung (PD-P4 / E-2) und einmal pro Haushaltstag erledigen (CASA-29)."""

import uuid
import zoneinfo
from datetime import date, datetime, timedelta, timezone

from app.models import PlantCareLog, PlantCareTask


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _today() -> date:
    return datetime.now(zoneinfo.ZoneInfo("Europe/Zurich")).date()


def _task(db, plant, **kw):
    kw.setdefault("care_type", "water")
    kw.setdefault("interval_days", 7)
    kw.setdefault("next_due_at", _today())
    task = PlantCareTask(id=uuid.uuid4(), household_id=plant.household_id, plant_id=plant.id, **kw)
    db.add(task)
    db.commit()
    return task


def _url(plant, task=None, suffix=""):
    base = f"/api/households/{plant.household_id}/plants"
    if task is None:
        return base + suffix
    return f"{base}/{plant.id}/care-tasks/{task.id}{suffix}"


# ---------------------------------------------------------------------------
# PD-P4 / E-2: Intervall ändern verschiebt die Fälligkeit
# ---------------------------------------------------------------------------


def test_interval_change_recomputes_next_due_from_last_done(client, db, household_a, token_a, plant_a):
    last = _today() - timedelta(days=3)
    task = _task(db, plant_a, interval_days=30, last_done_at=last, next_due_at=last + timedelta(days=30),
                 notified_at=datetime.now(timezone.utc))
    resp = client.patch(_url(plant_a, task), json={"interval_days": 7}, headers=_h(token_a))
    assert resp.status_code == 200
    assert resp.json()["next_due_at"] == str(last + timedelta(days=7))
    assert resp.json()["notified_at"] is None


def test_interval_change_without_history_counts_from_today(client, db, household_a, token_a, plant_a):
    task = _task(db, plant_a, interval_days=30, next_due_at=_today() + timedelta(days=25))
    resp = client.patch(_url(plant_a, task), json={"interval_days": 10}, headers=_h(token_a))
    assert resp.json()["next_due_at"] == str(_today() + timedelta(days=10))


def test_explicit_next_due_wins_and_same_interval_keeps_due(client, db, household_a, token_a, plant_a):
    task = _task(db, plant_a, interval_days=30, next_due_at=_today() + timedelta(days=25))
    explicit = _today() + timedelta(days=2)
    resp = client.patch(_url(plant_a, task), json={"interval_days": 10, "next_due_at": str(explicit)},
                        headers=_h(token_a))
    assert resp.json()["next_due_at"] == str(explicit)
    # Unverändertes Intervall (z. B. Label-Änderung) → Fälligkeit bleibt
    resp = client.patch(_url(plant_a, task), json={"interval_days": 10, "label": "x"}, headers=_h(token_a))
    assert resp.json()["next_due_at"] == str(explicit)


def test_pet_care_interval_change_recomputes_next_due(client, db, household_a, token_a, pet_a):
    from app.models import PetCareTask

    last = _today() - timedelta(days=5)
    task = PetCareTask(household_id=household_a.id, pet_id=pet_a.id, name="Wurmkur", interval_days=90,
                       last_done_at=last, next_due_at=last + timedelta(days=90),
                       notified_at=datetime.now(timezone.utc))
    db.add(task)
    db.commit()
    resp = client.patch(f"/api/households/{household_a.id}/pets/{pet_a.id}/care-tasks/{task.id}",
                        json={"interval_days": 30}, headers=_h(token_a))
    assert resp.status_code == 200
    assert resp.json()["next_due_at"] == str(last + timedelta(days=30))
    assert resp.json()["notified_at"] is None



# ---------------------------------------------------------------------------
# CASA-29: pro Aufgabe höchstens ein Log pro Haushaltstag
# ---------------------------------------------------------------------------


def test_complete_twice_same_day_logs_once(client, db, household_a, token_a, plant_a):
    task = _task(db, plant_a, interval_days=5)
    first = client.post(_url(plant_a, task, "/complete"), headers=_h(token_a))
    assert first.status_code == 200
    assert first.json()["changed"] is True
    assert first.json()["log"] is not None

    second = client.post(_url(plant_a, task, "/complete"), json={"note": "nochmal"}, headers=_h(token_a))
    assert second.status_code == 200
    assert second.json()["changed"] is False
    assert second.json()["log"] is None
    assert second.json()["task"]["next_due_at"] == str(_today() + timedelta(days=5))
    assert db.query(PlantCareLog).filter_by(care_task_id=task.id).count() == 1


def test_tag_scans_on_same_day_do_not_crash_or_log_twice(client, db, household_a, token_a, plant_a):
    """Tags rufen den plants-Router direkt auf: zweiter Scan am selben Tag → changed=false."""
    from app.models import Tag
    from app.routers.tags import generate_tag_token

    task = _task(db, plant_a)
    tags = [
        Tag(household_id=household_a.id, token=generate_tag_token(), label="W", target_type="plant",
            target_id=plant_a.id, action="plant.water", enabled=True),
        Tag(household_id=household_a.id, token=generate_tag_token(), label="C", target_type="plant_care_task",
            target_id=task.id, action="plant.care_task.done", enabled=True),
    ]
    db.add_all(tags)
    db.commit()
    first = client.post(f"/api/tags/{tags[0].token}/execute", headers=_h(token_a))
    assert first.status_code == 200 and first.json()["changed"] is True
    for tag in tags:
        again = client.post(f"/api/tags/{tag.token}/execute", headers=_h(token_a))
        assert again.status_code == 200, again.text
        assert again.json()["changed"] is False
    assert db.query(PlantCareLog).count() == 1


def test_water_all_twice_logs_once(client, db, household_a, token_a, plant_a):
    _task(db, plant_a, next_due_at=_today() - timedelta(days=1))
    first = client.post(_url(plant_a, suffix="/water-all"), headers=_h(token_a)).json()
    second = client.post(_url(plant_a, suffix="/water-all"), headers=_h(token_a)).json()
    assert len(first) == 1 and second == []
    assert db.query(PlantCareLog).count() == 1
