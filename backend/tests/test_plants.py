"""
Tests für das Pflanzen-Modul: CRUD, Haushalts-Scoping, Pflege-Log,
Status-Endpunkt, water-all und Foto.
"""

import uuid
import zoneinfo
from datetime import date, datetime, timedelta
from unittest.mock import patch

from app.models import Plant, PlantCareLog, PlantCareTask, StoredFile


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _today() -> date:
    # Household-Default-Timezone ist Europe/Zurich
    return datetime.now(zoneinfo.ZoneInfo("Europe/Zurich")).date()


def _base(household):
    return f"/api/households/{household.id}/plants"


def _create_task(client, household, plant, token, **payload):
    payload.setdefault("care_type", "water")
    resp = client.post(
        f"{_base(household)}/{plant.id}/care-tasks/", headers=_auth(token), json=payload
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _image_file(db, household, user) -> StoredFile:
    sf = StoredFile(
        id=uuid.uuid4(),
        household_id=household.id,
        original_name="plant.jpeg",
        mime_type="image/jpeg",
        size_bytes=100,
        storage_path=f"{household.id}/{uuid.uuid4()}.jpeg",
        uploaded_by_user_id=user.id,
    )
    db.add(sf)
    db.commit()
    db.refresh(sf)
    return sf


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_create_and_get_plant(client, household_a, token_a):
    resp = client.post(
        f"{_base(household_a)}/",
        headers=_auth(token_a),
        json={
            "name": "Ficus",
            "species": "Ficus benjamina",
            "location": "Büro",
            "notes": "Hell stellen",
            "care_notes": "Wenig Wasser im Winter",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Ficus"
    assert data["location"] == "Büro"
    assert data["care_notes"] == "Wenig Wasser im Winter"
    assert data["photo_file_id"] is None
    assert data["household_id"] == str(household_a.id)

    got = client.get(f"{_base(household_a)}/{data['id']}", headers=_auth(token_a))
    assert got.status_code == 200
    assert got.json()["id"] == data["id"]


def test_create_plant_emits_event(client, household_a, token_a, _mock_socket_emit):
    client.post(f"{_base(household_a)}/", headers=_auth(token_a), json={"name": "Kaktus"})
    assert _mock_socket_emit.call_args.args[1] == "plant_created"


def test_create_plant_requires_name(client, household_a, token_a):
    resp = client.post(f"{_base(household_a)}/", headers=_auth(token_a), json={"name": ""})
    assert resp.status_code == 422


def test_list_plants_sorted_by_name(client, household_a, token_a, plant_a):
    client.post(f"{_base(household_a)}/", headers=_auth(token_a), json={"name": "Aloe"})
    resp = client.get(f"{_base(household_a)}/", headers=_auth(token_a))
    assert resp.status_code == 200
    assert [p["name"] for p in resp.json()] == ["Aloe", "Monstera"]


def test_update_plant(client, household_a, token_a, plant_a, _mock_socket_emit):
    resp = client.patch(
        f"{_base(household_a)}/{plant_a.id}",
        headers=_auth(token_a),
        json={"location": "Balkon"},
    )
    assert resp.status_code == 200
    assert resp.json()["location"] == "Balkon"
    assert resp.json()["name"] == "Monstera"
    assert _mock_socket_emit.call_args.args[1] == "plant_updated"


def test_update_plant_name_null_rejected(client, household_a, token_a, plant_a):
    resp = client.patch(
        f"{_base(household_a)}/{plant_a.id}", headers=_auth(token_a), json={"name": None}
    )
    assert resp.status_code == 422


def test_delete_plant_cascades(client, db, household_a, token_a, plant_a, _mock_socket_emit):
    _create_task(client, household_a, plant_a, token_a)
    client.post(
        f"{_base(household_a)}/{plant_a.id}/care-tasks/{db.query(PlantCareTask).first().id}/complete",
        headers=_auth(token_a),
    )
    resp = client.delete(f"{_base(household_a)}/{plant_a.id}", headers=_auth(token_a))
    assert resp.status_code == 204
    assert _mock_socket_emit.call_args.args[1] == "plant_deleted"
    db.expire_all()
    assert db.query(Plant).count() == 0
    assert db.query(PlantCareTask).count() == 0
    assert db.query(PlantCareLog).count() == 0


# ---------------------------------------------------------------------------
# Haushalts-Scoping
# ---------------------------------------------------------------------------


def test_cross_household_list_forbidden(client, household_b, token_a, plant_b):
    resp = client.get(f"{_base(household_b)}/", headers=_auth(token_a))
    assert resp.status_code == 403


def test_cross_household_create_forbidden(client, household_b, token_a):
    resp = client.post(f"{_base(household_b)}/", headers=_auth(token_a), json={"name": "X"})
    assert resp.status_code == 403


def test_cross_household_status_and_water_all_forbidden(client, household_b, token_a):
    assert client.get(f"{_base(household_b)}/care-status", headers=_auth(token_a)).status_code == 403
    assert client.post(f"{_base(household_b)}/water-all", headers=_auth(token_a)).status_code == 403


def test_plant_of_other_household_is_404_in_own_household(
    client, household_a, token_a, plant_b
):
    """Plant-ID aus Haushalt B über den eigenen Haushalt A → 404."""
    base = f"{_base(household_a)}/{plant_b.id}"
    assert client.get(base, headers=_auth(token_a)).status_code == 404
    assert client.patch(base, headers=_auth(token_a), json={"name": "Hack"}).status_code == 404
    assert client.delete(base, headers=_auth(token_a)).status_code == 404
    assert client.get(f"{base}/care-tasks/", headers=_auth(token_a)).status_code == 404
    assert client.get(f"{base}/care-log", headers=_auth(token_a)).status_code == 404
    resp = client.post(
        f"{base}/care-tasks/", headers=_auth(token_a), json={"care_type": "water"}
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "PLANT_NOT_FOUND"


def test_cross_household_care_task_access(
    client, db, household_a, household_b, token_a, token_b, plant_a, plant_b
):
    task_b = _create_task(client, household_b, plant_b, token_b)

    # Fremder Haushalt direkt → 403
    resp = client.post(
        f"{_base(household_b)}/{plant_b.id}/care-tasks/{task_b['id']}/complete",
        headers=_auth(token_a),
    )
    assert resp.status_code == 403

    # Task von B über Pflanze A im eigenen Haushalt → 404
    for method, suffix, kwargs in (
        (client.post, "/complete", {}),
        (client.patch, "", {"json": {"interval_days": 2}}),
        (client.delete, "", {}),
    ):
        resp = method(
            f"{_base(household_a)}/{plant_a.id}/care-tasks/{task_b['id']}{suffix}",
            headers=_auth(token_a),
            **kwargs,
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "PLANT_CARE_TASK_NOT_FOUND"

    db.expire_all()
    assert db.get(PlantCareTask, uuid.UUID(task_b["id"])).last_done_at is None


def test_status_and_water_all_do_not_touch_other_household(
    client, db, household_a, household_b, token_a, token_b, plant_a, plant_b
):
    _create_task(client, household_b, plant_b, token_b, next_due_at=str(_today() - timedelta(days=2)))

    status_resp = client.get(f"{_base(household_a)}/care-status", headers=_auth(token_a))
    assert [p["plant_id"] for p in status_resp.json()] == [str(plant_a.id)]

    assert client.post(f"{_base(household_a)}/water-all", headers=_auth(token_a)).json() == []
    db.expire_all()
    assert db.query(PlantCareLog).count() == 0


# ---------------------------------------------------------------------------
# Pflegeaufgaben
# ---------------------------------------------------------------------------


def test_care_task_defaults_per_type(client, household_a, token_a, plant_a):
    expected = {"water": 7, "fertilize": 30, "repot": 365, "mist": 3, "other": 30}
    for care_type, days in expected.items():
        task = _create_task(client, household_a, plant_a, token_a, care_type=care_type)
        assert task["interval_days"] == days
        assert task["next_due_at"] == str(_today() + timedelta(days=days))
        assert task["last_done_at"] is None


def test_care_task_with_label_and_explicit_values(client, household_a, token_a, plant_a):
    task = _create_task(
        client, household_a, plant_a, token_a,
        care_type="other", label="Blätter abwischen", interval_days=14, next_due_at="2030-01-01",
    )
    assert task["label"] == "Blätter abwischen"
    assert task["interval_days"] == 14
    assert task["next_due_at"] == "2030-01-01"


def test_care_task_invalid_type_and_interval(client, household_a, token_a, plant_a):
    url = f"{_base(household_a)}/{plant_a.id}/care-tasks/"
    assert client.post(url, headers=_auth(token_a), json={"care_type": "dance"}).status_code == 422
    assert client.post(
        url, headers=_auth(token_a), json={"care_type": "water", "interval_days": 0}
    ).status_code == 422


def test_update_and_delete_care_task(client, household_a, token_a, plant_a):
    task = _create_task(client, household_a, plant_a, token_a)
    url = f"{_base(household_a)}/{plant_a.id}/care-tasks/{task['id']}"
    resp = client.patch(url, headers=_auth(token_a), json={"interval_days": 10})
    assert resp.status_code == 200
    assert resp.json()["interval_days"] == 10
    assert client.delete(url, headers=_auth(token_a)).status_code == 204
    assert client.get(f"{_base(household_a)}/{plant_a.id}/care-tasks/", headers=_auth(token_a)).json() == []


# ---------------------------------------------------------------------------
# Pflege-Log
# ---------------------------------------------------------------------------


def test_complete_sets_next_due_and_logs(
    client, household_a, token_a, user_a, plant_a, _mock_socket_emit
):
    task = _create_task(
        client, household_a, plant_a, token_a,
        interval_days=5, next_due_at=str(_today() - timedelta(days=3)),
    )
    resp = client.post(
        f"{_base(household_a)}/{plant_a.id}/care-tasks/{task['id']}/complete",
        headers=_auth(token_a),
        json={"note": "Viel Wasser"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["task"]["last_done_at"] == str(_today())
    assert data["task"]["next_due_at"] == str(_today() + timedelta(days=5))
    assert data["log"]["care_type"] == "water"
    assert data["log"]["note"] == "Viel Wasser"
    assert data["log"]["done_by_user_id"] == str(user_a.id)
    assert data["log"]["care_task_id"] == task["id"]
    assert "plant_care_logged" in [c.args[1] for c in _mock_socket_emit.call_args_list]

    log = client.get(f"{_base(household_a)}/{plant_a.id}/care-log", headers=_auth(token_a)).json()
    assert [entry["id"] for entry in log] == [data["log"]["id"]]


def test_complete_without_body_and_log_ordering(client, household_a, token_a, plant_a):
    task = _create_task(client, household_a, plant_a, token_a)
    url = f"{_base(household_a)}/{plant_a.id}/care-tasks/{task['id']}/complete"
    first = client.post(url, headers=_auth(token_a))
    assert first.status_code == 200
    assert first.json()["log"]["note"] is None
    second = client.post(url, headers=_auth(token_a), json={"note": "nochmal"})
    log = client.get(f"{_base(household_a)}/{plant_a.id}/care-log", headers=_auth(token_a)).json()
    assert [e["id"] for e in log] == [second.json()["log"]["id"], first.json()["log"]["id"]]


def test_complete_resets_notified_at(client, db, household_a, token_a, plant_a):
    task = _create_task(client, household_a, plant_a, token_a)
    row = db.get(PlantCareTask, uuid.UUID(task["id"]))
    row.notified_at = datetime.now(zoneinfo.ZoneInfo("UTC"))
    db.commit()
    client.post(
        f"{_base(household_a)}/{plant_a.id}/care-tasks/{task['id']}/complete",
        headers=_auth(token_a),
    )
    db.expire_all()
    assert db.get(PlantCareTask, uuid.UUID(task["id"])).notified_at is None


def test_log_survives_task_deletion(client, db, household_a, token_a, plant_a):
    task = _create_task(client, household_a, plant_a, token_a)
    base = f"{_base(household_a)}/{plant_a.id}/care-tasks/{task['id']}"
    client.post(f"{base}/complete", headers=_auth(token_a))
    client.delete(base, headers=_auth(token_a))
    log = client.get(f"{_base(household_a)}/{plant_a.id}/care-log", headers=_auth(token_a)).json()
    assert len(log) == 1
    assert log[0]["care_task_id"] is None
    assert log[0]["care_type"] == "water"


# ---------------------------------------------------------------------------
# Status + water-all
# ---------------------------------------------------------------------------


def test_care_status_flags(client, household_a, token_a, plant_a):
    _create_task(client, household_a, plant_a, token_a, care_type="water", next_due_at=str(_today() - timedelta(days=1)))
    _create_task(client, household_a, plant_a, token_a, care_type="fertilize", next_due_at=str(_today()))
    _create_task(client, household_a, plant_a, token_a, care_type="repot", next_due_at=str(_today() + timedelta(days=30)))
    empty = client.post(f"{_base(household_a)}/", headers=_auth(token_a), json={"name": "Aloe"}).json()

    resp = client.get(f"{_base(household_a)}/care-status", headers=_auth(token_a))
    assert resp.status_code == 200
    by_plant = {p["plant_id"]: p for p in resp.json()}

    monstera = by_plant[str(plant_a.id)]
    assert monstera["overdue"] is True
    assert monstera["due_today"] is True
    flags = {t["care_type"]: (t["due_today"], t["overdue"]) for t in monstera["tasks"]}
    assert flags == {"water": (False, True), "fertilize": (True, False), "repot": (False, False)}
    assert monstera["tasks"][0]["care_type"] == "water"  # nach Fälligkeit sortiert

    aloe = by_plant[empty["id"]]
    assert aloe["tasks"] == []
    assert aloe["due_today"] is False and aloe["overdue"] is False


def test_water_all_only_due_water_tasks(client, db, household_a, token_a, plant_a):
    other = client.post(f"{_base(household_a)}/", headers=_auth(token_a), json={"name": "Aloe"}).json()
    overdue = _create_task(client, household_a, plant_a, token_a, next_due_at=str(_today() - timedelta(days=4)))
    due_today = client.post(
        f"{_base(household_a)}/{other['id']}/care-tasks/",
        headers=_auth(token_a),
        json={"care_type": "water", "next_due_at": str(_today())},
    ).json()
    future = _create_task(client, household_a, plant_a, token_a, care_type="water", next_due_at=str(_today() + timedelta(days=2)))
    fert = _create_task(client, household_a, plant_a, token_a, care_type="fertilize", next_due_at=str(_today() - timedelta(days=1)))

    resp = client.post(f"{_base(household_a)}/water-all", headers=_auth(token_a))
    assert resp.status_code == 200
    assert {log["care_task_id"] for log in resp.json()} == {overdue["id"], due_today["id"]}
    assert all(log["care_type"] == "water" for log in resp.json())

    db.expire_all()
    assert db.get(PlantCareTask, uuid.UUID(overdue["id"])).next_due_at == _today() + timedelta(days=7)
    assert db.get(PlantCareTask, uuid.UUID(future["id"])).last_done_at is None
    assert db.get(PlantCareTask, uuid.UUID(fert["id"])).last_done_at is None

    # Zweiter Aufruf: nichts mehr fällig
    assert client.post(f"{_base(household_a)}/water-all", headers=_auth(token_a)).json() == []


def test_water_all_emits_logged_events(client, household_a, token_a, plant_a, _mock_socket_emit):
    _create_task(client, household_a, plant_a, token_a, next_due_at=str(_today()))
    _mock_socket_emit.reset_mock()
    client.post(f"{_base(household_a)}/water-all", headers=_auth(token_a))
    events = [c.args[1] for c in _mock_socket_emit.call_args_list]
    assert events.count("plant_care_logged") == 1


# ---------------------------------------------------------------------------
# Foto
# ---------------------------------------------------------------------------


def test_photo_upload_and_attach(client, household_a, token_a, plant_a):
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (50, 50), color="green").save(buf, format="PNG")
    buf.seek(0)
    with patch("app.routers.files._storage") as mock_storage:
        mock_storage.save.return_value = f"{household_a.id}/plant.jpeg"
        up = client.post(
            f"/api/households/{household_a.id}/files/",
            headers=_auth(token_a),
            files={"file": ("plant.png", buf, "image/png")},
        )
    assert up.status_code == 201
    file_id = up.json()["id"]

    resp = client.patch(
        f"{_base(household_a)}/{plant_a.id}", headers=_auth(token_a), json={"photo_file_id": file_id}
    )
    assert resp.status_code == 200
    assert resp.json()["photo_file_id"] == file_id

    # Foto ist jetzt belegt → Löschen der Datei über /files verweigert
    with patch("app.routers.files._storage"):
        blocked = client.delete(
            f"/api/households/{household_a.id}/files/{file_id}", headers=_auth(token_a)
        )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "FILE_IN_USE"


def test_photo_from_other_household_rejected(client, db, household_a, user_b, household_b, token_a, plant_a):
    sf = _image_file(db, household_b, user_b)
    resp = client.patch(
        f"{_base(household_a)}/{plant_a.id}", headers=_auth(token_a), json={"photo_file_id": str(sf.id)}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_MISMATCH"


def test_photo_non_image_rejected(client, db, household_a, user_a, token_a, plant_a):
    sf = _image_file(db, household_a, user_a)
    sf.mime_type = "application/pdf"
    db.commit()
    resp = client.patch(
        f"{_base(household_a)}/{plant_a.id}", headers=_auth(token_a), json={"photo_file_id": str(sf.id)}
    )
    assert resp.status_code == 422


def test_photo_cannot_be_shared_between_plants(client, db, household_a, user_a, token_a, plant_a):
    sf = _image_file(db, household_a, user_a)
    db.add(Plant(household_id=household_a.id, name="Anderer", photo_file_id=sf.id))
    db.commit()
    resp = client.patch(
        f"{_base(household_a)}/{plant_a.id}", headers=_auth(token_a), json={"photo_file_id": str(sf.id)}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


def test_photo_cannot_use_pet_photo(client, db, household_a, user_a, token_a, plant_a, pet_a):
    sf = _image_file(db, household_a, user_a)
    pet_a.photo_file_id = sf.id
    db.commit()
    resp = client.patch(
        f"{_base(household_a)}/{plant_a.id}", headers=_auth(token_a), json={"photo_file_id": str(sf.id)}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "FILE_IN_USE"


def test_delete_plant_removes_own_photo(client, db, household_a, user_a, token_a, plant_a):
    sf = _image_file(db, household_a, user_a)
    file_id, path = sf.id, sf.storage_path
    plant_a.photo_file_id = file_id
    db.commit()

    with patch("app.routers.files._storage") as mock_storage:
        resp = client.delete(f"{_base(household_a)}/{plant_a.id}", headers=_auth(token_a))
    assert resp.status_code == 204
    mock_storage.delete.assert_called_once_with(path)
    db.expire_all()
    assert db.get(StoredFile, file_id) is None


def test_orphan_cleanup_keeps_plant_photo(db, household_a, user_a, plant_a):
    from datetime import timezone

    from app.routers.files import ORPHAN_FILE_GRACE, delete_orphan_files

    old = datetime.now(timezone.utc) - ORPHAN_FILE_GRACE - timedelta(hours=1)
    sf = _image_file(db, household_a, user_a)
    sf.created_at = old
    plant_a.photo_file_id = sf.id
    db.commit()

    with patch("app.routers.files._storage"):
        assert delete_orphan_files(db) == 0
    assert db.get(StoredFile, sf.id) is not None
