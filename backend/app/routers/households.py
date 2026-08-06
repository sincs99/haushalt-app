import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, verify_household_access, verify_household_admin
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Household, HouseholdMember, User
from app.services.invite_code import generate_unique_invite_code
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class HouseholdMemberResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    role: str
    model_config = ConfigDict(from_attributes=True)


class JoinRequest(BaseModel):
    invite_code: str


class JoinResponse(BaseModel):
    id: uuid.UUID
    name: str


class InviteCodeResponse(BaseModel):
    invite_code: str


class HouseholdCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class HouseholdCreateResponse(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    currency: str


class HouseholdUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class HouseholdUpdateResponse(BaseModel):
    id: uuid.UUID
    name: str


# ---------------------------------------------------------------------------
# Router 1: Household-spezifische Endpoints (mit household_id im Pfad)
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}",
    tags=["households"],
)


@router.get("/members", response_model=list[HouseholdMemberResponse])
def list_household_members(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    members = (
        db.query(HouseholdMember)
        .options(joinedload(HouseholdMember.user))
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    return [
        HouseholdMemberResponse(
            id=m.user.id,
            display_name=m.user.display_name,
            role=m.role,
        )
        for m in members
    ]


@router.get("/invite-code", response_model=InviteCodeResponse)
def get_invite_code(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail=error_detail(ErrorCode.HOUSEHOLD_NOT_FOUND, "Household not found"))
    return InviteCodeResponse(invite_code=household.invite_code)


@router.patch("", response_model=HouseholdUpdateResponse)
def rename_household(
    household_id: uuid.UUID,
    body: HouseholdUpdateRequest,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail=error_detail(ErrorCode.HOUSEHOLD_NOT_FOUND, "Household not found"))

    household.name = body.name.strip()
    db.commit()

    result = HouseholdUpdateResponse(id=household.id, name=household.name)
    emit_to_household_sync(household_id, "household_updated", {"id": str(household.id), "name": household.name})
    return result


# ---------------------------------------------------------------------------
# Router 2: Household-übergreifende Endpoints (ohne household_id im Pfad)
# ---------------------------------------------------------------------------

general_router = APIRouter(
    prefix="/api/households",
    tags=["households"],
)


@general_router.post("/", response_model=HouseholdCreateResponse, status_code=status.HTTP_201_CREATED)
def create_household(
    body: HouseholdCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invite_code = generate_unique_invite_code(db)
    household = Household(name=body.name.strip(), invite_code=invite_code)
    db.add(household)
    db.flush()

    membership = HouseholdMember(
        household_id=household.id,
        user_id=current_user.id,
        role="admin",
    )
    db.add(membership)

    # Werte vor Commit sichern
    result = HouseholdCreateResponse(
        id=household.id, name=household.name, role="admin", currency=household.currency
    )
    db.commit()
    return result


@general_router.post("/join", response_model=JoinResponse)
def join_household(
    data: JoinRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Code normalisieren (case-insensitiv)
    code = data.invite_code.strip().upper()

    # Household suchen
    from sqlalchemy import func
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

    # Prüfen ob User bereits Mitglied ist
    existing = (
        db.query(HouseholdMember)
        .filter_by(household_id=household.id, user_id=current_user.id)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.ALREADY_MEMBER, "Already a member of this household"),
        )

    # Membership anlegen
    membership = HouseholdMember(
        household_id=household.id,
        user_id=current_user.id,
        role="member",
    )
    db.add(membership)

    # Werte vor dem Commit sichern (SQLAlchemy expired Objekte nach commit)
    household_id = household.id
    household_name = household.name
    user_id = current_user.id
    display_name = current_user.display_name

    db.commit()

    emit_to_household_sync(
        household_id,
        "household_member_joined",
        {
            "household_id": str(household_id),
            "user_id": str(user_id),
            "display_name": display_name,
            "role": "member",
        },
    )

    return JoinResponse(id=household_id, name=household_name)
