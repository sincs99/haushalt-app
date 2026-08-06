import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel, EmailStr, Field

from app.database import get_db
from app.models import User, Household, HouseholdMember
from app.core.error_codes import ErrorCode, error_detail
from app.core.security import hash_password, verify_password, create_access_token, generate_invite_code
from app.core.deps import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str
    household_name: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class HouseholdOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    households: list[HouseholdOut]


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

    MAX_INVITE_CODE_RETRIES = 5
    for attempt in range(MAX_INVITE_CODE_RETRIES):
        invite_code = generate_invite_code()
        existing = db.query(Household).filter_by(invite_code=invite_code).first()
        if existing is None:
            break
        if attempt == MAX_INVITE_CODE_RETRIES - 1:
            logger.error(
                "Failed to generate unique invite code after %d attempts",
                MAX_INVITE_CODE_RETRIES,
            )
            raise HTTPException(
                status_code=500,
                detail=error_detail(ErrorCode.INVITE_CODE_GENERATION_FAILED, "Could not generate unique invite code"),
            )

    household = Household(name=data.household_name, invite_code=invite_code)
    db.add(household)
    db.flush()

    membership = HouseholdMember(household_id=household.id, user_id=user.id, role="admin")
    db.add(membership)
    db.commit()

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail=error_detail(ErrorCode.INVALID_CREDENTIALS, "Incorrect email or password"))

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


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
        HouseholdOut(id=m.household.id, name=m.household.name, role=m.role)
        for m in memberships
    ]

    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        households=households,
    )
