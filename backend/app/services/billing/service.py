"""Abo-Zustand auf den Haushalt-Tarif abbilden — anbieterneutral.

Stripe-Webhooks, spätere App-Store-Server-Notifications (Apple) und Real-time
Developer Notifications (Google) sowie manuelle Vergaben durch den Plattform-Admin
landen alle in ``apply_subscription``. Dort wird das Abo gespeichert und der Tarif des
Haushalts (``plan``, ``plan_expires_at``) abgeleitet.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Household, Subscription
from app.services.entitlements import PLAN_FREE, PLAN_PREMIUM
from app.socket_manager import emit_to_household_sync

logger = logging.getLogger(__name__)

PROVIDER_STRIPE = "stripe"
PROVIDER_APPLE = "apple"
PROVIDER_GOOGLE = "google"
PROVIDER_MANUAL = "manual"

# Anbieter-Status, bei denen der Haushalt Premium behält (past_due: Karenz läuft über plan_expires_at)
ENTITLED_STATUSES = frozenset({"active", "trialing", "past_due"})


@dataclass(frozen=True)
class SubscriptionState:
    provider: str
    provider_subscription_id: str
    status: str
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    note: str | None = None


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def apply_subscription(db: Session, household: Household, state: SubscriptionState) -> Subscription:
    """Speichert/aktualisiert das Abo und setzt den Tarif des Haushalts. Committet."""
    sub = (
        db.query(Subscription)
        .filter_by(provider=state.provider, provider_subscription_id=state.provider_subscription_id)
        .first()
    )
    if sub is None:
        sub = Subscription(
            household_id=household.id,
            provider=state.provider,
            provider_subscription_id=state.provider_subscription_id,
            status=state.status,
        )
        db.add(sub)
    elif sub.household_id != household.id:
        logger.warning(
            "Subscription %s/%s moved from household %s to %s",
            state.provider, state.provider_subscription_id, sub.household_id, household.id,
        )
        sub.household_id = household.id
    sub.status = state.status
    sub.current_period_end = _aware(state.current_period_end)
    sub.cancel_at_period_end = state.cancel_at_period_end
    if state.note is not None:
        sub.note = state.note[:200]

    old_plan = household.plan
    if state.status in ENTITLED_STATUSES:
        household.plan = PLAN_PREMIUM
        period_end = _aware(state.current_period_end)
        household.plan_expires_at = (
            period_end + timedelta(days=settings.plan_grace_days) if period_end else None
        )
    else:
        # Abo beendet (canceled, unpaid, incomplete_expired, expired …) → Gratis-Tarif.
        # Ein anderes, noch gültiges Abo desselben Haushalts (z. B. Wechsel Stripe → App
        # Store) hält den Tarif aufrecht.
        other_active = (
            db.query(Subscription)
            .filter(
                Subscription.household_id == household.id,
                Subscription.id != sub.id,
                Subscription.status.in_(ENTITLED_STATUSES),
            )
            .first()
        )
        if other_active is None:
            household.plan = PLAN_FREE
            household.plan_expires_at = None
    db.commit()

    if household.plan != old_plan:
        logger.info("Household %s plan %s → %s (%s)", household.id, old_plan, household.plan, state.provider)
    emit_to_household_sync(
        household.id,
        "household_updated",
        {"id": str(household.id), "name": household.name, "ai_enabled": household.ai_enabled, "plan": household.plan},
    )
    return sub


def set_plan_manually(
    db: Session, household: Household, plan: str, expires_at: datetime | None, note: str | None
) -> Subscription:
    """Plattform-Admin vergibt/entzieht einen Tarif (Support, Beta-Tester, Vorführung)."""
    status = "active" if plan == PLAN_PREMIUM else "canceled"
    return apply_subscription(
        db,
        household,
        SubscriptionState(
            provider=PROVIDER_MANUAL,
            provider_subscription_id=f"manual-{household.id}",
            status=status,
            current_period_end=expires_at,
            note=note,
        ),
    )


def latest_subscription(db: Session, household_id: uuid.UUID) -> Subscription | None:
    """Das zuletzt geänderte Abo — aktive bevorzugt."""
    subs = db.query(Subscription).filter_by(household_id=household_id).all()
    if not subs:
        return None
    active = [s for s in subs if s.status in ENTITLED_STATUSES]
    pool = active or subs
    return max(pool, key=lambda s: _aware(s.updated_at) or datetime.min.replace(tzinfo=timezone.utc))
