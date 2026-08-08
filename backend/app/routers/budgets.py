import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Budget, HouseholdMember
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class BudgetUpsert(BaseModel):
    month: date
    amount_rappen: int = Field(..., gt=0)

    @field_validator("month")
    @classmethod
    def month_must_be_first(cls, v: date) -> date:
        if v.day != 1:
            raise ValueError("month must be the first day of a month (day == 1)")
        return v


class BudgetResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    month: date
    amount_rappen: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}",
    tags=["budgets"],
)


# ---------------------------------------------------------------------------
# PUT /budget  — Upsert (Create or Update)
# ---------------------------------------------------------------------------
@router.put(
    "/budget",
    response_model=BudgetResponse,
    responses={200: {"description": "Updated"}, 201: {"description": "Created"}},
)
def upsert_budget(
    household_id: uuid.UUID,
    body: BudgetUpsert,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    existing = (
        db.query(Budget)
        .filter(Budget.household_id == household_id, Budget.month == body.month)
        .first()
    )

    if existing:
        existing.amount_rappen = body.amount_rappen
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)

        emit_to_household_sync(
            household_id,
            "budget_updated",
            BudgetResponse.model_validate(existing).model_dump(mode="json"),
        )
        # 200 OK — FastAPI gibt default 200 zurück
        return existing
    else:
        budget = Budget(
            household_id=household_id,
            month=body.month,
            amount_rappen=body.amount_rappen,
        )
        db.add(budget)
        db.commit()
        db.refresh(budget)

        emit_to_household_sync(
            household_id,
            "budget_updated",
            BudgetResponse.model_validate(budget).model_dump(mode="json"),
        )
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=BudgetResponse.model_validate(budget).model_dump(mode="json"),
        )


# ---------------------------------------------------------------------------
# GET /budget  — Aktuelles Monatsbudget
# ---------------------------------------------------------------------------
@router.get("/budget", response_model=BudgetResponse | None)
def get_budget(
    household_id: uuid.UUID,
    month: date | None = Query(None, description="YYYY-MM-DD, must be 1st of month. Default: current month"),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    if month is None:
        today = date.today()
        month = date(today.year, today.month, 1)
    elif month.day != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.INVALID_MONTH, "month must be the first day of a month"),
        )

    budget = (
        db.query(Budget)
        .filter(Budget.household_id == household_id, Budget.month == month)
        .first()
    )

    # Falls kein Budget: 200 mit null (nicht 404)
    return budget


# ---------------------------------------------------------------------------
# DELETE /budget  — Budget für einen Monat löschen
# ---------------------------------------------------------------------------
@router.delete("/budget", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(
    household_id: uuid.UUID,
    month: date = Query(...),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Budget für einen bestimmten Monat löschen."""
    if month.day != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.INVALID_MONTH, "month must be the first day of a month"),
        )

    budget = (
        db.query(Budget)
        .filter(Budget.household_id == household_id, Budget.month == month)
        .first()
    )
    if budget is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.BUDGET_NOT_FOUND, "No budget found for this month"),
        )

    db.delete(budget)
    db.commit()

    emit_to_household_sync(
        household_id,
        "budget_deleted",
        {"household_id": str(household_id), "month": month.isoformat()},
    )
