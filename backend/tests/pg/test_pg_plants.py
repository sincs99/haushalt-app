"""Pflanzen auf PostgreSQL: parallele Erledigung / „Alle giessen“ (CASA-29)."""

import uuid
from datetime import timedelta

from app.models import Plant, PlantCareLog, PlantCareTask
from app.routers.plants import _get_household_today
from tests.pg.harness import run_parallel, status_codes


def _setup(db, hh, n_plants=5):
    today = _get_household_today(db, hh.id)
    plants, tasks = [], []
    for i in range(n_plants):
        plant = Plant(id=uuid.uuid4(), household_id=hh.id, name=f"P{i}")
        db.add(plant)
        db.flush()
        task = PlantCareTask(
            id=uuid.uuid4(), household_id=hh.id, plant_id=plant.id, care_type="water",
            interval_days=7, next_due_at=today - timedelta(days=1),
        )
        db.add(task)
        plants.append(plant)
        tasks.append(task)
    db.commit()
    return today, plants, tasks


def test_parallel_water_all_logs_each_task_once(client, household, db):
    """Vorher: 2× water-all parallel → 10 Logs für 5 Pflanzen."""
    _, plants, _ = _setup(db, household)

    results = run_parallel(
        lambda i: client.post(household.url("/plants/water-all"), headers=household.headers(i)), 2
    )
    assert status_codes(results) == [200, 200]
    assert sum(len(r.json()) for r in results) == len(plants)
    db.expire_all()
    assert db.query(PlantCareLog).filter(PlantCareLog.household_id == household.id).count() == len(plants)


def test_parallel_complete_same_task_logs_once(client, household, db):
    today, plants, tasks = _setup(db, household, n_plants=1)
    url = household.url(f"/plants/{plants[0].id}/care-tasks/{tasks[0].id}/complete")

    results = run_parallel(lambda i: client.post(url, headers=household.headers(i % 2)), 4)
    assert status_codes(results) == [200] * 4
    assert [r.json()["changed"] for r in results].count(True) == 1
    db.expire_all()
    assert db.query(PlantCareLog).filter(PlantCareLog.care_task_id == tasks[0].id).count() == 1
    task = db.get(PlantCareTask, tasks[0].id)
    assert task.last_done_at == today
    assert task.next_due_at == today + timedelta(days=7)


def test_parallel_complete_and_water_all(client, household, db):
    _, plants, tasks = _setup(db, household, n_plants=3)

    def act(i):
        if i == 0:
            return client.post(household.url("/plants/water-all"), headers=household.headers(0))
        return client.post(
            household.url(f"/plants/{plants[0].id}/care-tasks/{tasks[0].id}/complete"),
            headers=household.headers(1),
        )

    results = run_parallel(act, 2)
    assert status_codes(results) == [200, 200]
    db.expire_all()
    assert db.query(PlantCareLog).filter(PlantCareLog.household_id == household.id).count() == 3
