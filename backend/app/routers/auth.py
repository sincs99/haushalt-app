import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, EmailStr, Field, model_validator

from app.database import get_db
from app.models import User, Household, HouseholdMember, RefreshToken
from app.core.error_codes import ErrorCode, error_detail
from app.core.security import (
    hash_password, verify_password, create_access_token,
    create_refresh_token, hash_refresh_token, get_access_token_expires_in,
)
from app.services.invite_code import generate_unique_invite_code
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str
    household_name: str | None = None
    invite_code: str | None = None

    @model_validator(mode="after")
    def exactly_one_household_method(self):
        """Genau eines von household_name oder invite_code muss gesetzt sein."""
        has_name = self.household_name is not None and self.household_name.strip() != ""
        has_code = self.invite_code is not None and self.invite_code.strip() != ""
        if has_name == has_code:  # Beide gesetzt oder beide leer
            raise ValueError("Exactly one of household_name or invite_code must be provided")
        return self


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Sekunden bis Access-Token abläuft


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class HouseholdOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    currency: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    households: list[HouseholdOut]


# ---------------------------------------------------------------------------
# Hilfsfunktion: Token-Paar erstellen + Refresh-Token persistieren
# ---------------------------------------------------------------------------


def _create_token_pair(user_id: str, db: Session) -> TokenResponse:
    """Erzeugt Access- + Refresh-Token-Paar und persistiert den Refresh-Token."""
    from app.core.config import settings

    access_token = create_access_token(user_id)
    raw_refresh = create_refresh_token()

    rt = RefreshToken(
        user_id=uuid.UUID(user_id),
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        token_type="bearer",
        expires_in=get_access_token_expires_in(),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", response_model=TokenResponse)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter_by(email=data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail=error_detail(ErrorCode.EMAIL_ALREADY_REGISTERED, "Email already registered"))

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
    )
    db.add(user)
    db.flush()

    if data.invite_code:
        # ── Pfad B: Mit Einladungscode beitreten ──
        code = data.invite_code.strip().upper()
        household = (
            db.query(Household)
            .filter(func.upper(Household.invite_code) == code)
            .first()
        )
        if household is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail(ErrorCode.INVITE_CODE_NOT_FOUND, "Invite code not found"),
            )
        membership = HouseholdMember(household_id=household.id, user_id=user.id, role="member")
    else:
        # ── Pfad A: Neuen Haushalt erstellen (Standard, wie bisher) ──
        invite_code = generate_unique_invite_code(db)
        household = Household(name=data.household_name.strip(), invite_code=invite_code)
        db.add(household)
        db.flush()
        membership = HouseholdMember(household_id=household.id, user_id=user.id, role="admin")

    db.add(membership)
    db.flush()

    return _create_token_pair(str(user.id), db)


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail=error_detail(ErrorCode.INVALID_CREDENTIALS, "Incorrect email or password"))

    return _create_token_pair(str(user.id), db)


@router.post("/refresh", response_model=TokenResponse)
def refresh_endpoint(data: RefreshRequest, db: Session = Depends(get_db)):
    """Token-Rotation: tausche gültigen Refresh-Token gegen neues Token-Paar."""
    token_hash = hash_refresh_token(data.refresh_token)
    old_token = db.query(RefreshToken).filter_by(token_hash=token_hash).first()

    # 1) Token nicht gefunden
    if old_token is None:
        raise HTTPException(
            status_code=401,
            detail=error_detail(ErrorCode.REFRESH_TOKEN_INVALID, "Refresh token invalid"),
        )

    # 2) Reuse-Detection: Token bereits revoked → gesamte Kette revoken
    if old_token.revoked_at is not None:
        db.query(RefreshToken).filter(
            RefreshToken.user_id == old_token.user_id,
            RefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(timezone.utc)})
        db.commit()
        raise HTTPException(
            status_code=401,
            detail=error_detail(ErrorCode.REFRESH_TOKEN_REUSED, "Refresh token reuse detected"),
        )

    # 3) Token abgelaufen (SQLite gibt naive datetimes, PostgreSQL aware)
    expires_at = old_token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=401,
            detail=error_detail(ErrorCode.REFRESH_TOKEN_EXPIRED, "Refresh token expired"),
        )

    # 4) Alles OK → alten Token revoken, neues Paar erstellen
    old_token.revoked_at = datetime.now(timezone.utc)
    db.flush()

    pair = _create_token_pair(str(old_token.user_id), db)

    # replaced_by_id auf das neue RefreshToken setzen
    new_rt = db.query(RefreshToken).filter_by(
        token_hash=hash_refresh_token(pair.refresh_token)
    ).first()
    if new_rt:
        old_token.replaced_by_id = new_rt.id
        db.commit()

    return pair


@router.post("/logout", status_code=204)
def logout_endpoint(data: LogoutRequest, db: Session = Depends(get_db)):
    """Revoke einen Refresh-Token. Idempotent: unbekannte/bereits revoked Tokens → trotzdem 204."""
    token_hash = hash_refresh_token(data.refresh_token)
    existing = db.query(RefreshToken).filter_by(token_hash=token_hash).first()
    if existing and existing.revoked_at is None:
        existing.revoked_at = datetime.now(timezone.utc)
        db.commit()
    return None


@router.get("/me", response_model=MeResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Gibt den aktuell eingeloggten User inkl. Household-Zugehörigkeiten zurück."""
    memberships = (
        db.query(HouseholdMember)
        .options(joinedload(HouseholdMember.household))
        .filter_by(user_id=current_user.id)
        .all()
    )
    households = [
        HouseholdOut(id=m.household.id, name=m.household.name, role=m.role, currency=m.household.currency)
        for m in memberships
    ]

    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        households=households,
    )
