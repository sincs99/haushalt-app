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
from datetime import date, datetime, timedelta, timezone
from typing import Callable
from urllib.parse import urlparse

from pywebpush import WebPushException, webpush
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import SessionLocal
from app.models import (
    Chore,
    ChoreAssignment,
    Document,
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
from app.services.attention import attention_count
from app.services.chore_scheduler import materialize_and_emit

logger = logging.getLogger("uvicorn.error")

SCHEDULER_INTERVAL_SECONDS = 60
# Erinnerungen, die länger überfällig sind (z.B. Backend war offline), werden
# still als erledigt markiert statt nachträglich eine Flut an Pushes zu senden.
STALE_AFTER = timedelta(hours=12)
# Tier- und Pflanzenpflege-Aufgaben (Datum ohne Uhrzeit) ab dieser lokalen Stunde melden.
PET_CARE_NOTIFY_HOUR = 8
PLANT_CARE_NOTIFY_HOUR = 8
# Putzplan "Du bist dran" und Dokument-Ablauf ebenfalls am Morgen
CHORE_NOTIFY_HOUR = 8
DOCUMENT_NOTIFY_HOUR = 8
# Vorwarnung für Ablaufdaten (Garantieende, Kündigungsfrist)
DOCUMENT_EXPIRY_LEAD_DAYS = 30

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
        "chore_title_mine": "Du bist dran",
        "chore_title_open": "Ämtli heute fällig",
        "doc_soon_title": "Dokument läuft bald ab",
        "doc_due_title": "Dokument läuft heute ab",
        "doc_body": "{title} · {date}",
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
        "chore_title_mine": "It's your turn",
        "chore_title_open": "Chore due today",
        "doc_soon_title": "Document expires soon",
        "doc_due_title": "Document expires today",
        "doc_body": "{title} · {date}",
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


def _format_date(locale: str, d: date) -> str:
    return d.strftime("%d.%m.%Y") if locale == "de" else d.isoformat()


def send_to_users(
    db: Session,
    user_ids: list[uuid.UUID],
    build_payload: PayloadBuilder,
    household_id: uuid.UUID | None = None,
) -> int:
    """Sendet an alle Subscriptions der User; Payload wird pro Locale gebaut.

    Mit household_id bekommt jede Payload die Zahl fürs App-Icon (`badge`,
    siehe services/attention.py), damit der Service Worker sie setzen kann.
    """
    if not user_ids:
        return 0
    subs = db.query(PushSubscription).filter(PushSubscription.user_id.in_(user_ids)).all()
    household = db.get(Household, household_id) if household_id else None
    badges: dict[uuid.UUID, int] = {}
    sent = 0
    for sub in subs:
        payload = build_payload(sub.locale)
        if household is not None:
            if sub.user_id not in badges:
                badges[sub.user_id] = attention_count(db, household, sub.user_id)
            payload = {**payload, "badge": badges[sub.user_id]}
        sent += _send_one(db, sub, payload)
    return sent


def _household_member_ids(db: Session, household_id: uuid.UUID) -> list[uuid.UUID]:
    rows = db.query(HouseholdMember.user_id).filter(HouseholdMember.household_id == household_id).all()
    return [r[0] for r in rows]


def _claim(db: Session, model, row_id: uuid.UUID, now: datetime, column: str = "notified_at") -> bool:
    """Setzt den Merker atomar; False wenn schon ein anderer Lauf geclaimt hat."""
    col = getattr(model, column)
    result = db.execute(
        update(model)
        .where(model.id == row_id, col.is_(None))
        .values({column: now})
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
        }, household_id=reminder.household_id)
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
        }, household_id=task.household_id)
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
        }, household_id=task.household_id)
    return sent


# Haushalt → lokales Datum der letzten Materialisierung durch den Scheduler.
# Nur ein Worker (uvicorn --workers 1); nach Neustart wird einmal neu materialisiert.
_chores_materialized: dict[uuid.UUID, date] = {}


def _ensure_chore_assignments(db: Session, now: datetime) -> None:
    """Legt die heutigen Ämtli an, auch wenn heute noch niemand die App geöffnet hat.

    Assignments entstehen sonst erst beim Laden des Putzplans (Lazy-Materialisierung).
    Einmal pro Haushalt und lokalem Tag, ab CHORE_NOTIFY_HOUR.
    """
    households = (
        db.query(Household)
        .join(Chore, Chore.household_id == Household.id)
        .filter(Chore.active == True)  # noqa: E712
        .distinct()
        .all()
    )
    for household in households:
        local_now = now.astimezone(zoneinfo.ZoneInfo(household.timezone or "Europe/Zurich"))
        if local_now.hour < CHORE_NOTIFY_HOUR or _chores_materialized.get(household.id) == local_now.date():
            continue
        try:
            materialize_and_emit(db, household)
            _chores_materialized[household.id] = local_now.date()
        except Exception:
            db.rollback()
            logger.exception("Chore materialization for household %s failed", household.id)


def process_chore_assignments(db: Session, now: datetime) -> int:
    """'Du bist dran': am Fälligkeitstag an die zugewiesene Person (sonst an alle)."""
    _ensure_chore_assignments(db, now)
    due = (
        db.query(ChoreAssignment, Chore.title, Household.timezone)
        .join(Chore, ChoreAssignment.chore_id == Chore.id)
        .join(Household, ChoreAssignment.household_id == Household.id)
        .filter(
            ChoreAssignment.notified_at.is_(None),
            ChoreAssignment.completed_at.is_(None),
            # Pausierte Ämtli melden nicht (CASA-17)
            Chore.active == True,  # noqa: E712
            # Grobfilter (±1 Tag für Zeitzonen), exakt pro Household unten
            ChoreAssignment.due_date >= (now - timedelta(days=1)).date(),
            ChoreAssignment.due_date <= (now + timedelta(days=1)).date(),
        )
        .all()
    )
    sent = 0
    for assignment, chore_title, tz_name in due:
        local_now = now.astimezone(zoneinfo.ZoneInfo(tz_name or "Europe/Zurich"))
        # Nur am Fälligkeitstag selbst; ältere offene Ämtli nicht nachträglich melden
        if assignment.due_date != local_now.date() or local_now.hour < CHORE_NOTIFY_HOUR:
            continue
        if not _claim(db, ChoreAssignment, assignment.id, now):
            continue

        members = _household_member_ids(db, assignment.household_id)
        mine = assignment.assigned_user_id in members
        recipients = [assignment.assigned_user_id] if mine else members
        title_key = "chore_title_mine" if mine else "chore_title_open"
        tag = f"chore-{assignment.id}"
        sent += send_to_users(db, recipients, lambda loc: {
            "title": _text(loc, title_key),
            "body": chore_title,
            "url": "/chores",
            "tag": tag,
        }, household_id=assignment.household_id)
    return sent


def process_document_expiry(db: Session, now: datetime) -> int:
    """Ablaufdaten (Garantieende, Kündigungsfrist): Vorwarnung und am Tag selbst."""
    lead = timedelta(days=DOCUMENT_EXPIRY_LEAD_DAYS)
    due = (
        db.query(Document, Household.timezone)
        .join(Household, Document.household_id == Household.id)
        .filter(
            Document.expiry_date.isnot(None),
            Document.expiry_notified_at.is_(None),
            # Grobfilter: ab gestern bis Ende der Vorwarnzeit (+1 Tag Zeitzonen)
            Document.expiry_date >= (now - timedelta(days=1)).date(),
            Document.expiry_date <= (now + lead + timedelta(days=1)).date(),
        )
        .all()
    )
    sent = 0
    for doc, tz_name in due:
        local_now = now.astimezone(zoneinfo.ZoneInfo(tz_name or "Europe/Zurich"))
        today = local_now.date()
        if local_now.hour < DOCUMENT_NOTIFY_HOUR or doc.expiry_date < today:
            continue

        if doc.expiry_date == today:
            column, title_key = "expiry_notified_at", "doc_due_title"
        elif doc.expiry_date <= today + lead and doc.expiry_soon_notified_at is None:
            column, title_key = "expiry_soon_notified_at", "doc_soon_title"
        else:
            continue
        if not _claim(db, Document, doc.id, now, column=column):
            continue

        doc_title, expiry, tag = doc.title, doc.expiry_date, f"document-expiry-{doc.id}"
        sent += send_to_users(db, _household_member_ids(db, doc.household_id), lambda loc: {
            "title": _text(loc, title_key),
            "body": _text(loc, "doc_body", title=doc_title, date=_format_date(loc, expiry)),
            "url": "/documents",
            "tag": tag,
        }, household_id=doc.household_id)
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
            + process_chore_assignments(db, now)
            + process_document_expiry(db, now)
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
