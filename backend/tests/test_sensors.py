"""
Raumklima: Schreib-Schlüssel, Messwerte liefern, Sensoren und Verlauf lesen.
"""

from datetime import datetime, timedelta, timezone

from app.models import HouseholdMember, SensorDevice, SensorIngestToken, SensorReading
from app.routers import sensors


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _url(household, suffix=""):
    return f"/api/households/{household.id}/sensors{suffix}"


def _create_key(client, household, token):
    r = client.post(_url(household, "/ingest-token"), headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _ingest(client, key, *readings):
    return client.post("/api/sensors/ingest", headers=_auth(key), json={"readings": list(readings)})


# ── Schlüssel ──


def test_key_status_without_key(client, household_a, token_a):
    r = client.get(_url(household_a, "/ingest-token"), headers=_auth(token_a))
    assert r.status_code == 200
    assert r.json() == {"exists": False, "token_prefix": None, "created_at": None, "last_used_at": None}


def test_create_key_stores_only_hash(client, db, household_a, token_a):
    plain = _create_key(client, household_a, token_a)
    assert plain.startswith("hs_") and len(plain) > 40

    row = db.query(SensorIngestToken).one()
    assert row.household_id == household_a.id
    assert plain not in (row.token_hash, row.token_prefix)
    assert plain.startswith(row.token_prefix)


def test_recreate_replaces_old_key(client, db, household_a, token_a):
    old = _create_key(client, household_a, token_a)
    new = _create_key(client, household_a, token_a)
    assert db.query(SensorIngestToken).count() == 1
    reading = {"device_id": "t1", "temperature": 20}
    assert _ingest(client, old, reading).status_code == 401
    assert _ingest(client, new, reading).status_code == 200


def test_revoke_key(client, household_a, token_a):
    plain = _create_key(client, household_a, token_a)
    assert client.delete(_url(household_a, "/ingest-token"), headers=_auth(token_a)).status_code == 204
    assert _ingest(client, plain, {"device_id": "t1", "temperature": 20}).status_code == 401
    # Idempotent
    assert client.delete(_url(household_a, "/ingest-token"), headers=_auth(token_a)).status_code == 204


def test_key_management_requires_admin(client, db, household_a, user_a, token_a):
    db.query(HouseholdMember).filter_by(household_id=household_a.id, user_id=user_a.id).update({"role": "member"})
    db.commit()
    assert client.post(_url(household_a, "/ingest-token"), headers=_auth(token_a)).status_code == 403
    assert client.delete(_url(household_a, "/ingest-token"), headers=_auth(token_a)).status_code == 403
    # Status dürfen alle Mitglieder sehen
    assert client.get(_url(household_a, "/ingest-token"), headers=_auth(token_a)).status_code == 200


def test_key_management_requires_membership(client, household_a, token_b):
    assert client.post(_url(household_a, "/ingest-token"), headers=_auth(token_b)).status_code == 403
    assert client.get(_url(household_a, "/ingest-token"), headers=_auth(token_b)).status_code == 403


# ── Messwerte liefern ──


def test_ingest_rejects_missing_or_wrong_keys(client, household_a, token_a):
    body = {"readings": [{"device_id": "t1", "temperature": 20}]}
    assert client.post("/api/sensors/ingest", json=body).status_code == 401
    assert client.post("/api/sensors/ingest", json=body, headers=_auth("hs_wrong")).status_code == 401
    # Ein normales Login-Token ist kein Sensor-Schlüssel
    r = client.post("/api/sensors/ingest", json=body, headers=_auth(token_a))
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "SENSOR_TOKEN_INVALID"


def test_sensor_key_cannot_use_normal_api(client, household_a, token_a):
    plain = _create_key(client, household_a, token_a)
    assert client.get(_url(household_a), headers=_auth(plain)).status_code == 401


def test_ingest_creates_device_and_history(client, db, household_a, token_a):
    key = _create_key(client, household_a, token_a)
    r = _ingest(client, key, {"device_id": "0xa4c1", "name": "Wohnzimmer", "temperature": 21.4, "humidity": 48, "battery": 87})
    assert r.status_code == 200
    assert r.json() == {"accepted": 1, "rejected": []}

    devices = client.get(_url(household_a), headers=_auth(token_a)).json()
    assert len(devices) == 1
    device = devices[0]
    assert device["external_id"] == "0xa4c1"
    assert device["name"] == "Wohnzimmer"
    assert (device["temperature"], device["humidity"], device["battery"]) == (21.4, 48, 87)
    assert device["last_seen_at"] is not None
    assert db.query(SensorReading).count() == 1
    assert db.query(SensorIngestToken).one().last_used_at is not None


def test_ingest_without_name_uses_device_id(client, household_a, token_a):
    key = _create_key(client, household_a, token_a)
    _ingest(client, key, {"device_id": "kueche", "humidity": 55})
    assert client.get(_url(household_a), headers=_auth(token_a)).json()[0]["name"] == "kueche"


def test_partial_reading_keeps_other_values_and_app_name(client, household_a, token_a):
    key = _create_key(client, household_a, token_a)
    _ingest(client, key, {"device_id": "t1", "name": "Sensor", "temperature": 20, "humidity": 50})
    device_id = client.get(_url(household_a), headers=_auth(token_a)).json()[0]["id"]
    client.patch(_url(household_a, f"/{device_id}"), headers=_auth(token_a), json={"name": "Bad", "room": "Bad"})

    _ingest(client, key, {"device_id": "t1", "name": "Sensor", "temperature": 22.5})
    device = client.get(_url(household_a), headers=_auth(token_a)).json()[0]
    assert device["temperature"] == 22.5
    assert device["humidity"] == 50
    assert (device["name"], device["room"]) == ("Bad", "Bad")


def test_history_is_thinned(client, db, household_a, token_a):
    """Zwei Lieferungen kurz nacheinander: Stand aktuell, aber nur ein Verlaufseintrag."""
    key = _create_key(client, household_a, token_a)
    _ingest(client, key, {"device_id": "t1", "temperature": 20})
    _ingest(client, key, {"device_id": "t1", "temperature": 21})
    assert db.query(SensorReading).count() == 1
    assert db.query(SensorDevice).one().temperature == 21

    # Nach Ablauf des Intervalls entsteht der nächste Eintrag
    device = db.query(SensorDevice).one()
    device.last_logged_at = datetime.now(timezone.utc) - sensors.HISTORY_INTERVAL - timedelta(seconds=1)
    db.commit()
    _ingest(client, key, {"device_id": "t1", "temperature": 22})
    assert db.query(SensorReading).count() == 2


def test_old_history_is_pruned(client, db, household_a, token_a):
    key = _create_key(client, household_a, token_a)
    _ingest(client, key, {"device_id": "t1", "temperature": 20})
    device = db.query(SensorDevice).one()
    now = datetime.now(timezone.utc)
    db.add(SensorReading(device_id=device.id, recorded_at=now - sensors.HISTORY_RETENTION - timedelta(days=1), temperature=5))
    device.last_logged_at = now - timedelta(hours=1)
    db.commit()

    _ingest(client, key, {"device_id": "t1", "temperature": 21})
    temperatures = sorted(r.temperature for r in db.query(SensorReading).all())
    assert temperatures == [20, 21]


def test_battery_only_reading_adds_no_history(client, db, household_a, token_a):
    key = _create_key(client, household_a, token_a)
    assert _ingest(client, key, {"device_id": "t1", "battery": 90}).status_code == 200
    assert db.query(SensorDevice).one().battery == 90
    assert db.query(SensorReading).count() == 0


def test_ingest_validation(client, household_a, token_a):
    key = _create_key(client, household_a, token_a)
    assert _ingest(client, key).status_code == 422  # leer
    assert _ingest(client, key, {"device_id": "t1"}).status_code == 422  # kein Wert
    assert _ingest(client, key, {"device_id": " ", "temperature": 20}).status_code == 422
    assert _ingest(client, key, {"device_id": "t1", "temperature": 500}).status_code == 422
    assert _ingest(client, key, {"device_id": "t1", "humidity": 101}).status_code == 422
    too_many = [{"device_id": f"t{i}", "temperature": 20} for i in range(sensors.MAX_READINGS_PER_REQUEST + 1)]
    assert _ingest(client, key, *too_many).status_code == 422


def test_device_limit(client, db, household_a, token_a, monkeypatch):
    monkeypatch.setattr(sensors, "MAX_DEVICES_PER_HOUSEHOLD", 2)
    key = _create_key(client, household_a, token_a)
    r = _ingest(client, key, *[{"device_id": f"t{i}", "temperature": 20} for i in range(3)])
    assert r.status_code == 200
    assert r.json() == {"accepted": 2, "rejected": ["t2"]}
    assert db.query(SensorDevice).count() == 2
    # Bekannte Geräte liefern weiter
    assert _ingest(client, key, {"device_id": "t0", "temperature": 23}).json()["accepted"] == 1


def test_ingest_emits_update(client, household_a, token_a, _mock_socket_emit):
    key = _create_key(client, household_a, token_a)
    _ingest(client, key, {"device_id": "t1", "temperature": 20})
    args = _mock_socket_emit.call_args.args
    assert args[0] == household_a.id
    assert args[1] == "sensor_updated"
    assert args[2]["temperature"] == 20


# ── Sensoren lesen und verwalten ──


def test_sensors_are_household_scoped(client, household_a, household_b, token_a, token_b):
    key = _create_key(client, household_a, token_a)
    _ingest(client, key, {"device_id": "t1", "temperature": 20})
    device_id = client.get(_url(household_a), headers=_auth(token_a)).json()[0]["id"]

    assert client.get(_url(household_a), headers=_auth(token_b)).status_code == 403
    assert client.get(_url(household_b), headers=_auth(token_b)).json() == []
    # Fremdes Gerät über den eigenen Haushalt ansprechen
    for call in (
        lambda: client.patch(_url(household_b, f"/{device_id}"), headers=_auth(token_b), json={"name": "x"}),
        lambda: client.delete(_url(household_b, f"/{device_id}"), headers=_auth(token_b)),
        lambda: client.get(_url(household_b, f"/{device_id}/readings"), headers=_auth(token_b)),
    ):
        r = call()
        assert r.status_code == 404
        assert r.json()["detail"]["code"] == "SENSOR_NOT_FOUND"


def test_same_device_id_in_two_households(client, db, household_a, household_b, user_b, token_a, token_b):
    db.query(HouseholdMember).filter_by(household_id=household_b.id, user_id=user_b.id).update({"role": "admin"})
    db.commit()
    key_a = _create_key(client, household_a, token_a)
    key_b = _create_key(client, household_b, token_b)
    _ingest(client, key_a, {"device_id": "t1", "temperature": 20})
    _ingest(client, key_b, {"device_id": "t1", "temperature": 5})
    assert client.get(_url(household_a), headers=_auth(token_a)).json()[0]["temperature"] == 20
    assert client.get(_url(household_b), headers=_auth(token_b)).json()[0]["temperature"] == 5


def test_update_validation(client, household_a, token_a):
    key = _create_key(client, household_a, token_a)
    _ingest(client, key, {"device_id": "t1", "temperature": 20})
    device_id = client.get(_url(household_a), headers=_auth(token_a)).json()[0]["id"]
    url = _url(household_a, f"/{device_id}")
    assert client.patch(url, headers=_auth(token_a), json={"name": "  "}).status_code == 422
    assert client.patch(url, headers=_auth(token_a), json={"name": None}).status_code == 422
    r = client.patch(url, headers=_auth(token_a), json={"room": "  "})
    assert r.status_code == 200 and r.json()["room"] is None


def test_delete_removes_history(client, db, household_a, token_a):
    key = _create_key(client, household_a, token_a)
    _ingest(client, key, {"device_id": "t1", "temperature": 20})
    device_id = client.get(_url(household_a), headers=_auth(token_a)).json()[0]["id"]
    assert client.delete(_url(household_a, f"/{device_id}"), headers=_auth(token_a)).status_code == 204
    assert db.query(SensorDevice).count() == 0
    assert db.query(SensorReading).count() == 0


def test_readings_window_and_hourly_means(client, db, household_a, token_a):
    key = _create_key(client, household_a, token_a)
    _ingest(client, key, {"device_id": "t1", "temperature": 20, "humidity": 40})
    device = db.query(SensorDevice).one()
    db.query(SensorReading).delete()
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=30)
    db.add_all([
        SensorReading(device_id=device.id, recorded_at=base + timedelta(minutes=10), temperature=20, humidity=40),
        SensorReading(device_id=device.id, recorded_at=base + timedelta(minutes=40), temperature=22, humidity=50),
        SensorReading(device_id=device.id, recorded_at=base + timedelta(hours=29), temperature=18, humidity=None),
    ])
    db.commit()
    url = _url(household_a, f"/{device.id}/readings")

    day = client.get(url, headers=_auth(token_a), params={"hours": 24}).json()
    assert [p["temperature"] for p in day] == [18]

    week = client.get(url, headers=_auth(token_a), params={"hours": 168}).json()
    assert [(p["temperature"], p["humidity"]) for p in week] == [(21, 45), (18, None)]

    assert client.get(url, headers=_auth(token_a), params={"hours": 0}).status_code == 422
