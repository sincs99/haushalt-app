import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Calendar, Event, HouseholdMember
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class CalendarCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str = Field(..., max_length=7)
    position: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name must not be blank")
        return v.strip()

    @field_validator("color")
    @classmethod
    def validate_hex_color(cls, v: str) -> str:
        import re
        if not re.match(r"^#[0-9A-Fa-f]{6}$", v):
            raise ValueError("color must be a valid hex color (#RRGGBB)")
        return v


class CalendarUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=50)
    color: str | None = Field(None, max_length=7)
    position: int | None = Field(None, ge=0)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Name must not be blank")
        return v.strip() if v is not None else v

    @field_validator("color")
    @classmethod
    def validate_hex_color(cls, v):
        if v is not None:
            import re
            if not re.match(r"^#[0-9A-Fa-f]{6}$", v):
                raise ValueError("color must be a valid hex color (#RRGGBB)")
        return v


class CalendarResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    color: str
    position: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/calendars",
    tags=["calendars"],
)


# ---------------------------------------------------------------------------
# GET /  — Alle Kalender des Haushalts, sortiert nach position
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[CalendarResponse])
def list_calendars(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return (
        db.query(Calendar)
        .filter(Calendar.household_id == household_id)
        .order_by(Calendar.position.asc(), Calendar.created_at.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# POST /  — Kalender erstellen
# ---------------------------------------------------------------------------
@router.post("/", response_model=CalendarResponse, status_code=status.HTTP_201_CREATED)
def create_calendar(
    household_id: uuid.UUID,
    body: CalendarCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    cal = Calendar(
        household_id=household_id,
        name=body.name,
        color=body.color,
        position=body.position,
    )
    db.add(cal)
    db.commit()
    db.refresh(cal)

    emit_to_household_sync(
        str(household_id),
        "calendar_created",
        CalendarResponse.model_validate(cal).model_dump(mode="json"),
    )
    return cal


# ---------------------------------------------------------------------------
# PATCH /{calendar_id}  — Umbenennen / Farbe / Position ändern
# ---------------------------------------------------------------------------
@router.patch("/{calendar_id}", response_model=CalendarResponse)
def update_calendar(
    household_id: uuid.UUID,
    calendar_id: uuid.UUID,
    body: CalendarUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    cal = db.get(Calendar, calendar_id)
    if cal is None or cal.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.CALENDAR_NOT_FOUND, "Calendar not found in this household"),
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(cal, field, value)

    db.commit()
    db.refresh(cal)

    emit_to_household_sync(
        str(household_id),
        "calendar_updated",
        CalendarResponse.model_validate(cal).model_dump(mode="json"),
    )
    return cal


# ---------------------------------------------------------------------------
# DELETE /{calendar_id}  — Kalender löschen (mit Validierungen)
# ---------------------------------------------------------------------------
@router.delete("/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar(
    household_id: uuid.UUID,
    calendar_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    cal = db.get(Calendar, calendar_id)
    if cal is None or cal.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.CALENDAR_NOT_FOUND, "Calendar not found in this household"),
        )

    # Letzter Kalender darf nicht gelöscht werden
    cal_count = (
        db.query(Calendar)
        .filter(Calendar.household_id == household_id)
        .count()
    )
    if cal_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.LAST_CALENDAR, "Cannot delete the last calendar"),
        )

    # Kalender mit Events darf nicht gelöscht werden
    event_count = (
        db.query(Event)
        .filter(Event.calendar_id == calendar_id)
        .count()
    )
    if event_count > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.CALENDAR_NOT_EMPTY, "Calendar still has events"),
        )

    db.delete(cal)
    db.commit()

    emit_to_household_sync(
        str(household_id),
        "calendar_deleted",
        {"id": str(calendar_id)},
    )
