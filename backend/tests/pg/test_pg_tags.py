"""Tag-Scans unter Parallelität (CASA-05, CASA-18, CASA-29 Tag-Teil, PD-T1).

NFC-Leser feuern oft doppelt, Retries nach Netzfehlern sind normal: wiederholte
und parallele Scans dürfen pro Haushaltstag nur einmal etwas ändern und nie einen
Rückstand oder eine andere Periode abhaken.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.models import (
    Chore,
    ChoreAssignment,
    Pet,
    PetCareTask,
    Plant,
    PlantCareLog,
    PlantCareTask,
    Tag,
    Todo,
)
from app.routers.tags import generate_tag_token
from app.services.chore_scheduler import today_in_tz
from tests.pg.harness import run_parallel, status_codes


def _today() -> date:
    return today_in_tz("Europe/Zurich")


def _add(db, *objs):
    db.add_all(objs)
    db.commit()
    for o in objs:
        db.refresh(o)
    return objs[0] if len(objs) == 1 else objs


def _tag(db, hh, action, target_type, target_id):
    return _add(
        db,
        Tag(
            household_id=hh.id,
            token=generate_tag_token(),
            label="Chip",
            target_type=target_type,
            target_id=target_id,
            action=action,
        ),
    )


def _resolve(client, hh, tag, i=0):
    r = client.post(f"/api/tags/resolve/{tag.token}", headers=hh.headers(i))
    assert r.status_code == 200, r.text
    return r.json()


def _execute(client, hh, tag, body=None, i=0):
    return client.post(f"/api/tags/{tag.token}/execute", headers=hh.headers(i), json=body)


def _changed(results):
    return [r.json().get("changed") for r in results]


@pytest.fixture()
def chore_with_backlog(db, household):
    """Wöchentliches Ämtli, heute fällig, mit zwei offenen Terminen der Vorwochen."""
    today = _today()
    chore = _add(
        db,
        Chore(
            household_id=household.id,
            title="Bad",
            recurrence="weekly",
            weekday=today.weekday(),
            rotation_order=[str(u) for u in household.user_ids],
            next_rotation_index=0,
            anchor_date=today - timedelta(days=14),
            active=True,
        ),
    )
    backlog = _add(
        db,
        *[
            ChoreAssignment(
                household_id=household.id,
                chore_id=chore.id,
                assigned_user_id=household.user_ids[1],
                due_date=today - timedelta(days=d),
            )
            for d in (7, 14)
        ],
    )
    return chore, backlog


def test_chore_parallel_scans_complete_only_current_period(client, db, household, chore_with_backlog):
    chore, backlog = chore_with_backlog
    tag = _tag(db, household, "chore.assignment.done", "chore", chore.id)
    confirm = _resolve(client, household, tag)["confirm"]

    results = run_parallel(lambda i: _execute(client, household, tag, {"confirm": confirm}, i % 2), 4)
    assert status_codes(results) == [200] * 4
    assert sorted(_changed(results)) == [False, False, False, True]

    db.expire_all()
    done = db.query(ChoreAssignment).filter(
        ChoreAssignment.chore_id == chore.id, ChoreAssignment.completed_at.isnot(None)
    ).all()
    assert [a.due_date for a in done] == [_today()]
    assert all(db.get(ChoreAssignment, b.id).completed_at is None for b in backlog)


def test_chore_sequential_rescans_report_already_done(client, db, household, chore_with_backlog):
    chore, backlog = chore_with_backlog
    tag = _tag(db, household, "chore.assignment.done", "chore", chore.id)
    confirm = _resolve(client, household, tag)["confirm"]
    assert _execute(client, household, tag, {"confirm": confirm}).json()["changed"] is True
    for _ in range(2):
        data = _resolve(client, household, tag)
        assert data["can_execute"] is False
        assert data["reason"] == "ALREADY_DONE"
        again = _execute(client, household, tag, {"confirm": confirm})
        assert again.status_code == 200
        assert again.json()["changed"] is False
    db.expire_all()
    assert all(db.get(ChoreAssignment, b.id).completed_at is None for b in backlog)


def test_chore_execute_after_app_completion_changes_nothing(client, db, household, chore_with_backlog):
    """CASA-18 T3: resolve → (App hakt ab) → execute: kein Rückstand wird stattdessen erledigt."""
    chore, backlog = chore_with_backlog
    tag = _tag(db, household, "chore.assignment.done", "chore", chore.id)
    confirm = _resolve(client, household, tag)["confirm"]
    r = client.post(
        household.url(f"/chores/assignments/{confirm['assignment_id']}/complete"), headers=household.headers(1)
    )
    assert r.status_code == 200
    resp = _execute(client, household, tag, {"confirm": confirm})
    assert resp.status_code == 200
    assert resp.json()["changed"] is False
    db.expire_all()
    assert all(db.get(ChoreAssignment, b.id).completed_at is None for b in backlog)


def test_water_all_parallel_logs_each_task_once(client, db, household):
    today = _today()
    plants = _add(db, *[Plant(household_id=household.id, name=f"P{i}") for i in range(3)])
    _add(
        db,
        *[
            PlantCareTask(
                household_id=household.id, plant_id=p.id, care_type="water", interval_days=7, next_due_at=today
            )
            for p in plants
        ],
    )
    tag = _tag(db, household, "plant.water", "plant", None)
    confirm = _resolve(client, household, tag)["confirm"]
    assert len(confirm["task_ids"]) == 3

    results = run_parallel(lambda i: _execute(client, household, tag, {"confirm": confirm}, i % 2), 3)
    assert status_codes(results) == [200] * 3
    db.expire_all()
    assert db.query(PlantCareLog).filter(PlantCareLog.household_id == household.id).count() == 3


def test_plant_care_task_parallel_logs_once(client, db, household):
    plant = _add(db, Plant(household_id=household.id, name="Monstera"))
    task = _add(
        db,
        PlantCareTask(
            household_id=household.id, plant_id=plant.id, care_type="fertilize", interval_days=30, next_due_at=_today()
        ),
    )
    tag = _tag(db, household, "plant.care_task.done", "plant_care_task", task.id)
    results = run_parallel(lambda i: _execute(client, household, tag, None, i % 2), 3)
    assert status_codes(results) == [200] * 3
    assert sorted(_changed(results)) == [False, False, True]
    db.expire_all()
    assert db.query(PlantCareLog).filter(PlantCareLog.care_task_id == task.id).count() == 1


def test_pet_care_task_parallel_changes_once(client, db, household):
    pet = _add(db, Pet(household_id=household.id, name="Luna", species="cat"))
    task = _add(
        db,
        PetCareTask(
            household_id=household.id, pet_id=pet.id, name="Wurmkur", interval_days=90, next_due_at=_today()
        ),
    )
    tag = _tag(db, household, "pet.care_task.done", "pet_care_task", task.id)
    results = run_parallel(lambda i: _execute(client, household, tag, None, i % 2), 3)
    assert status_codes(results) == [200] * 3
    assert sorted(_changed(results)) == [False, False, True]
    db.expire_all()
    assert db.get(PetCareTask, task.id).next_due_at == _today() + timedelta(days=90)


def test_todo_done_parallel_single_event(client, db, household, emits):
    todo = _add(db, Todo(household_id=household.id, title="Müll", created_by_user_id=household.user_ids[0]))
    tag = _tag(db, household, "todo.done", "todo", todo.id)
    results = run_parallel(lambda i: _execute(client, household, tag, None, i % 2), 3)
    assert status_codes(results) == [200] * 3
    assert sorted(_changed(results)) == [False, False, True]
    updates = [c for c in emits.events("todo_updated") if c[2]["id"] == str(todo.id)]
    assert len(updates) == 1
    db.expire_all()
    first_done_at = db.get(Todo, todo.id).done_at
    assert first_done_at is not None
    assert uuid.UUID(updates[0][2]["id"]) == todo.id
