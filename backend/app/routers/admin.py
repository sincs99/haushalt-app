"""Plattform-Admin (Betreiber): Übersicht, Haushalte/Tarife, Nutzer sperren.

Getrennt von der Haushalts-Admin-Rolle. Den Zugang vergibt nur der Betreiber selbst:
``python -m scripts.make_platform_admin --email …`` (nie über die API-Registrierung).
Alle Endpunkte liefern nur, was der Betrieb braucht — keine Inhalte der Haushalte.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Household, HouseholdMember, RefreshToken, StoredFile, Subscription, User
from app.services import entitlements
from app.services.billing.service import ENTITLED_STATUSES, set_plan_manually
from app.socket_manager import disconnect_user_sync

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_platform_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(ErrorCode.PLATFORM_ADMIN_REQUIRED, "Platform admin required"),
        )
    return current_user


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OverviewOut(BaseModel):
    billing_enabled: bool
    users_total: int
    users_active: int
    users_deleted: int
    households_total: int
    households_by_plan: dict[str, int]
    subscriptions_active: int


class HouseholdAdminOut(BaseModel):
    id: uuid.UUID
    name: str
    plan: str
    effective_plan: str
    plan_expires_at: datetime | None
    member_count: int
    storage_bytes: int
    created_at: datetime
    stripe_customer_id: str | None


class SetPlanRequest(BaseModel):
    plan: str
    expires_at: datetime | None = None
    note: str | None = Field(default=None, max_length=200)


class UserAdminOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime
    is_active: bool
    is_platform_admin: bool
    email_verified: bool
    deleted: bool
    household_count: int


class UpdateUserRequest(BaseModel):
    is_active: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=OverviewOut)
def overview(admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    users_total = db.query(func.count(User.id)).scalar() or 0
    users_deleted = db.query(func.count(User.id)).filter(User.deleted_at.isnot(None)).scalar() or 0
    users_active = (
        db.query(func.count(User.id))
        .filter(User.deleted_at.is_(None), User.is_active.is_(True))
        .scalar()
        or 0
    )
    households_total = db.query(func.count(Household.id)).scalar() or 0
    by_plan = {
        plan: count
        for plan, count in db.query(Household.plan, func.count(Household.id)).group_by(Household.plan).all()
    }
    subs_active = (
        db.query(func.count(Subscription.id)).filter(Subscription.status.in_(ENTITLED_STATUSES)).scalar() or 0
    )
    return OverviewOut(
        billing_enabled=settings.billing_enabled,
        users_total=users_total,
        users_active=users_active,
        users_deleted=users_deleted,
        households_total=households_total,
        households_by_plan=by_plan,
        subscriptions_active=subs_active,
    )


def _household_out(db: Session, household: Household) -> HouseholdAdminOut:
    storage = (
        db.query(func.coalesce(func.sum(StoredFile.size_bytes), 0))
        .filter(StoredFile.household_id == household.id)
        .scalar()
        or 0
    )
    return HouseholdAdminOut(
        id=household.id,
        name=household.name,
        plan=household.plan,
        effective_plan=entitlements.effective_plan(household),
        plan_expires_at=household.plan_expires_at,
        member_count=entitlements.member_count(db, household.id),
        storage_bytes=int(storage),
        created_at=household.created_at,
        stripe_customer_id=household.stripe_customer_id,
    )


@router.get("/households", response_model=list[HouseholdAdminOut])
def list_households(
    q: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    query = db.query(Household)
    term = q.strip()
    if term:
        try:
            query = query.filter(Household.id == uuid.UUID(term))
        except ValueError:
            query = query.filter(func.lower(Household.name).contains(term.lower()))
    households = query.order_by(Household.created_at.desc()).limit(limit).all()
    return [_household_out(db, h) for h in households]


@router.patch("/households/{household_id}/plan", response_model=HouseholdAdminOut)
def set_household_plan(
    household_id: uuid.UUID,
    body: SetPlanRequest,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    if body.plan not in entitlements.ASSIGNABLE_PLANS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.PLAN_INVALID, f"Unknown plan '{body.plan}'"),
        )
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.HOUSEHOLD_NOT_FOUND, "Household not found"),
        )
    expires = body.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    set_plan_manually(db, household, body.plan, expires, body.note)
    db.refresh(household)
    return _household_out(db, household)


@router.get("/users", response_model=list[UserAdminOut])
def list_users(
    q: str = Query(default="", max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    query = db.query(User)
    term = q.strip().lower()
    if term:
        query = query.filter(
            func.lower(User.email).contains(term) | func.lower(User.display_name).contains(term)
        )
    users = query.order_by(User.created_at.desc()).limit(limit).all()
    counts = dict(
        db.query(HouseholdMember.user_id, func.count(HouseholdMember.id))
        .filter(HouseholdMember.user_id.in_([u.id for u in users]))
        .group_by(HouseholdMember.user_id)
        .all()
    ) if users else {}
    return [
        UserAdminOut(
            id=u.id,
            email=u.email,
            display_name=u.display_name,
            created_at=u.created_at,
            is_active=u.is_active,
            is_platform_admin=u.is_platform_admin,
            email_verified=u.email_verified_at is not None,
            deleted=u.deleted_at is not None,
            household_count=int(counts.get(u.id, 0)),
        )
        for u in users
    ]


@router.patch("/users/{user_id}", response_model=UserAdminOut)
def update_user(
    user_id: uuid.UUID,
    body: UpdateUserRequest,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.CANNOT_DEACTIVATE_SELF, "You cannot change your own account here"),
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.USER_NOT_FOUND, "User not found"),
        )
    user.is_active = body.is_active
    if not body.is_active:
        # Sperren = alle Sitzungen beenden; der nächste Refresh schlägt fehl → Logout im Client
        db.query(RefreshToken).filter(
            RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
        ).update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
    db.commit()
    if not body.is_active:
        disconnect_user_sync(user.id, "revoked")
    household_count = db.query(func.count(HouseholdMember.id)).filter_by(user_id=user.id).scalar() or 0
    return UserAdminOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
        is_active=user.is_active,
        is_platform_admin=user.is_platform_admin,
        email_verified=user.email_verified_at is not None,
        deleted=user.deleted_at is not None,
        household_count=int(household_count),
    )
