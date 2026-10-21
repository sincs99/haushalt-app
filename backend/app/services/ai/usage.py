"""Atomic household, account and global UTC-day reservations.

The complete reservation commits before provider dispatch. Unknown outcomes
remain charged to the call budget; only a proven pre-dispatch rejection can be
refunded. A durable reservation UUID owns exactly one completion or refund.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AiBudgetCounter, AiCallReservation, AiUsage, AiUserUsage
from app.services import entitlements
from app.services.ai.errors import AiDailyLimitReached, AiUsageInfo, AiUserDailyLimitReached


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _increment_below_limit(db: Session, model, key_column, key: uuid.UUID | str, day: date, limit: int) -> bool:
    """Atomically create or increment one budget under its unique scope/day key."""
    if limit <= 0:
        return False
    insert = postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert
    values = {"day": day, "calls": 1, key_column.key: key}
    if model is not AiBudgetCounter:
        values["id"] = uuid.uuid4()
    stmt = insert(model).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[key_column, model.day],
        set_={"calls": model.calls + 1},
        where=model.calls < limit,
    ).returning(model.calls)
    return db.execute(stmt).first() is not None


def daily_limit(db: Session, household_id: uuid.UUID) -> int:
    """Preserve the existing household entitlement/plan allocation."""
    return entitlements.limits_for_household_id(db, household_id).ai_daily_limit


def reserve_call(db: Session, household_id: uuid.UUID, user_id: uuid.UUID) -> uuid.UUID:
    """All three budgets succeed together, or none is consumed."""
    day = today_utc()
    reservation_id = uuid.uuid4()
    try:
        # Stable lock order, shared with release_call, avoids budget deadlocks.
        household_limit = daily_limit(db, household_id)
        if not _increment_below_limit(db, AiBudgetCounter, AiBudgetCounter.scope_key, "global", day, settings.ai_daily_limit_global):
            raise AiDailyLimitReached("Global daily AI budget reached")
        if not _increment_below_limit(db, AiUserUsage, AiUserUsage.user_id, user_id, day, settings.ai_daily_limit_per_user):
            raise AiUserDailyLimitReached("Personal daily AI limit reached")
        if not _increment_below_limit(db, AiUsage, AiUsage.household_id, household_id, day, household_limit):
            raise AiDailyLimitReached("Household daily AI limit reached")
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
            db.execute(
                update(AiBudgetCounter)
                .where(AiBudgetCounter.scope_key == "global", AiBudgetCounter.day == row.day, AiBudgetCounter.calls > 0)
                .values(calls=AiBudgetCounter.calls - 1)
            )
            db.execute(
                update(AiUserUsage)
                .where(AiUserUsage.user_id == row.user_id, AiUserUsage.day == row.day, AiUserUsage.calls > 0)
                .values(calls=AiUserUsage.calls - 1)
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


def user_calls_today(db: Session, user_id: uuid.UUID) -> int:
    row = db.query(AiUserUsage).filter_by(user_id=user_id, day=today_utc()).first()
    return row.calls if row else 0
