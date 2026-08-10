import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
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


class EventCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    starts_at: datetime
    ends_at: datetime | None = None
    all_day: bool = False
    calendar_id: uuid.UUID
    participant_ids: list[uuid.UUID] = Field(default_factory=list)
    note: str | None = Field(None, max_length=500)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title must not be blank")
        return v.strip()

    @field_validator("note", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class EventUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=150)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool | None = None
    calendar_id: uuid.UUID | None = None
    participant_ids: list[uuid.UUID] | None = None
    note: str | None = Field(None, max_length=500)

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Title must not be blank")
        return v.strip() if v is not None else v

    @field_validator("note", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class EventResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    calendar_id: uuid.UUID
    title: str
    starts_at: datetime
    ends_at: datetime | None
    all_day: bool
    participant_ids: list[uuid.UUID]
    note: str | None
    created_by_user_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/events",
    tags=["events"],
)


# ---------------------------------------------------------------------------
# GET  /  — Liste mit from_date / to_date Filter
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[EventResponse])
def list_events(
    household_id: uuid.UUID,
    from_date: datetime = Query(...),
    to_date: datetime = Query(...),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return (
        db.query(Event)
        .filter(
            Event.household_id == household_id,
            Event.starts_at >= from_date,
            Event.starts_at <= to_date,
        )
        .order_by(Event.starts_at.asc())
        .all()
    )


# ---------------------------------------------------------------------------
# POST /  — Neues Event erstellen
# ---------------------------------------------------------------------------
@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
def create_event(
    household_id: uuid.UUID,
    body: EventCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    if body.ends_at is not None and body.ends_at < body.starts_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.EVENT_END_BEFORE_START, "ends_at must not be before starts_at"),
        )

    # Calendar muss zum gleichen Haushalt gehören
    calendar = db.get(Calendar, body.calendar_id)
    if calendar is None or calendar.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.CALENDAR_MISMATCH, "Calendar does not belong to this household"),
        )

    event = Event(
        household_id=household_id,
        calendar_id=body.calendar_id,
        title=body.title,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        all_day=body.all_day,
        participant_ids=[str(pid) for pid in body.participant_ids],
        note=body.note,
        created_by_user_id=membership.user_id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    emit_to_household_sync(
        str(household_id),
        "event_created",
        EventResponse.model_validate(event).model_dump(mode="json"),
    )
    return event


# ---------------------------------------------------------------------------
# GET /{event_id}  — Einzelnes Event
# ---------------------------------------------------------------------------
@router.get("/{event_id}", response_model=EventResponse)
def get_event(
    household_id: uuid.UUID,
    event_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = db.get(Event, event_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.EVENT_NOT_FOUND, "Event not found in this household"),
        )
    return item


# ---------------------------------------------------------------------------
# PATCH /{event_id}  — Event aktualisieren (partial update)
# ---------------------------------------------------------------------------
@router.patch("/{event_id}", response_model=EventResponse)
def update_event(
    household_id: uuid.UUID,
    event_id: uuid.UUID,
    body: EventUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = db.get(Event, event_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.EVENT_NOT_FOUND, "Event not found in this household"),
        )

    update_data = body.model_dump(exclude_unset=True)

    # Bestimme die effektiven Werte (gesendet oder bestehend)
    effective_starts = update_data.get("starts_at", item.starts_at)
    effective_ends = update_data.get("ends_at", item.ends_at)

    # Validierung nur wenn ends_at gesetzt ist (nicht None)
    if effective_ends is not None and effective_ends < effective_starts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.EVENT_END_BEFORE_START, "ends_at must not be before starts_at"),
        )

    # calendar_id Validierung falls mitgesendet
    if "calendar_id" in update_data and update_data["calendar_id"] is not None:
        calendar = db.get(Calendar, update_data["calendar_id"])
        if calendar is None or calendar.household_id != household_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(ErrorCode.CALENDAR_MISMATCH, "Calendar does not belong to this household"),
            )

    # participant_ids als String-Liste speichern
    if "participant_ids" in update_data and update_data["participant_ids"] is not None:
        update_data["participant_ids"] = [str(pid) for pid in update_data["participant_ids"]]

    for field, value in update_data.items():
        setattr(item, field, value)

    db.commit()
    db.refresh(item)

    emit_to_household_sync(
        str(household_id),
        "event_updated",
        EventResponse.model_validate(item).model_dump(mode="json"),
    )
    return item


# ---------------------------------------------------------------------------
# DELETE /{event_id}  — Event löschen
# ---------------------------------------------------------------------------
@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    household_id: uuid.UUID,
    event_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = db.get(Event, event_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.EVENT_NOT_FOUND, "Event not found in this household"),
        )

    db.delete(item)
    db.commit()

    emit_to_household_sync(
        str(household_id),
        "event_deleted",
        {"id": str(event_id)},
    )
