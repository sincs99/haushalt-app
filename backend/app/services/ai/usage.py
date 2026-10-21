"""Atomic household, account and global UTC-day reservations.

The complete reservation commits before provider dispatch. Unknown outcomes
remain charged to the call budget; only a proven pre-dispatch rejection can be
refunded. A durable reservation UUID owns exactly one completion or refund.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AiBudgetCounter, AiCallReservation, AiUsage
from app.services.ai.errors import AiDailyLimitReached, AiUsageInfo


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _increment(db: Session, model: type[AiBudgetCounter] | type[AiUsage], identity: dict, limit: int) -> None:
    """Create-if-missing, then conditional UPDATE under the database row lock."""
    if limit <= 0:
        raise AiDailyLimitReached("Daily AI limit reached")
    if db.query(model).filter_by(**identity).first() is None:
        try:
            # A competing insert must roll back only this savepoint, never the
            # aggregate counters already reserved in the outer transaction.
            with db.begin_nested():
                db.add(model(**identity, calls=0))
                db.flush()
        except IntegrityError:
            pass  # Unique scope/day winner is now visible under READ COMMITTED.
    count = (
        db.query(model).filter_by(**identity).filter(model.calls < limit)
        .update({model.calls: model.calls + 1}, synchronize_session=False)
    )
    if count != 1:
        raise AiDailyLimitReached("Daily AI limit reached")


def reserve_call(db: Session, household_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    """All three budgets succeed together, or none is consumed."""
    day = today_utc()
    reservation_id = uuid.uuid4()
    try:
        # Stable lock order, shared with release_call, avoids budget deadlocks.
        _increment(db, AiBudgetCounter, {"scope_key": "global", "day": day}, settings.ai_daily_limit_global)
        _increment(db, AiBudgetCounter, {"scope_key": f"user:{user_id}", "day": day}, settings.ai_daily_limit_per_user)
        _increment(db, AiUsage, {"household_id": household_id, "day": day}, settings.ai_daily_limit_per_household)
        db.add(AiCallReservation(
            id=reservation_id, household_id=household_id, user_id=user_id,
            day=day, state="reserved",
        ))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return reservation_id


def _claim(db: Session, reservation_id: uuid.UUID, state: str):
    # Conditional state transition is atomic across processes; duplicate and
    # conflicting finalizers cannot debit another request's reservation.
    return db.execute(
        update(AiCallReservation)
        .where(AiCallReservation.id == reservation_id, AiCallReservation.state == "reserved")
        .values(state=state)
        .returning(AiCallReservation.household_id, AiCallReservation.user_id, AiCallReservation.day)
    ).first()


def record_tokens(db: Session, reservation_id: uuid.UUID, usage: AiUsageInfo) -> None:
    try:
        row = _claim(db, reservation_id, "completed")
        if row is not None:
            db.execute(
                update(AiUsage)
                .where(AiUsage.household_id == row.household_id, AiUsage.day == row.day)
                .values(
                    input_tokens=AiUsage.input_tokens + usage.input_tokens,
                    output_tokens=AiUsage.output_tokens + usage.output_tokens,
                )
            )
        db.commit()
    except BaseException:
        db.rollback()
        raise


def release_call(db: Session, reservation_id: uuid.UUID) -> None:
    """Refund only the named, still-pending reservation, once."""
    try:
        row = _claim(db, reservation_id, "released")
        if row is not None:
            for key in ("global", f"user:{row.user_id}"):
                db.execute(
                    update(AiBudgetCounter)
                    .where(AiBudgetCounter.scope_key == key, AiBudgetCounter.day == row.day, AiBudgetCounter.calls > 0)
                    .values(calls=AiBudgetCounter.calls - 1)
                )
            db.execute(
                update(AiUsage)
                .where(AiUsage.household_id == row.household_id, AiUsage.day == row.day, AiUsage.calls > 0)
                .values(calls=AiUsage.calls - 1)
            )
        db.commit()
    except BaseException:
        db.rollback()
        raise


def calls_today(db: Session, household_id: uuid.UUID) -> int:
    row = db.query(AiUsage).filter_by(household_id=household_id, day=today_utc()).first()
    return row.calls if row else 0
