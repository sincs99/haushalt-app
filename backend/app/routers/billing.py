"""Tarif und Abrechnung eines Haushalts.

- GET  /api/households/{id}/billing            Tarif, Limits, Verbrauch, Abo (alle Mitglieder)
- POST /api/households/{id}/billing/checkout   Stripe-Checkout starten (Admin, bestätigte E-Mail)
- POST /api/households/{id}/billing/portal     Stripe-Kundenportal (Admin; kündigen, Zahlungsmittel)
- POST /api/billing/webhooks/stripe            Stripe-Webhook (Signatur, Idempotenz)

Native Apps (iOS/Android) dürfen digitale Abos nur über die Store-Abrechnung verkaufen;
dort blendet das Frontend den Stripe-Checkout aus. Store-Abos landen später über
``services/billing/service.apply_subscription`` im selben Modell (docs/monetization.md).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, verify_household_access, verify_household_admin
from app.core.error_codes import ErrorCode, error_detail
from app.core.rate_limit import limiter
from app.database import get_db
from app.models import BillingEvent, Household, HouseholdMember, User
from app.routers.files import household_storage_used
from app.services import entitlements
from app.services.ai import usage as ai_usage
from app.services.billing import stripe_client
from app.services.billing.service import (
    PROVIDER_STRIPE,
    SubscriptionState,
    apply_subscription,
    latest_subscription,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/households/{household_id}/billing", tags=["billing"])
webhook_router = APIRouter(prefix="/api/billing", tags=["billing"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class PlanLimitsOut(BaseModel):
    max_members: int | None
    storage_bytes: int
    ai_daily_limit: int


class UsageOut(BaseModel):
    members: int
    storage_bytes: int
    ai_calls_today: int


class SubscriptionOut(BaseModel):
    provider: str
    status: str
    current_period_end: datetime | None
    cancel_at_period_end: bool


class BillingStatus(BaseModel):
    billing_enabled: bool
    plan: str
    plan_expires_at: datetime | None
    limits: PlanLimitsOut
    usage: UsageOut
    subscription: SubscriptionOut | None
    # Stripe eingerichtet → Upgrade-Button im Web; Portal nur bei bestehendem Stripe-Abo
    checkout_available: bool
    portal_available: bool
    intervals: list[str]


class CheckoutRequest(BaseModel):
    interval: Literal["month", "year"] = "month"


class RedirectOut(BaseModel):
    url: str


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _get_household(db: Session, household_id: uuid.UUID) -> Household:
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.HOUSEHOLD_NOT_FOUND, "Household not found"),
        )
    return household


def _require_billing() -> None:
    if not settings.billing_enabled:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.BILLING_DISABLED, "Billing is not enabled on this server"),
        )
    if not settings.stripe_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail(ErrorCode.BILLING_NOT_CONFIGURED, "Payment provider is not configured"),
        )


def _available_intervals() -> list[str]:
    out = []
    if settings.stripe_price_id_monthly.strip():
        out.append("month")
    if settings.stripe_price_id_yearly.strip():
        out.append("year")
    return out


def _frontend_url(path: str) -> str:
    return f"{settings.public_base_url}{path if path.startswith('/') else '/' + path}"


def _ensure_stripe_customer(db: Session, household: Household, user: User) -> str:
    if household.stripe_customer_id:
        return household.stripe_customer_id
    customer = stripe_client.post(
        "customers",
        {
            "email": user.email,
            "name": household.name,
            "metadata": {"household_id": str(household.id)},
        },
        idempotency_key=f"customer-{household.id}",
    )
    household.stripe_customer_id = customer["id"]
    db.commit()
    return customer["id"]


def _provider_error(exc: Exception) -> HTTPException:
    logger.warning("Stripe request failed: %s", exc)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=error_detail(ErrorCode.BILLING_PROVIDER_ERROR, "Payment provider request failed"),
    )


# ---------------------------------------------------------------------------
# Endpoints (Haushalt)
# ---------------------------------------------------------------------------


@router.get("", response_model=BillingStatus)
def get_billing_status(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    household = _get_household(db, household_id)
    limits = entitlements.limits_for_household(household)
    sub = latest_subscription(db, household_id) if settings.billing_enabled else None
    return BillingStatus(
        billing_enabled=settings.billing_enabled,
        plan=entitlements.effective_plan(household),
        plan_expires_at=household.plan_expires_at if settings.billing_enabled else None,
        limits=PlanLimitsOut(
            max_members=limits.max_members,
            storage_bytes=limits.storage_bytes,
            ai_daily_limit=limits.ai_daily_limit,
        ),
        usage=UsageOut(
            members=entitlements.member_count(db, household_id),
            storage_bytes=household_storage_used(db, household_id),
            ai_calls_today=ai_usage.calls_today(db, household_id),
        ),
        subscription=(
            SubscriptionOut(
                provider=sub.provider,
                status=sub.status,
                current_period_end=sub.current_period_end,
                cancel_at_period_end=sub.cancel_at_period_end,
            )
            if sub
            else None
        ),
        checkout_available=settings.billing_enabled and settings.stripe_configured,
        portal_available=bool(
            settings.billing_enabled and settings.stripe_configured and household.stripe_customer_id
        ),
        intervals=_available_intervals() if settings.billing_enabled else [],
    )


@router.post("/checkout", response_model=RedirectOut)
@limiter.limit("10/minute")
def start_checkout(
    request: Request,
    household_id: uuid.UUID,
    body: CheckoutRequest,
    membership: HouseholdMember = Depends(verify_household_admin),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_billing()
    if current_user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(
                ErrorCode.EMAIL_VERIFICATION_REQUIRED, "Confirm your e-mail address before purchasing"
            ),
        )
    price = settings.stripe_price_id_monthly if body.interval == "month" else settings.stripe_price_id_yearly
    if not price.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.PLAN_INVALID, f"No price configured for interval '{body.interval}'"),
        )
    household = _get_household(db, household_id)
    try:
        customer_id = _ensure_stripe_customer(db, household, current_user)
        session = stripe_client.post(
            "checkout/sessions",
            {
                "mode": "subscription",
                "customer": customer_id,
                "client_reference_id": str(household.id),
                "line_items": [{"price": price.strip(), "quantity": 1}],
                "success_url": _frontend_url(settings.billing_success_path),
                "cancel_url": _frontend_url(settings.billing_cancel_path),
                "allow_promotion_codes": True,
                "metadata": {"household_id": str(household.id)},
                "subscription_data": {"metadata": {"household_id": str(household.id)}},
            },
        )
    except stripe_client.StripeError as exc:
        raise _provider_error(exc)
    return RedirectOut(url=session["url"])


@router.post("/portal", response_model=RedirectOut)
@limiter.limit("10/minute")
def open_portal(
    request: Request,
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    _require_billing()
    household = _get_household(db, household_id)
    if not household.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.BILLING_NO_SUBSCRIPTION, "No Stripe subscription for this household"),
        )
    try:
        session = stripe_client.post(
            "billing_portal/sessions",
            {
                "customer": household.stripe_customer_id,
                "return_url": _frontend_url("/household"),
            },
        )
    except stripe_client.StripeError as exc:
        raise _provider_error(exc)
    return RedirectOut(url=session["url"])


# ---------------------------------------------------------------------------
# Stripe-Webhook
# ---------------------------------------------------------------------------

_SUBSCRIPTION_EVENTS = (
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
)


def _period_end(subscription: dict) -> datetime | None:
    """``current_period_end`` liegt je nach API-Version am Abo oder am ersten Item."""
    value = subscription.get("current_period_end")
    if value is None:
        items = (subscription.get("items") or {}).get("data") or []
        if items:
            value = items[0].get("current_period_end")
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc)


def _household_for_subscription(db: Session, subscription: dict) -> Household | None:
    household_id = (subscription.get("metadata") or {}).get("household_id")
    if household_id:
        try:
            household = db.get(Household, uuid.UUID(household_id))
        except ValueError:
            household = None
        if household is not None:
            return household
    customer = subscription.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    if customer:
        return db.query(Household).filter_by(stripe_customer_id=customer).first()
    return None


def handle_stripe_event(db: Session, event: dict) -> str:
    """Verarbeitet ein (bereits signaturgeprüftes) Event. Liefert eine kurze Ergebnis-Kennung."""
    event_type = event.get("type", "")
    obj = (event.get("data") or {}).get("object") or {}

    if event_type == "checkout.session.completed":
        household_id = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("household_id")
        customer = obj.get("customer")
        if household_id and customer:
            try:
                household = db.get(Household, uuid.UUID(household_id))
            except ValueError:
                household = None
            if household is not None and household.stripe_customer_id != customer:
                household.stripe_customer_id = customer
                db.commit()
        return "customer_linked"

    if event_type in _SUBSCRIPTION_EVENTS:
        household = _household_for_subscription(db, obj)
        if household is None:
            logger.warning("Stripe subscription %s without matching household", obj.get("id"))
            return "ignored_no_household"
        apply_subscription(
            db,
            household,
            SubscriptionState(
                provider=PROVIDER_STRIPE,
                provider_subscription_id=str(obj.get("id")),
                status=str(obj.get("status") or "unknown"),
                current_period_end=_period_end(obj),
                cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
            ),
        )
        return "subscription_applied"

    return "ignored"


@webhook_router.post("/webhooks/stripe")
@limiter.limit("120/minute")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not settings.billing_enabled or not settings.stripe_webhook_secret.strip():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.BILLING_DISABLED, "Billing is not enabled on this server"),
        )
    payload = await request.body()
    if not stripe_client.verify_webhook_signature(
        payload, request.headers.get("stripe-signature"), settings.stripe_webhook_secret.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.WEBHOOK_SIGNATURE_INVALID, "Invalid webhook signature"),
        )
    try:
        event = json.loads(payload)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    event_id = str(event.get("id") or "")
    if not event_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing event id")

    # Idempotenz: Stripe liefert Events bei Timeouts erneut
    db.add(BillingEvent(provider=PROVIDER_STRIPE, event_id=event_id, event_type=str(event.get("type", ""))[:64]))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"received": True, "result": "duplicate"}

    result = handle_stripe_event(db, event)
    return {"received": True, "result": result}
