"""Tageslimit und Token-Zähler pro Haushalt (Tabelle ``ai_usage``).

Ablauf pro Anfrage:

1. ``reserve_call`` erhöht ``calls`` atomar, aber nur solange das Limit nicht erreicht
   ist (``UPDATE … WHERE calls < limit``). So kann es auch bei parallelen Anfragen
   nicht überschritten werden. Danach wird committet — während des API-Aufrufs hält
   die Session keine DB-Verbindung.
2. ``record_tokens`` addiert die Token-Zahlen aus ``response.usage``.
3. ``release_call`` gibt die Reservierung zurück, wenn die API nicht geantwortet hat
   (Netzwerkfehler, Fehlerstatus, Überlast) — dann sind keine Kosten entstanden.

Der Tag ist der UTC-Tag.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AiUsage
from app.services import entitlements
from app.services.ai.errors import AiDailyLimitReached, AiUsageInfo


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _try_increment(db: Session, household_id: uuid.UUID, day: date, limit: int) -> bool:
    result = db.execute(
        update(AiUsage)
        .where(
            AiUsage.household_id == household_id,
            AiUsage.day == day,
            AiUsage.calls < limit,
        )
        .values(calls=AiUsage.calls + 1)
    )
    return result.rowcount == 1


def daily_limit(db: Session, household_id: uuid.UUID) -> int:
    """Tageslimit des Haushalts (tarifabhängig, services/entitlements.py)."""
    return entitlements.limits_for_household_id(db, household_id).ai_daily_limit


def reserve_call(db: Session, household_id: uuid.UUID) -> date:
    """Reserviert einen Aufruf und liefert den gezählten Tag, sonst ``AiDailyLimitReached``."""
    limit = daily_limit(db, household_id)
    day = today_utc()
    if limit <= 0:
        raise AiDailyLimitReached("Daily limit is 0")

    if not _try_increment(db, household_id, day, limit):
        exists = db.query(AiUsage.id).filter_by(household_id=household_id, day=day).first()
        if exists:
            db.rollback()
            raise AiDailyLimitReached("Daily limit reached")
        db.add(AiUsage(household_id=household_id, day=day, calls=1))
        try:
            db.flush()
        except IntegrityError:
            # Parallele Anfrage hat die Zeile gerade angelegt → noch einmal zählen
            db.rollback()
            if not _try_increment(db, household_id, day, limit):
                db.rollback()
                raise AiDailyLimitReached("Daily limit reached")
    db.commit()
    return day


def record_tokens(db: Session, household_id: uuid.UUID, day: date, usage: AiUsageInfo) -> None:
    db.execute(
        update(AiUsage)
        .where(AiUsage.household_id == household_id, AiUsage.day == day)
        .values(
            input_tokens=AiUsage.input_tokens + usage.input_tokens,
            output_tokens=AiUsage.output_tokens + usage.output_tokens,
        )
    )
    db.commit()


def release_call(db: Session, household_id: uuid.UUID, day: date) -> None:
    db.execute(
        update(AiUsage)
        .where(
            AiUsage.household_id == household_id,
            AiUsage.day == day,
            AiUsage.calls > 0,
        )
        .values(calls=AiUsage.calls - 1)
    )
    db.commit()


def calls_today(db: Session, household_id: uuid.UUID) -> int:
    row = db.query(AiUsage).filter_by(household_id=household_id, day=today_utc()).first()
    return row.calls if row else 0
