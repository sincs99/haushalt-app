import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, verify_household_access
from app.database import get_db
from app.models import Household, HouseholdMember, User

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class HouseholdMemberResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    model_config = ConfigDict(from_attributes=True)


class JoinRequest(BaseModel):
    invite_code: str


class JoinResponse(BaseModel):
    id: uuid.UUID
    name: str


class InviteCodeResponse(BaseModel):
    invite_code: str


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
        raise HTTPException(status_code=404, detail="Household not found")
    return InviteCodeResponse(invite_code=household.invite_code)


# ---------------------------------------------------------------------------
# Router 2: Household-übergreifende Endpoints (ohne household_id im Pfad)
# ---------------------------------------------------------------------------

general_router = APIRouter(
    prefix="/api/households",
    tags=["households"],
)


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
            detail="Invite-Code nicht gefunden",
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
            detail="Du bist bereits Mitglied dieses Haushalts",
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

    db.commit()

    return JoinResponse(id=household_id, name=household_name)
