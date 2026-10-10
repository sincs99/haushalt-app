"""Tageslimits und Token-Zähler (Tabellen ``ai_usage`` pro Haushalt, ``ai_user_usage`` pro Person).

Ablauf pro Anfrage:

1. ``reserve_call`` zählt einen Aufruf beim Haushalt UND bei der Person — jeweils mit
   ``INSERT … ON CONFLICT DO UPDATE SET calls = calls + 1 WHERE calls < limit RETURNING``.
   Ein Statement pro Zähler: legt die Tageszeile an oder erhöht sie, aber nur unter dem
   Limit. Parallele Anfragen warten auf die Zeilensperre und sehen danach den neuen Stand,
   es gibt also weder ein Überschreiten noch ein falsches 429 beim ersten Aufruf des
   Tages (CASA-32). Greift eines der Limits, wird die ganze Reservierung zurückgerollt.
   Danach wird committet — während des API-Aufrufs hält die Session keine DB-Verbindung.
2. ``record_tokens`` addiert die Token-Zahlen aus ``response.usage`` (nur Haushalt).
3. ``release_call`` gibt die Reservierung zurück, wenn die API nicht geantwortet hat
   (Netzwerkfehler, Fehlerstatus, Überlast, unerwarteter Fehler) — dann sind keine
   Kosten entstanden.

Sperr-Reihenfolge immer Haushalt → Person (kein Deadlock zwischen Reserve und Release).
Der Tag ist der UTC-Tag.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AiUsage, AiUserUsage
from app.services.ai.errors import AiDailyLimitReached, AiUsageInfo, AiUserDailyLimitReached


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _increment_below_limit(db: Session, model, key_column, key: uuid.UUID, day: date, limit: int) -> bool:
    """Upsert ``calls + 1`` nur solange ``calls < limit``. True = gezählt."""
    insert = postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert
    stmt = insert(model).values(id=uuid.uuid4(), day=day, calls=1, **{key_column.key: key})
    stmt = stmt.on_conflict_do_update(
        index_elements=[key_column, model.day],
        set_={"calls": model.calls + 1},
        where=model.calls < limit,
    ).returning(model.calls)
    return db.execute(stmt).first() is not None


def reserve_call(db: Session, household_id: uuid.UUID, user_id: uuid.UUID) -> date:
    """Reserviert einen Aufruf und liefert den gezählten Tag.

    Wirft ``AiDailyLimitReached`` (Haushalt) oder ``AiUserDailyLimitReached`` (Person).
    """
    household_limit = settings.ai_daily_limit_per_household
    user_limit = settings.ai_daily_limit_per_user
    day = today_utc()
    if household_limit <= 0:
        raise AiDailyLimitReached("Daily limit is 0")
    if user_limit <= 0:
        raise AiUserDailyLimitReached("Daily user limit is 0")

    if not _increment_below_limit(db, AiUsage, AiUsage.household_id, household_id, day, household_limit):
        db.rollback()
        raise AiDailyLimitReached("Daily limit reached")
    if not _increment_below_limit(db, AiUserUsage, AiUserUsage.user_id, user_id, day, user_limit):
        db.rollback()  # nimmt auch die Haushalts-Zählung zurück
        raise AiUserDailyLimitReached("Daily user limit reached")
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


def release_call(db: Session, household_id: uuid.UUID, user_id: uuid.UUID, day: date) -> None:
    db.rollback()  # falls die Session nach einem Fehler noch eine offene Transaktion hat
    db.execute(
        update(AiUsage)
        .where(AiUsage.household_id == household_id, AiUsage.day == day, AiUsage.calls > 0)
        .values(calls=AiUsage.calls - 1)
    )
    db.execute(
        update(AiUserUsage)
        .where(AiUserUsage.user_id == user_id, AiUserUsage.day == day, AiUserUsage.calls > 0)
        .values(calls=AiUserUsage.calls - 1)
    )
    db.commit()


def calls_today(db: Session, household_id: uuid.UUID) -> int:
    row = db.query(AiUsage).filter_by(household_id=household_id, day=today_utc()).first()
    return row.calls if row else 0


def user_calls_today(db: Session, user_id: uuid.UUID) -> int:
    row = db.query(AiUserUsage).filter_by(user_id=user_id, day=today_utc()).first()
    return row.calls if row else 0
