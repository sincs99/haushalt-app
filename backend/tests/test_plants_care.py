"""Pflege-Intervalle (Pflanzen und Tiere): Intervall-Änderung verschiebt die Fälligkeit (PD-P4 / E-2)."""

import uuid
import zoneinfo
from datetime import date, datetime, timedelta, timezone

from app.models import PlantCareTask


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

