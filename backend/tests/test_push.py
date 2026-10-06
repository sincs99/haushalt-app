"""
Tests für Web Push: Subscription-API (inkl. SSRF-Allowlist) und Scheduler-Verarbeitung.

webpush() wird gemockt — es werden nie echte HTTP-Requests gesendet.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from pywebpush import WebPushException

from app.core.config import settings
from app.models import PetCareTask, PlantCareTask, PushSubscription, TodoReminder
from app.services import push_service

FCM = "https://fcm.googleapis.com/fcm/send/"


@pytest.fixture()
def push_on(monkeypatch):
    monkeypatch.setattr(settings, "vapid_public_key", "BPublicKeyForTests")
    monkeypatch.setattr(settings, "vapid_private_key", "private-key-for-tests")


@pytest.fixture()
def mock_webpush():
    with patch("app.services.push_service.webpush") as m:
        yield m


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _sub_body(endpoint=FCM + "abc", locale="de"):
    return {"endpoint": endpoint, "keys": {"p256dh": "p256", "auth": "authsecret"}, "locale": locale}


def _add_sub(db, user, endpoint=None, locale="de"):
    sub = PushSubscription(
        user_id=user.id, endpoint=endpoint or FCM + uuid.uuid4().hex,
        p256dh="p256", auth="authsecret", locale=locale,
    )
    db.add(sub)
    db.commit()
    return sub


def _payloads(mock):
    import json
    return [json.loads(c.kwargs["data"]) for c in mock.call_args_list]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def test_config_disabled_by_default(client, token_a):
    resp = client.get("/api/push/config", headers=_auth(token_a))
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False, "public_key": None}


def test_config_enabled(client, token_a, push_on):
    resp = client.get("/api/push/config", headers=_auth(token_a))
    assert resp.json() == {"enabled": True, "public_key": "BPublicKeyForTests"}


def test_config_requires_auth(client):
    assert client.get("/api/push/config").status_code == 401


# ---------------------------------------------------------------------------
# Subscribe / Unsubscribe
# ---------------------------------------------------------------------------
def test_subscribe_disabled_503(client, token_a):
    resp = client.post("/api/push/subscriptions", headers=_auth(token_a), json=_sub_body())
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "PUSH_DISABLED"


def test_subscribe_creates_row(client, db, token_a, user_a, push_on):
    resp = client.post("/api/push/subscriptions", headers=_auth(token_a), json=_sub_body(locale="en"))
    assert resp.status_code == 204
    sub = db.query(PushSubscription).one()
    assert sub.user_id == user_a.id
    assert sub.locale == "en"


def test_subscribe_is_idempotent_and_rebinds_user(client, db, token_a, token_b, user_b, push_on):
    client.post("/api/push/subscriptions", headers=_auth(token_a), json=_sub_body())
    client.post("/api/push/subscriptions", headers=_auth(token_b), json=_sub_body())
    subs = db.query(PushSubscription).all()
    assert len(subs) == 1
    db.refresh(subs[0])
    assert subs[0].user_id == user_b.id


def test_subscribe_unknown_locale_falls_back(client, db, token_a, push_on):
    client.post("/api/push/subscriptions", headers=_auth(token_a), json=_sub_body(locale="xx"))
    assert db.query(PushSubscription).one().locale == "de"


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/abc",          # kein https
    "https://backend:8000/api/health",                 # interner Host
    "https://127.0.0.1/x",
    "https://evil.example.com/push",
    "https://fcm.googleapis.com.evil.com/x",           # Suffix-Trick
    "https://evilfcm.googleapis.com.attacker.io/x",
    "not a url",
])
def test_subscribe_rejects_disallowed_endpoints(client, db, token_a, push_on, endpoint):
    resp = client.post("/api/push/subscriptions", headers=_auth(token_a), json=_sub_body(endpoint))
    assert resp.status_code == 422
    assert db.query(PushSubscription).count() == 0


@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/abc",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
    "https://web.push.apple.com/abc",
    "https://wns2-am3p.notify.windows.com/w/?token=abc",
])
def test_allowed_endpoints(endpoint):
    assert push_service.is_allowed_endpoint(endpoint)


def test_unsubscribe_only_own(client, db, token_a, token_b, user_a, push_on):
    sub = _add_sub(db, user_a)
    # Fremder User kann nicht abmelden
    resp = client.request("DELETE", "/api/push/subscriptions", headers=_auth(token_b), json={"endpoint": sub.endpoint})
    assert resp.status_code == 204
    assert db.query(PushSubscription).count() == 1
    # Eigener schon
    resp = client.request("DELETE", "/api/push/subscriptions", headers=_auth(token_a), json={"endpoint": sub.endpoint})
    assert resp.status_code == 204
    assert db.query(PushSubscription).count() == 0


def test_test_endpoint_sends_to_own_devices(client, db, token_a, user_a, user_b, push_on, mock_webpush):
    _add_sub(db, user_a)
    _add_sub(db, user_a, locale="en")
    _add_sub(db, user_b)
    resp = client.post("/api/push/test", headers=_auth(token_a))
    assert resp.status_code == 200
    assert resp.json() == {"sent": 2}
    titles = sorted(p["title"] for p in _payloads(mock_webpush))
    assert titles == ["Benachrichtigungen aktiv", "Notifications enabled"]


# ---------------------------------------------------------------------------
# Scheduler: Todo-Reminders
# ---------------------------------------------------------------------------
def _reminder(db, todo, remind_at):
    r = TodoReminder(household_id=todo.household_id, todo_id=todo.id, remind_at=remind_at)
    db.add(r)
    db.commit()
    return r


def test_due_reminder_sent_once_to_all_members(db, todo_a, user_a, user_a2, user_b, mock_webpush):
    now = datetime.now(timezone.utc)
    _add_sub(db, user_a)
    _add_sub(db, user_a2)
    _add_sub(db, user_b)  # anderer Haushalt
    r = _reminder(db, todo_a, now - timedelta(minutes=1))

    assert push_service.process_todo_reminders(db, now) == 2
    payload = _payloads(mock_webpush)[0]
    assert payload["body"] == "Küche putzen"
    assert payload["url"] == "/todos"
    db.refresh(r)
    assert r.notified_at is not None

    # Zweiter Lauf: nichts mehr
    mock_webpush.reset_mock()
    assert push_service.process_todo_reminders(db, now) == 0
    mock_webpush.assert_not_called()


def test_reminder_goes_only_to_assignee(db, todo_a, user_a, user_a2, mock_webpush):
    now = datetime.now(timezone.utc)
    _add_sub(db, user_a)
    sub2 = _add_sub(db, user_a2)
    todo_a.assigned_to_user_id = user_a2.id
    db.commit()
    _reminder(db, todo_a, now)

    assert push_service.process_todo_reminders(db, now) == 1
    assert mock_webpush.call_args.kwargs["subscription_info"]["endpoint"] == sub2.endpoint


def test_future_reminder_not_sent(db, todo_a, user_a, mock_webpush):
    now = datetime.now(timezone.utc)
    _add_sub(db, user_a)
    r = _reminder(db, todo_a, now + timedelta(minutes=5))
    assert push_service.process_todo_reminders(db, now) == 0
    db.refresh(r)
    assert r.notified_at is None


def test_done_and_stale_reminders_claimed_but_not_sent(db, todo_a, user_a, mock_webpush):
    now = datetime.now(timezone.utc)
    _add_sub(db, user_a)
    stale = _reminder(db, todo_a, now - timedelta(days=2))
    assert push_service.process_todo_reminders(db, now) == 0
    db.refresh(stale)
    assert stale.notified_at is not None

    todo_a.is_done = True
    db.commit()
    done = _reminder(db, todo_a, now)
    assert push_service.process_todo_reminders(db, now) == 0
    db.refresh(done)
    assert done.notified_at is not None
    mock_webpush.assert_not_called()


def test_expired_subscription_is_removed(db, todo_a, user_a, mock_webpush):
    now = datetime.now(timezone.utc)
    _add_sub(db, user_a)
    mock_webpush.side_effect = WebPushException("gone", response=MagicMock(status_code=410))
    _reminder(db, todo_a, now)

    assert push_service.process_todo_reminders(db, now) == 0
    assert db.query(PushSubscription).count() == 0


def test_transient_error_keeps_subscription(db, todo_a, user_a, mock_webpush):
    now = datetime.now(timezone.utc)
    _add_sub(db, user_a)
    mock_webpush.side_effect = WebPushException("boom", response=MagicMock(status_code=500))
    _reminder(db, todo_a, now)

    assert push_service.process_todo_reminders(db, now) == 0
    assert db.query(PushSubscription).count() == 1


# ---------------------------------------------------------------------------
# Scheduler: Tierpflege
# ---------------------------------------------------------------------------
def _care_task(db, pet, due: date):
    t = PetCareTask(household_id=pet.household_id, pet_id=pet.id, name="Krallen schneiden", interval_days=14, next_due_at=due)
    db.add(t)
    db.commit()
    return t


def test_pet_care_waits_for_morning(db, household_a, pet_a, user_a, mock_webpush):
    household_a.timezone = "Europe/Zurich"
    db.commit()
    _add_sub(db, user_a)
    task = _care_task(db, pet_a, date(2026, 9, 29))

    early = datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)  # 06:00 Zürich
    assert push_service.process_pet_care_tasks(db, early) == 0
    db.refresh(task)
    assert task.notified_at is None

    later = datetime(2026, 9, 29, 7, 0, tzinfo=timezone.utc)  # 09:00 Zürich
    assert push_service.process_pet_care_tasks(db, later) == 1
    payload = _payloads(mock_webpush)[0]
    assert payload["body"] == "Luna: Krallen schneiden"
    assert payload["url"] == f"/pets/{pet_a.id}"

    mock_webpush.reset_mock()
    assert push_service.process_pet_care_tasks(db, later) == 0


def test_pet_care_not_due_yet(db, pet_a, user_a, mock_webpush):
    _add_sub(db, user_a)
    _care_task(db, pet_a, date(2026, 10, 1))
    now = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)
    assert push_service.process_pet_care_tasks(db, now) == 0


# ---------------------------------------------------------------------------
# Scheduler: Pflanzenpflege
# ---------------------------------------------------------------------------
def _plant_task(db, plant, due: date, care_type="water", label=None):
    t = PlantCareTask(
        household_id=plant.household_id, plant_id=plant.id, care_type=care_type,
        label=label, interval_days=7, next_due_at=due,
    )
    db.add(t)
    db.commit()
    return t


def test_plant_care_waits_for_morning(db, household_a, plant_a, user_a, mock_webpush):
    household_a.timezone = "Europe/Zurich"
    db.commit()
    _add_sub(db, user_a)
    task = _plant_task(db, plant_a, date(2026, 9, 29))

    early = datetime(2026, 9, 29, 4, 0, tzinfo=timezone.utc)  # 06:00 Zürich
    assert push_service.process_plant_care_tasks(db, early) == 0
    db.refresh(task)
    assert task.notified_at is None

    later = datetime(2026, 9, 29, 7, 0, tzinfo=timezone.utc)  # 09:00 Zürich
    assert push_service.process_plant_care_tasks(db, later) == 1
    payload = _payloads(mock_webpush)[0]
    assert payload["title"] == "Pflanzenpflege fällig"
    assert payload["body"] == "Monstera: Gießen"
    assert payload["url"] == f"/plants/{plant_a.id}"

    mock_webpush.reset_mock()
    assert push_service.process_plant_care_tasks(db, later) == 0


def test_plant_care_label_and_locale(db, plant_a, user_a, mock_webpush):
    _add_sub(db, user_a, locale="en")
    _plant_task(db, plant_a, date(2026, 9, 29), care_type="mist")
    _plant_task(db, plant_a, date(2026, 9, 29), care_type="other", label="Wipe leaves")
    now = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    assert push_service.process_plant_care_tasks(db, now) == 2
    assert sorted(p["body"] for p in _payloads(mock_webpush)) == ["Monstera: Mist", "Monstera: Wipe leaves"]


def test_plant_care_not_due_yet(db, plant_a, user_a, mock_webpush):
    _add_sub(db, user_a)
    _plant_task(db, plant_a, date(2026, 10, 1))
    now = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)
    assert push_service.process_plant_care_tasks(db, now) == 0
