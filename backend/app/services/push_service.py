"""Web Push: Versand an Subscriptions + periodische Verarbeitung fälliger Erinnerungen.

Der Scheduler läuft als asyncio-Task im Backend-Prozess (uvicorn --workers 1).
Jede Benachrichtigung wird vor dem Versand per bedingtem UPDATE
(`notified_at IS NULL`) "geclaimt" — so wird auch bei mehreren Prozessen
nichts doppelt verschickt.
"""

import asyncio
import json
import logging
import uuid
import zoneinfo
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlparse

from pywebpush import WebPushException, webpush
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import SessionLocal
from app.models import (
    Household,
    HouseholdMember,
    Pet,
    PetCareTask,
    Plant,
    PlantCareTask,
    PushSubscription,
    Todo,
    TodoReminder,
)

logger = logging.getLogger("uvicorn.error")

SCHEDULER_INTERVAL_SECONDS = 60
# Erinnerungen, die länger überfällig sind (z.B. Backend war offline), werden
# still als erledigt markiert statt nachträglich eine Flut an Pushes zu senden.
STALE_AFTER = timedelta(hours=12)
# Tier- und Pflanzenpflege-Aufgaben (Datum ohne Uhrzeit) ab dieser lokalen Stunde melden.
PET_CARE_NOTIFY_HOUR = 8
PLANT_CARE_NOTIFY_HOUR = 8

# SSRF-Schutz: Der Server POSTet an die vom Client gelieferte Endpoint-URL.
# Nur bekannte Push-Services der Browser-Hersteller zulassen.
ALLOWED_PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",          # Chrome, Edge (Android), Samsung
    "push.services.mozilla.com",   # Firefox
    "push.apple.com",              # Safari (macOS/iOS)
    "notify.windows.com",          # Edge (Windows)
)

SUPPORTED_LOCALES = ("de", "en")

_TEXTS = {
    "de": {
        "todo_title": "Erinnerung",
        "pet_title": "Tierpflege fällig",
        "pet_body": "{pet}: {task}",
        "plant_title": "Pflanzenpflege fällig",
        "plant_body": "{plant}: {task}",
        "plant_care_water": "Gießen",
        "plant_care_fertilize": "Düngen",
        "plant_care_repot": "Umtopfen",
        "plant_care_mist": "Besprühen",
        "plant_care_other": "Pflege",
        "test_title": "Benachrichtigungen aktiv",
        "test_body": "So sehen Erinnerungen der Haushalt App aus.",
    },
    "en": {
        "todo_title": "Reminder",
        "pet_title": "Pet care due",
        "pet_body": "{pet}: {task}",
        "plant_title": "Plant care due",
        "plant_body": "{plant}: {task}",
        "plant_care_water": "Water",
        "plant_care_fertilize": "Fertilize",
        "plant_care_repot": "Repot",
        "plant_care_mist": "Mist",
        "plant_care_other": "Care",
        "test_title": "Notifications enabled",
        "test_body": "This is how Haushalt App reminders look.",
    },
}

PayloadBuilder = Callable[[str], dict]


def is_allowed_endpoint(endpoint: str) -> bool:
    try:
        parsed = urlparse(endpoint)
        host = (parsed.hostname or "").lower()
    except ValueError:
        return False
    if parsed.scheme != "https" or not host:
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED_PUSH_HOST_SUFFIXES)


def _text(locale: str, key: str, **kwargs) -> str:
    texts = _TEXTS.get(locale, _TEXTS["de"])
    return texts[key].format(**kwargs)


def _send_one(db: Session, sub: PushSubscription, payload: dict) -> bool:
    """Sendet an eine Subscription. Abgelaufene (404/410) werden gelöscht."""
    try:
        webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            # Frische Dict-Instanz: pywebpush ergänzt "aud"/"exp" in-place
            vapid_claims={"sub": settings.vapid_subject},
            ttl=12 * 3600,
            timeout=10,
        )
        return True
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            db.delete(sub)
            db.commit()
            logger.info("Push subscription %s expired (HTTP %s) — removed", sub.id, status)
        else:
            logger.warning("Push to subscription %s failed: %s", sub.id, exc)
        return False
    except Exception as exc:  # Netzwerkfehler etc. dürfen den Scheduler nicht stoppen
        logger.warning("Push to subscription %s failed: %s", sub.id, exc)
        return False


def send_to_users(db: Session, user_ids: list[uuid.UUID], build_payload: PayloadBuilder) -> int:
    """Sendet an alle Subscriptions der User; Payload wird pro Locale gebaut."""
    if not user_ids:
        return 0
    subs = db.query(PushSubscription).filter(PushSubscription.user_id.in_(user_ids)).all()
    return sum(_send_one(db, sub, build_payload(sub.locale)) for sub in subs)


def _household_member_ids(db: Session, household_id: uuid.UUID) -> list[uuid.UUID]:
    rows = db.query(HouseholdMember.user_id).filter(HouseholdMember.household_id == household_id).all()
    return [r[0] for r in rows]


def _claim(db: Session, model, row_id: uuid.UUID, now: datetime) -> bool:
    """Setzt notified_at atomar; False wenn schon ein anderer Lauf geclaimt hat."""
    result = db.execute(
        update(model)
        .where(model.id == row_id, model.notified_at.is_(None))
        .values(notified_at=now)
    )
    db.commit()
    return result.rowcount == 1


def _as_utc(dt: datetime) -> datetime:
    # SQLite liefert naive Datetimes zurück
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def process_todo_reminders(db: Session, now: datetime) -> int:
    due = (
        db.query(TodoReminder, Todo)
        .join(Todo, TodoReminder.todo_id == Todo.id)
        .filter(
            TodoReminder.remind_at <= now,
            TodoReminder.notified_at.is_(None),
        )
        .all()
    )
    sent = 0
    for reminder, todo in due:
        if not _claim(db, TodoReminder, reminder.id, now):
            continue
        if todo.is_done or now - _as_utc(reminder.remind_at) > STALE_AFTER:
            continue

        members = _household_member_ids(db, reminder.household_id)
        # Zugewiesene Person, sonst der ganze Haushalt
        recipients = [todo.assigned_to_user_id] if todo.assigned_to_user_id in members else members

        title, tag = todo.title, f"todo-reminder-{todo.id}"
        sent += send_to_users(db, recipients, lambda loc: {
            "title": _text(loc, "todo_title"),
            "body": title,
            "url": "/todos",
            "tag": tag,
        })
    return sent


def process_pet_care_tasks(db: Session, now: datetime) -> int:
    due = (
        db.query(PetCareTask, Pet.name, Household.timezone)
        .join(Pet, PetCareTask.pet_id == Pet.id)
        .join(Household, PetCareTask.household_id == Household.id)
        .filter(
            PetCareTask.notified_at.is_(None),
            # Grobfilter (+1 Tag Puffer für Zeitzonen), exakt pro Household unten
            PetCareTask.next_due_at <= (now + timedelta(days=1)).date(),
        )
        .all()
    )
    sent = 0
    for task, pet_name, tz_name in due:
        local_now = now.astimezone(zoneinfo.ZoneInfo(tz_name or "Europe/Zurich"))
        if task.next_due_at > local_now.date() or local_now.hour < PET_CARE_NOTIFY_HOUR:
            continue
        if not _claim(db, PetCareTask, task.id, now):
            continue

        task_name, url, tag = task.name, f"/pets/{task.pet_id}", f"pet-care-{task.id}"
        sent += send_to_users(db, _household_member_ids(db, task.household_id), lambda loc: {
            "title": _text(loc, "pet_title"),
            "body": _text(loc, "pet_body", pet=pet_name, task=task_name),
            "url": url,
            "tag": tag,
        })
    return sent


def process_plant_care_tasks(db: Session, now: datetime) -> int:
    due = (
        db.query(PlantCareTask, Plant.name, Household.timezone)
        .join(Plant, PlantCareTask.plant_id == Plant.id)
        .join(Household, PlantCareTask.household_id == Household.id)
        .filter(
            PlantCareTask.notified_at.is_(None),
            # Grobfilter (+1 Tag Puffer für Zeitzonen), exakt pro Household unten
            PlantCareTask.next_due_at <= (now + timedelta(days=1)).date(),
        )
        .all()
    )
    sent = 0
    for task, plant_name, tz_name in due:
        local_now = now.astimezone(zoneinfo.ZoneInfo(tz_name or "Europe/Zurich"))
        if task.next_due_at > local_now.date() or local_now.hour < PLANT_CARE_NOTIFY_HOUR:
            continue
        if not _claim(db, PlantCareTask, task.id, now):
            continue

        care_type, label = task.care_type, task.label
        url, tag = f"/plants/{task.plant_id}", f"plant-care-{task.id}"
        sent += send_to_users(db, _household_member_ids(db, task.household_id), lambda loc: {
            "title": _text(loc, "plant_title"),
            "body": _text(loc, "plant_body", plant=plant_name, task=label or _text(loc, f"plant_care_{care_type}")),
            "url": url,
            "tag": tag,
        })
    return sent


def send_test_notification(db: Session, user_id: uuid.UUID) -> int:
    return send_to_users(db, [user_id], lambda loc: {
        "title": _text(loc, "test_title"),
        "body": _text(loc, "test_body"),
        "url": "/household",
        "tag": "push-test",
    })


def run_once() -> None:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        sent = (
            process_todo_reminders(db, now)
            + process_pet_care_tasks(db, now)
            + process_plant_care_tasks(db, now)
        )
        if sent:
            logger.info("Push scheduler: %d notification(s) sent", sent)
    except Exception:
        db.rollback()
        logger.exception("Push scheduler run failed")
    finally:
        db.close()


async def scheduler_loop() -> None:
    logger.info("Push scheduler started (interval=%ss)", SCHEDULER_INTERVAL_SECONDS)
    while True:
        # Sync-DB + blockierende HTTP-Calls → Thread, damit der Event-Loop frei bleibt
        await asyncio.to_thread(run_once)
        await asyncio.sleep(SCHEDULER_INTERVAL_SECONDS)
