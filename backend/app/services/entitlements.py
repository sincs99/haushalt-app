"""Tarife und Limits pro Haushalt.

Ein Haushalt hat einen Tarif (``Household.plan``: ``free`` oder ``premium``). Welche Limits
gelten, entscheidet dieses Modul — alle Prüfpunkte (Mitglieder beim Beitritt, Speicher
beim Upload, KI-Tageslimit) fragen hier nach und kennen weder Stripe noch Tarif-Namen.

Self-Hosting (``BILLING_ENABLED=false``, Standard): jeder Haushalt bekommt den Tarif
``selfhosted`` mit den globalen Limits aus der Konfiguration — Verhalten wie vor der
Einführung der Tarife.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Household, HouseholdMember

PLAN_FREE = "free"
PLAN_PREMIUM = "premium"
PLAN_SELFHOSTED = "selfhosted"
PAID_PLANS = (PLAN_PREMIUM,)
ASSIGNABLE_PLANS = (PLAN_FREE, PLAN_PREMIUM)


@dataclass(frozen=True)
class PlanLimits:
    key: str
    # None = unbegrenzt
    max_members: int | None
    storage_bytes: int
    # 0 = KI nicht im Tarif enthalten
    ai_daily_limit: int

    @property
    def ai_included(self) -> bool:
        return self.ai_daily_limit > 0

    @property
    def storage_mb(self) -> int:
        return self.storage_bytes // (1024 * 1024)


def _members_limit(value: int) -> int | None:
    return None if value <= 0 else value


def limits_for_plan(plan: str) -> PlanLimits:
    if plan == PLAN_SELFHOSTED:
        return PlanLimits(
            key=PLAN_SELFHOSTED,
            max_members=None,
            storage_bytes=settings.household_storage_quota_mb * 1024 * 1024,
            ai_daily_limit=settings.ai_daily_limit_per_household,
        )
    if plan == PLAN_PREMIUM:
        return PlanLimits(
            key=PLAN_PREMIUM,
            max_members=_members_limit(settings.plan_premium_max_members),
            storage_bytes=settings.plan_premium_storage_mb * 1024 * 1024,
            ai_daily_limit=max(0, settings.plan_premium_ai_daily_limit),
        )
    return PlanLimits(
        key=PLAN_FREE,
        max_members=_members_limit(settings.plan_free_max_members),
        storage_bytes=settings.plan_free_storage_mb * 1024 * 1024,
        ai_daily_limit=max(0, settings.plan_free_ai_daily_limit),
    )


def _is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:  # SQLite liefert naive Datetimes
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at < datetime.now(timezone.utc)


def effective_plan(household: Household) -> str:
    """Tarif-Schlüssel, der gerade gilt (abgelaufene bezahlte Tarife fallen auf ``free``)."""
    if not settings.billing_enabled:
        return PLAN_SELFHOSTED
    if household.plan in PAID_PLANS and not _is_expired(household.plan_expires_at):
        return household.plan
    return PLAN_FREE


def limits_for_household(household: Household) -> PlanLimits:
    return limits_for_plan(effective_plan(household))


def limits_for_household_id(db: Session, household_id: uuid.UUID) -> PlanLimits:
    household = db.get(Household, household_id)
    if household is None:
        # Haushalt gerade gelöscht — grosszügigster Tarif, die Zugriffsprüfung greift ohnehin
        return limits_for_plan(PLAN_SELFHOSTED)
    return limits_for_household(household)


def member_count(db: Session, household_id: uuid.UUID) -> int:
    return (
        db.query(func.count(HouseholdMember.id))
        .filter(HouseholdMember.household_id == household_id)
        .scalar()
        or 0
    )


def can_add_member(db: Session, household: Household) -> bool:
    limits = limits_for_household(household)
    if limits.max_members is None:
        return True
    return member_count(db, household.id) < limits.max_members
