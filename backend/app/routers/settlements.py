import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.database import get_db
from app.models import Settlement, HouseholdMember
from app.services.household_checks import assert_users_in_household
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class SettlementCreate(BaseModel):
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    amount_rappen: int = Field(..., gt=0)
    currency: str = Field(default="CHF", pattern=r"^[A-Z]{3}$")
    settled_date: date | None = None  # Default: heute (server-seitig)
    note: str | None = Field(None, max_length=200)


class SettlementResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    amount_rappen: int
    currency: str
    settled_date: date
    note: str | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/settlements",
    tags=["settlements"],
)


# GET / — Liste aller Settlements
@router.get("/", response_model=list[SettlementResponse])
def list_settlements(
    household_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return (
        db.query(Settlement)
        .filter(Settlement.household_id == household_id)
        .order_by(Settlement.settled_date.desc(), Settlement.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


# POST / — Neues Settlement
@router.post("/", response_model=SettlementResponse, status_code=status.HTTP_201_CREATED)
def create_settlement(
    household_id: uuid.UUID,
    body: SettlementCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # from != to
    if body.from_user_id == body.to_user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="from_user_id and to_user_id must be different",
        )

    # Beide User müssen Household-Mitglieder sein
    assert_users_in_household(db, household_id, [body.from_user_id, body.to_user_id])

    settlement = Settlement(
        household_id=household_id,
        from_user_id=body.from_user_id,
        to_user_id=body.to_user_id,
        amount_rappen=body.amount_rappen,
        currency=body.currency,
        settled_date=body.settled_date or date.today(),
        note=body.note,
        created_by_user_id=membership.user_id,  # aktueller User
    )
    db.add(settlement)
    db.commit()
    db.refresh(settlement)

    emit_to_household_sync(
        household_id,
        "settlement_created",
        SettlementResponse.model_validate(settlement).model_dump(mode="json"),
    )
    return settlement


# DELETE /{settlement_id} — Settlement löschen
@router.delete("/{settlement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_settlement(
    household_id: uuid.UUID,
    settlement_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    settlement = db.get(Settlement, settlement_id)
    if settlement is None or settlement.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Settlement not found in this household",
        )

    db.delete(settlement)
    db.commit()

    emit_to_household_sync(
        household_id,
        "settlement_deleted",
        {"id": str(settlement_id), "household_id": str(household_id)},
    )
