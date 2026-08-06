import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Chore, ChoreAssignment, HouseholdMember, Household
from app.services.household_checks import assert_users_in_household
from app.services.chore_scheduler import (
    today_in_tz,
    next_due_dates,
    materialize_due_assignments,
)
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class ChoreCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    recurrence: str = Field(...)  # "weekly" | "biweekly" | "monthly"
    weekday: int | None = None  # 0-6
    day_of_month: int | None = None  # 1-31
    rotation_order: list[str] = Field(..., min_length=1)
    active: bool = True

    @field_validator("recurrence")
    @classmethod
    def validate_recurrence(cls, v):
        if v not in ("weekly", "biweekly", "monthly"):
            raise ValueError("Must be weekly, biweekly, or monthly")
        return v


class ChoreUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    recurrence: str | None = None
    weekday: int | None = None
    day_of_month: int | None = None
    rotation_order: list[str] | None = None
    active: bool | None = None


class ChoreResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    title: str
    description: str | None
    recurrence: str
    weekday: int | None
    day_of_month: int | None
    rotation_order: list[str]
    next_rotation_index: int
    anchor_date: date
    active: bool
    created_at: datetime
    created_by_user_id: uuid.UUID | None

    model_config = ConfigDict(from_attributes=True)


class ChoreAssignmentResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    chore_id: uuid.UUID
    assigned_user_id: uuid.UUID | None
    due_date: date
    completed_at: datetime | None
    completed_by_user_id: uuid.UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssignmentReassign(BaseModel):
    assigned_user_id: uuid.UUID


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/chores",
    tags=["chores"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_rotation_order(
    db: Session, household_id: uuid.UUID, rotation_order: list[str]
) -> None:
    """Validiert rotation_order: UUID-parsbar, keine Duplikate, alle im Household."""
    parsed_ids: list[uuid.UUID] = []
    seen: set[str] = set()
    for uid_str in rotation_order:
        try:
            parsed_ids.append(uuid.UUID(uid_str))
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.CHORE_INVALID_ROTATION,
                    f"Invalid UUID in rotation_order: {uid_str}",
                ),
            )
        if uid_str in seen:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.CHORE_INVALID_ROTATION,
                    f"Duplicate user in rotation_order: {uid_str}",
                ),
            )
        seen.add(uid_str)

    assert_users_in_household(db, household_id, parsed_ids)


def _validate_recurrence_fields(
    recurrence: str,
    weekday: int | None,
    day_of_month: int | None,
) -> None:
    """Validiert, dass weekday/day_of_month passend zur recurrence gesetzt sind."""
    if recurrence in ("weekly", "biweekly"):
        if weekday is None or not (0 <= weekday <= 6):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.CHORE_WEEKDAY_REQUIRED,
                    "weekday (0-6) is required for weekly/biweekly recurrence",
                ),
            )
    elif recurrence == "monthly":
        if day_of_month is None or not (1 <= day_of_month <= 31):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.CHORE_DAY_OF_MONTH_REQUIRED,
                    "day_of_month (1-31) is required for monthly recurrence",
                ),
            )


def _compute_anchor_date(
    recurrence: str,
    weekday: int | None,
    day_of_month: int | None,
    today: date,
) -> date:
    """Berechnet das erste fällige Datum ab heute als anchor_date."""
    temp_chore = SimpleNamespace(
        recurrence=recurrence,
        weekday=weekday,
        day_of_month=day_of_month,
        anchor_date=today,
    )
    dates = next_due_dates(temp_chore, today, today + timedelta(days=366))
    return dates[0] if dates else today


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# GET / — Liste aller Chores
@router.get("/", response_model=list[ChoreResponse])
def list_chores(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return (
        db.query(Chore)
        .filter(Chore.household_id == household_id)
        .order_by(Chore.title)
        .all()
    )


# POST / — Chore erstellen
@router.post("/", response_model=ChoreResponse, status_code=status.HTTP_201_CREATED)
def create_chore(
    household_id: uuid.UUID,
    body: ChoreCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Recurrence-abhängige Validierung
    _validate_recurrence_fields(body.recurrence, body.weekday, body.day_of_month)

    # Rotation Order validieren
    _validate_rotation_order(db, household_id, body.rotation_order)

    # anchor_date serverseitig berechnen
    household = db.get(Household, household_id)
    today = today_in_tz(household.timezone)
    anchor = _compute_anchor_date(
        body.recurrence, body.weekday, body.day_of_month, today
    )

    chore = Chore(
        household_id=household_id,
        title=body.title,
        description=body.description,
        recurrence=body.recurrence,
        weekday=body.weekday,
        day_of_month=body.day_of_month,
        rotation_order=body.rotation_order,
        anchor_date=anchor,
        active=body.active,
        created_by_user_id=membership.user_id,
    )
    db.add(chore)
    db.commit()
    db.refresh(chore)

    emit_to_household_sync(
        household_id,
        "chore_created",
        ChoreResponse.model_validate(chore).model_dump(mode="json"),
    )
    return chore


# PATCH /{chore_id} — Chore aktualisieren
@router.patch("/{chore_id}", response_model=ChoreResponse)
def update_chore(
    household_id: uuid.UUID,
    chore_id: uuid.UUID,
    body: ChoreUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    chore = db.get(Chore, chore_id)
    if chore is None or chore.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.CHORE_NOT_FOUND, "Chore not found in this household"
            ),
        )

    update_data = body.model_dump(exclude_unset=True)

    # Rotation Order validieren (wenn geändert)
    if "rotation_order" in update_data and update_data["rotation_order"] is not None:
        _validate_rotation_order(db, household_id, update_data["rotation_order"])

    # Recurrence/Weekday/DayOfMonth-Änderungen → Validierung + anchor_date neu
    recurrence_changed = "recurrence" in update_data
    schedule_changed = (
        recurrence_changed
        or "weekday" in update_data
        or "day_of_month" in update_data
    )

    if schedule_changed:
        new_recurrence = update_data.get("recurrence", chore.recurrence)
        new_weekday = update_data.get("weekday", chore.weekday)
        new_day_of_month = update_data.get("day_of_month", chore.day_of_month)

        _validate_recurrence_fields(new_recurrence, new_weekday, new_day_of_month)

        household = db.get(Household, household_id)
        today = today_in_tz(household.timezone)

        # anchor_date neu berechnen
        update_data["anchor_date"] = _compute_anchor_date(
            new_recurrence, new_weekday, new_day_of_month, today
        )

        # Zukünftige, unerledigte Assignments löschen
        db.query(ChoreAssignment).filter(
            ChoreAssignment.chore_id == chore.id,
            ChoreAssignment.due_date > today,
            ChoreAssignment.completed_at == None,  # noqa: E711
        ).delete()

    # Felder setzen
    for key, value in update_data.items():
        setattr(chore, key, value)

    db.commit()
    db.refresh(chore)

    emit_to_household_sync(
        household_id,
        "chore_updated",
        ChoreResponse.model_validate(chore).model_dump(mode="json"),
    )
    return chore


# DELETE /{chore_id} — Chore löschen
@router.delete("/{chore_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chore(
    household_id: uuid.UUID,
    chore_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    chore = db.get(Chore, chore_id)
    if chore is None or chore.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.CHORE_NOT_FOUND, "Chore not found in this household"
            ),
        )

    db.delete(chore)
    db.commit()

    emit_to_household_sync(
        household_id,
        "chore_deleted",
        {"id": str(chore_id), "household_id": str(household_id)},
    )


# GET /assignments — Assignments mit Materialisierung
@router.get("/assignments", response_model=list[ChoreAssignmentResponse])
def list_assignments(
    household_id: uuid.UUID,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    household = db.get(Household, household_id)
    today = today_in_tz(household.timezone)

    start = from_date or (today - timedelta(days=14))
    end = to_date or (today + timedelta(days=7))

    # Fenster max. 92 Tage
    if (end - start).days > 92:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.CHORE_WINDOW_TOO_LARGE,
                "Date window must not exceed 92 days",
            ),
        )

    # 1. Materialisierung triggern
    new_assignments = materialize_due_assignments(db, household)

    # 2. Socket-Events für neu erzeugte Assignments
    for a in new_assignments:
        db.refresh(a)
        emit_to_household_sync(
            household_id,
            "chore_assignment_created",
            ChoreAssignmentResponse.model_validate(a).model_dump(mode="json"),
        )

    # 3. Assignments im Fenster zurückgeben
    return (
        db.query(ChoreAssignment)
        .filter(
            ChoreAssignment.household_id == household_id,
            ChoreAssignment.due_date >= start,
            ChoreAssignment.due_date <= end,
        )
        .order_by(ChoreAssignment.due_date.asc())
        .all()
    )


# POST /assignments/{assignment_id}/complete
@router.post(
    "/assignments/{assignment_id}/complete",
    response_model=ChoreAssignmentResponse,
)
def complete_assignment(
    household_id: uuid.UUID,
    assignment_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    assignment = db.get(ChoreAssignment, assignment_id)
    if not assignment or assignment.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.CHORE_ASSIGNMENT_NOT_FOUND, "Assignment not found"
            ),
        )

    # Idempotent: bereits erledigt → 200, keine Änderung
    if assignment.completed_at is None:
        assignment.completed_at = datetime.now(timezone.utc)
        assignment.completed_by_user_id = membership.user_id
        db.commit()
        db.refresh(assignment)

    emit_to_household_sync(
        household_id,
        "chore_assignment_updated",
        ChoreAssignmentResponse.model_validate(assignment).model_dump(mode="json"),
    )
    return assignment


# POST /assignments/{assignment_id}/uncomplete
@router.post(
    "/assignments/{assignment_id}/uncomplete",
    response_model=ChoreAssignmentResponse,
)
def uncomplete_assignment(
    household_id: uuid.UUID,
    assignment_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    assignment = db.get(ChoreAssignment, assignment_id)
    if not assignment or assignment.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.CHORE_ASSIGNMENT_NOT_FOUND, "Assignment not found"
            ),
        )

    # Idempotent: wenn schon None → 200
    if assignment.completed_at is not None:
        assignment.completed_at = None
        assignment.completed_by_user_id = None
        db.commit()
        db.refresh(assignment)

    emit_to_household_sync(
        household_id,
        "chore_assignment_updated",
        ChoreAssignmentResponse.model_validate(assignment).model_dump(mode="json"),
    )
    return assignment


# PATCH /assignments/{assignment_id} — Reassign
@router.patch(
    "/assignments/{assignment_id}",
    response_model=ChoreAssignmentResponse,
)
def reassign_assignment(
    household_id: uuid.UUID,
    assignment_id: uuid.UUID,
    body: AssignmentReassign,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    assignment = db.get(ChoreAssignment, assignment_id)
    if not assignment or assignment.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.CHORE_ASSIGNMENT_NOT_FOUND, "Assignment not found"
            ),
        )

    assert_users_in_household(db, household_id, [body.assigned_user_id])

    assignment.assigned_user_id = body.assigned_user_id
    db.commit()
    db.refresh(assignment)

    emit_to_household_sync(
        household_id,
        "chore_assignment_updated",
        ChoreAssignmentResponse.model_validate(assignment).model_dump(mode="json"),
    )
    return assignment
