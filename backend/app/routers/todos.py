import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import update
from sqlalchemy.orm import Session, selectinload

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.core.patch_schema import PatchModel
from app.database import get_db
from app.models import Household, HouseholdMember, Todo, TodoReminder
from app.services.client_ids import commit_or_get_existing, get_existing_by_client_id
from app.services.event_times import household_tz, to_utc
from app.services.household_checks import assert_users_allowed, assert_users_in_household
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class TodoReminderResponse(BaseModel):
    id: uuid.UUID
    todo_id: uuid.UUID
    remind_at: datetime
    notified_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReminderCreate(BaseModel):
    # Mit Offset (das Frontend sendet ISO mit "Z") oder ohne: dann Wanduhrzeit des
    # Haushalts — dieselbe Regel wie bei Termin-Uhrzeiten (services/event_times.py)
    remind_at: datetime


class TodoCreate(BaseModel):
    # Optional client-generierte ID → idempotenter Create (Offline-Sync)
    id: uuid.UUID | None = None
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    assigned_to_user_id: uuid.UUID | None = None
    due_date: datetime | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        for tag in v:
            tag_stripped = tag.strip()
            if len(tag_stripped) == 0 or len(tag_stripped) > 50:
                raise ValueError("Each tag must be 1-50 characters")
        return [t.strip() for t in v]

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title must not be blank")
        return v.strip()

    @field_validator("description", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class TodoUpdate(PatchModel):
    # null auf NOT-NULL-Spalten von Todo → 422 (app/core/patch_schema.py)
    __orm_model__ = Todo

    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    assigned_to_user_id: uuid.UUID | None = None
    due_date: datetime | None = None
    is_done: bool | None = None
    tags: list[str] | None = Field(None, max_length=20)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v):
        if v is None:
            return v
        for tag in v:
            tag_stripped = tag.strip()
            if len(tag_stripped) == 0 or len(tag_stripped) > 50:
                raise ValueError("Each tag must be 1-50 characters")
        return [t.strip() for t in v]

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Title must not be blank")
        return v.strip() if v is not None else v

    @field_validator("description", mode="before")
    @classmethod
    def empty_string_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class TodoResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    title: str
    description: str | None
    assigned_to_user_id: uuid.UUID | None
    due_date: datetime | None
    is_done: bool
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    done_at: datetime | None
    tags: list[str]
    updated_at: datetime
    version: int
    reminders: list[TodoReminderResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _todo_response(todo: Todo) -> dict:
    """Konsistente JSON-Serialisierung eines Todo-Objekts für Socket-Events."""
    return TodoResponse.model_validate(todo).model_dump(mode="json")


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/todos",
    tags=["todos"],
)


# ---------------------------------------------------------------------------
# GET  /  — Liste aller Todos
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[TodoResponse])
def list_todos(
    household_id: uuid.UUID,
    include_done: bool = False,
    assigned_to_me: bool = False,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Todo)
        .options(selectinload(Todo.reminders))
        .filter(Todo.household_id == household_id)
    )

    if not include_done:
        query = query.filter(Todo.is_done == False)  # noqa: E712

    if assigned_to_me:
        query = query.filter(Todo.assigned_to_user_id == membership.user_id)

    return query.order_by(Todo.created_at).all()


# ---------------------------------------------------------------------------
# POST /  — Neues Todo erstellen
# ---------------------------------------------------------------------------
@router.post("/", response_model=TodoResponse, status_code=status.HTTP_201_CREATED)
def create_todo(
    household_id: uuid.UUID,
    body: TodoCreate,
    response: Response,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Wiederholter Create mit gleicher Client-ID → bestehendes Todo, kein neues Event
    existing = get_existing_by_client_id(db, Todo, body.id, household_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing

    # Zuständige Person muss Mitglied sein (CASA-21; sonst 500 bei unbekannter ID
    # bzw. eine Aufgabe, die niemandem zählt)
    if body.assigned_to_user_id is not None:
        assert_users_in_household(db, household_id, [body.assigned_to_user_id])

    todo = Todo(
        household_id=household_id,
        title=body.title,
        description=body.description,
        assigned_to_user_id=body.assigned_to_user_id,
        due_date=body.due_date,
        tags=body.tags,
        created_by_user_id=membership.user_id,
    )
    if body.id is not None:
        todo.id = body.id
    db.add(todo)
    existing = commit_or_get_existing(db, Todo, body.id, household_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing
    db.refresh(todo)
    db.refresh(todo, attribute_names=["reminders"])

    emit_to_household_sync(household_id, "todo_created", _todo_response(todo))
    return todo


# ---------------------------------------------------------------------------
# PATCH /{todo_id}  — Todo aktualisieren (partial update)
# ---------------------------------------------------------------------------
@router.patch("/{todo_id}", response_model=TodoResponse)
def update_todo(
    household_id: uuid.UUID,
    todo_id: uuid.UUID,
    body: TodoUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = (
        db.query(Todo)
        .options(selectinload(Todo.reminders))
        .filter(Todo.id == todo_id, Todo.household_id == household_id)
        .first()
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found in this household",
        )

    update_data = body.model_dump(exclude_unset=True)

    # Neue zuständige Person muss Mitglied sein; ein Ex-Mitglied, das schon
    # eingetragen ist, darf beim Speichern stehen bleiben (CASA-21)
    if update_data.get("assigned_to_user_id") is not None:
        on_record = {item.assigned_to_user_id} if item.assigned_to_user_id else set()
        assert_users_allowed(db, household_id, [update_data["assigned_to_user_id"]], on_record)

    was_done = item.is_done
    for field, value in update_data.items():
        setattr(item, field, value)

    # done_at Logik. Erinnerungen werden beim Erledigen NICHT als gesendet markiert
    # (der Scheduler überspringt erledigte Todos) — sonst wären sie nach „Rückgängig“
    # still verloren (CASA-06).
    if "is_done" in update_data:
        if update_data["is_done"] is True:
            if not was_done:
                item.done_at = datetime.now(timezone.utc)
        else:
            item.done_at = None
            if was_done:
                # Wiedereröffnet: künftige Erinnerungen wieder scharf schalten
                # (auch solche, die ältere Versionen beim Erledigen markiert haben)
                now = datetime.now(timezone.utc)
                for reminder in item.reminders:
                    remind_at = reminder.remind_at
                    if remind_at.tzinfo is None:
                        remind_at = remind_at.replace(tzinfo=timezone.utc)
                    if reminder.notified_at is not None and remind_at > now:
                        reminder.notified_at = None

    db.commit()
    db.refresh(item)
    db.refresh(item, attribute_names=["reminders"])

    emit_to_household_sync(household_id, "todo_updated", _todo_response(item))
    return item


# ---------------------------------------------------------------------------
# DELETE /{todo_id}  — Todo löschen
# ---------------------------------------------------------------------------
@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_todo(
    household_id: uuid.UUID,
    todo_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = db.get(Todo, todo_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found in this household",
        )

    db.delete(item)
    db.commit()

    emit_to_household_sync(
        household_id,
        "todo_deleted",
        {"id": str(todo_id)},
    )


# ---------------------------------------------------------------------------
# POST /{todo_id}/claim  — Todo für sich beanspruchen
# ---------------------------------------------------------------------------
@router.post("/{todo_id}/claim", response_model=TodoResponse)
def claim_todo(
    household_id: uuid.UUID,
    todo_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = (
        db.query(Todo)
        .options(selectinload(Todo.reminders))
        .filter(Todo.id == todo_id, Todo.household_id == household_id)
        .first()
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.TODO_NOT_FOUND, "Todo not found in this household"),
        )

    # Atomares UPDATE: nur wenn assigned_to_user_id noch NULL ist (TOCTOU-sicher)
    result = db.execute(
        update(Todo)
        .where(Todo.id == todo_id, Todo.assigned_to_user_id.is_(None))
        # Core-UPDATE umgeht den ORM-Hook → version selbst erhöhen
        .values(assigned_to_user_id=membership.user_id, version=Todo.version + 1)
    )

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.TODO_ALREADY_CLAIMED, "Todo is already assigned"),
        )

    db.commit()
    db.refresh(item)
    db.refresh(item, attribute_names=["reminders"])

    emit_to_household_sync(household_id, "todo_updated", _todo_response(item))
    return item


# ---------------------------------------------------------------------------
# POST /{todo_id}/reminders/  — Neue Erinnerung erstellen
# ---------------------------------------------------------------------------
@router.post("/{todo_id}/reminders/", response_model=TodoReminderResponse, status_code=status.HTTP_201_CREATED)
def create_reminder(
    household_id: uuid.UUID,
    todo_id: uuid.UUID,
    body: ReminderCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # 1. Todo prüfen
    todo = (
        db.query(Todo)
        .options(selectinload(Todo.reminders))
        .filter(Todo.id == todo_id, Todo.household_id == household_id)
        .first()
    )
    if not todo:
        raise HTTPException(
            status_code=404,
            detail=error_detail(ErrorCode.TODO_NOT_FOUND, "Todo not found"),
        )

    # 2. Erledigte Aufgabe: Erinnerung würde nie gesendet (CASA-51)
    if todo.is_done:
        raise HTTPException(
            status_code=422,
            detail=error_detail(ErrorCode.TODO_IS_DONE, "Cannot add a reminder to a done todo"),
        )

    # 3. Zeitpunkt: ohne Offset = Wanduhrzeit des Haushalts; muss in der Zukunft liegen
    household = db.get(Household, household_id)
    remind_at = to_utc(body.remind_at, household_tz(household.timezone if household else None))
    if remind_at <= datetime.now(timezone.utc):
        raise HTTPException(
            status_code=422,
            detail=error_detail(ErrorCode.REMINDER_IN_PAST, "remind_at must be in the future"),
        )

    # 4. Max 5 prüfen
    if len(todo.reminders) >= 5:
        raise HTTPException(
            status_code=422,
            detail=error_detail(ErrorCode.TOO_MANY_REMINDERS, "Maximum 5 reminders per todo"),
        )

    # 5. Erstellen; Todo-Version erhöhen, damit andere Clients das todo_updated-Event
    # nicht als veraltet verwerfen (CASA-46)
    reminder = TodoReminder(
        household_id=household_id,
        todo_id=todo_id,
        remind_at=remind_at,
    )
    db.add(reminder)
    todo.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(reminder)

    # 6. Todo neu laden für Socket-Event
    db.refresh(todo)
    db.refresh(todo, attribute_names=["reminders"])
    emit_to_household_sync(household_id, "todo_updated", _todo_response(todo))

    return reminder


# ---------------------------------------------------------------------------
# DELETE /{todo_id}/reminders/{reminder_id}  — Erinnerung löschen
# ---------------------------------------------------------------------------
@router.delete("/{todo_id}/reminders/{reminder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reminder(
    household_id: uuid.UUID,
    todo_id: uuid.UUID,
    reminder_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # 1. Todo prüfen
    todo = (
        db.query(Todo)
        .filter(Todo.id == todo_id, Todo.household_id == household_id)
        .first()
    )
    if not todo:
        raise HTTPException(
            status_code=404,
            detail=error_detail(ErrorCode.TODO_NOT_FOUND, "Todo not found"),
        )

    # 2. Reminder prüfen
    reminder = db.get(TodoReminder, reminder_id)
    if not reminder or reminder.todo_id != todo_id:
        raise HTTPException(
            status_code=404,
            detail=error_detail(ErrorCode.REMINDER_NOT_FOUND, "Reminder not found"),
        )

    # 3. Löschen (Todo-Version erhöhen, siehe create_reminder)
    db.delete(reminder)
    todo.updated_at = datetime.now(timezone.utc)
    db.commit()

    # 4. Todo neu laden
    db.refresh(todo)
    db.refresh(todo, attribute_names=["reminders"])
    emit_to_household_sync(household_id, "todo_updated", _todo_response(todo))
