"""Web-Push-Subscriptions verwalten (per User, nicht per Household)."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.error_codes import ErrorCode, error_detail
from app.core.rate_limit import limiter
from app.database import get_db
from app.models import PushSubscription, User
from app.services.push_service import SUPPORTED_LOCALES, is_allowed_endpoint, send_test_notification

router = APIRouter(prefix="/api/push", tags=["push"])


class PushConfigResponse(BaseModel):
    enabled: bool
    public_key: str | None


class SubscriptionKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class SubscriptionCreate(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1000)
    keys: SubscriptionKeys
    locale: str = "de"


class SubscriptionDelete(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1000)


class TestPushResponse(BaseModel):
    sent: int


def _require_enabled() -> None:
    if not settings.push_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail(ErrorCode.PUSH_DISABLED, "Push notifications are not configured"),
        )


@router.get("/config", response_model=PushConfigResponse)
def get_config(current_user: User = Depends(get_current_user)):
    return PushConfigResponse(
        enabled=settings.push_enabled,
        public_key=settings.vapid_public_key if settings.push_enabled else None,
    )


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def upsert_subscription(
    body: SubscriptionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Registriert das Gerät. Idempotent: gleicher Endpoint → Keys/Locale/User aktualisieren
    (z.B. wenn sich auf demselben Gerät ein anderer User anmeldet)."""
    _require_enabled()
    if not is_allowed_endpoint(body.endpoint):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error_detail(ErrorCode.PUSH_ENDPOINT_NOT_ALLOWED, "Push endpoint not allowed"),
        )

    locale = body.locale if body.locale in SUPPORTED_LOCALES else "de"
    sub = db.query(PushSubscription).filter_by(endpoint=body.endpoint).first()
    if sub is None:
        sub = PushSubscription(endpoint=body.endpoint)
        db.add(sub)
    sub.user_id = current_user.id
    sub.p256dh = body.keys.p256dh
    sub.auth = body.keys.auth
    sub.locale = locale
    db.commit()


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
def delete_subscription(
    body: SubscriptionDelete,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Meldet das Gerät ab. Nur eigene Subscriptions; unbekannter Endpoint → trotzdem 204."""
    db.query(PushSubscription).filter_by(
        endpoint=body.endpoint, user_id=current_user.id
    ).delete()
    db.commit()


@router.post("/test", response_model=TestPushResponse)
@limiter.limit("5/minute")
def send_test(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sendet eine Test-Benachrichtigung an alle Geräte des aktuellen Users."""
    _require_enabled()
    return TestPushResponse(sent=send_test_notification(db, current_user.id))
