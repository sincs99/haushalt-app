import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.core.patch_schema import PatchModel
from app.database import get_db
from app.models import Calendar, Event, Household, HouseholdMember
from app.services.event_times import household_tz, range_bounds, to_household_time, to_utc
from app.services.household_checks import assert_users_allowed
from app.services.locking import lock_row
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


class EventUpdate(PatchModel):
    # null auf NOT-NULL-Spalten von Event → 422 (app/core/patch_schema.py)
    __orm_model__ = Event

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


def _tz(db: Session, household_id: uuid.UUID):
    household = db.get(Household, household_id)
    return household_tz(household.timezone if household else None)


def _dedupe(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Doppelte Teilnehmer entfernen, Reihenfolge behalten."""
    return list(dict.fromkeys(ids))


def _validated_participants(
    db: Session, household_id: uuid.UUID, ids: list[uuid.UUID], on_record: list[str] | None = None
) -> list[str]:
    """Teilnehmer prüfen (CASA-21): neue müssen aktuelle Mitglieder sein; wer schon auf
    dem Termin steht, darf auch Ex-Mitglied sein (wie bei Ausgaben, L-05)."""
    ids = _dedupe(ids)
    already = {uuid.UUID(str(p)) for p in (on_record or [])}
    assert_users_allowed(db, household_id, ids, already)
    return [str(pid) for pid in ids]


def _event_response(event: Event, tz) -> EventResponse:
    """Response mit Zeiten in Haushaltszeit (Offset des Haushalts statt UTC)."""
    response = EventResponse.model_validate(event)
    response.starts_at = to_household_time(event.starts_at, tz)
    response.ends_at = to_household_time(event.ends_at, tz)
    return response


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
    # Reines Datum = ganzer Tag in Haushaltszeit (to_date inklusive)
    from_date: date | datetime = Query(...),
    to_date: date | datetime = Query(...),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    tz = _tz(db, household_id)
    range_start, range_end = range_bounds(from_date, to_date, tz)
    events = (
        db.query(Event)
        .filter(
            Event.household_id == household_id,
            Event.starts_at < range_end,
            # Mehrtägige Termine, die vor dem Bereich beginnen, aber hineinreichen
            func.coalesce(Event.ends_at, Event.starts_at) >= range_start,
        )
        .order_by(Event.starts_at.asc())
        .all()
    )
    return [_event_response(e, tz) for e in events]


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
    tz = _tz(db, household_id)
    starts_at = to_utc(body.starts_at, tz)
    ends_at = to_utc(body.ends_at, tz) if body.ends_at is not None else None
    if ends_at is not None and ends_at < starts_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.EVENT_END_BEFORE_START, "ends_at must not be before starts_at"),
        )

    # Calendar muss zum gleichen Haushalt gehören. Gesperrt bis zum Commit, damit
    # ein paralleles Löschen des Kalenders den neuen Termin nicht verliert (CASA-20)
    calendar = lock_row(db, Calendar, body.calendar_id)
    if calendar is None or calendar.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.CALENDAR_MISMATCH, "Calendar does not belong to this household"),
        )

    event = Event(
        household_id=household_id,
        calendar_id=body.calendar_id,
        title=body.title,
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=body.all_day,
        participant_ids=_validated_participants(db, household_id, body.participant_ids),
        note=body.note,
        created_by_user_id=membership.user_id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    response = _event_response(event, tz)
    emit_to_household_sync(
        str(household_id),
        "event_created",
        response.model_dump(mode="json"),
    )
    return response


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
    return _event_response(item, _tz(db, household_id))


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
    tz = _tz(db, household_id)
    for key in ("starts_at", "ends_at"):
        if update_data.get(key) is not None:
            update_data[key] = to_utc(update_data[key], tz)

    # Bestimme die effektiven Werte (gesendet oder bestehend), alles in UTC
    effective_starts = update_data.get("starts_at") or to_household_time(item.starts_at, tz)
    effective_ends = update_data["ends_at"] if "ends_at" in update_data else to_household_time(item.ends_at, tz)

    # Validierung nur wenn ends_at gesetzt ist (nicht None)
    if effective_ends is not None and effective_ends < effective_starts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.EVENT_END_BEFORE_START, "ends_at must not be before starts_at"),
        )

    # calendar_id Validierung falls mitgesendet
    if "calendar_id" in update_data and update_data["calendar_id"] is not None:
        calendar = lock_row(db, Calendar, update_data["calendar_id"])
        if calendar is None or calendar.household_id != household_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(ErrorCode.CALENDAR_MISMATCH, "Calendar does not belong to this household"),
            )

    # participant_ids prüfen und als String-Liste speichern
    if "participant_ids" in update_data and update_data["participant_ids"] is not None:
        update_data["participant_ids"] = _validated_participants(
            db, household_id, update_data["participant_ids"], item.participant_ids
        )

    for field, value in update_data.items():
        setattr(item, field, value)

    db.commit()
    db.refresh(item)

    response = _event_response(item, tz)
    emit_to_household_sync(
        str(household_id),
        "event_updated",
        response.model_dump(mode="json"),
    )
    return response


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
