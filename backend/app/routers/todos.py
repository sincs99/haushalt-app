import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import exists, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, selectinload

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.core.patch_schema import PatchModel
from app.database import get_db
from app.models import Household, HouseholdMember, Todo, TodoAssignee, TodoReminder
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


# Obergrenze Zuständige pro Aufgabe (Haushalte sind klein; schützt vor Riesen-Bodies)
MAX_ASSIGNEES = 10


def _dedupe(ids: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
    return None if ids is None else list(dict.fromkeys(ids))


class TodoCreate(BaseModel):
    # Optional client-generierte ID → idempotenter Create (Offline-Sync)
    id: uuid.UUID | None = None
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    # Zuständige; leer = offen für alle
    assignee_ids: list[uuid.UUID] | None = Field(None, max_length=MAX_ASSIGNEES)
    # Veraltet (alte PWA): eine Person → assignee_ids=[id]; assignee_ids hat Vorrang
    assigned_to_user_id: uuid.UUID | None = None
    due_date: datetime | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("assignee_ids")
    @classmethod
    def dedupe_assignees(cls, v):
        return _dedupe(v)

    def resolved_assignee_ids(self) -> list[uuid.UUID]:
        if self.assignee_ids is not None:
            return self.assignee_ids
        return [self.assigned_to_user_id] if self.assigned_to_user_id else []

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
    # null auf NOT-NULL-Spalten von Todo → 422 (app/core/patch_schema.py);
    # assignee_ids: null → 422 ("niemand" ist die leere Liste)
    __orm_model__ = Todo
    __extra_non_nullable__ = ("assignee_ids",)

    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    # Ersetzt die Menge der Zuständigen
    assignee_ids: list[uuid.UUID] | None = Field(None, max_length=MAX_ASSIGNEES)
    # Veraltet (alte PWA): id → [id], null → [] (niemand); assignee_ids hat Vorrang
    assigned_to_user_id: uuid.UUID | None = None
    due_date: datetime | None = None
    is_done: bool | None = None
    tags: list[str] | None = Field(None, max_length=20)

    @field_validator("assignee_ids")
    @classmethod
    def dedupe_assignees(cls, v):
        return _dedupe(v)

    def resolved_assignee_ids(self) -> list[uuid.UUID] | None:
        """Neue Menge der Zuständigen oder None (= nicht ändern)."""
        if "assignee_ids" in self.model_fields_set:
            return self.assignee_ids
        if "assigned_to_user_id" in self.model_fields_set:
            return [self.assigned_to_user_id] if self.assigned_to_user_id else []
        return None

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
    assignee_ids: list[uuid.UUID]
    # Veraltet: erste zuständige Person (nur für alte PWA-Versionen, wird entfernt)
    assigned_to_user_id: uuid.UUID | None
    due_date: datetime | None
    is_done: bool
    # Wer abgehakt hat (eine:r für alle)
    done_by_user_id: uuid.UUID | None
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


def _load_todo(db: Session, household_id: uuid.UUID, todo_id: uuid.UUID) -> Todo | None:
    return (
        db.query(Todo)
        .options(selectinload(Todo.reminders), selectinload(Todo.assignee_links))
        .filter(Todo.id == todo_id, Todo.household_id == household_id)
        .first()
    )


def _reload(db: Session, todo: Todo) -> None:
    db.refresh(todo)
    db.refresh(todo, attribute_names=["reminders", "assignee_links"])


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
        .options(selectinload(Todo.reminders), selectinload(Todo.assignee_links))
        .filter(Todo.household_id == household_id)
    )

    if not include_done:
        query = query.filter(Todo.is_done == False)  # noqa: E712

    if assigned_to_me:
        # "Meine": ich bin eine der zuständigen Personen
        query = query.filter(
            exists().where(TodoAssignee.todo_id == Todo.id, TodoAssignee.user_id == membership.user_id)
        )

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

    # Zuständige müssen Mitglieder sein (CASA-21; sonst 500 bei unbekannter ID
    # bzw. eine Aufgabe, die niemandem zählt)
    assignee_ids = body.resolved_assignee_ids()
    if assignee_ids:
        assert_users_in_household(db, household_id, assignee_ids)

    todo = Todo(
        household_id=household_id,
        title=body.title,
        description=body.description,
        due_date=body.due_date,
        tags=body.tags,
        created_by_user_id=membership.user_id,
    )
    if body.id is not None:
        todo.id = body.id
    todo.assignee_ids = assignee_ids
    db.add(todo)
    existing = commit_or_get_existing(db, Todo, body.id, household_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing
    _reload(db, todo)

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
    item = _load_todo(db, household_id, todo_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found in this household",
        )

    update_data = body.model_dump(exclude_unset=True)
    new_assignees = body.resolved_assignee_ids()
    update_data.pop("assignee_ids", None)
    update_data.pop("assigned_to_user_id", None)

    # Neu hinzukommende Zuständige müssen Mitglied sein; Ex-Mitglieder, die schon
    # eingetragen sind, dürfen beim Speichern stehen bleiben (CASA-21)
    if new_assignees:
        assert_users_allowed(db, household_id, new_assignees, set(item.assignee_ids))

    was_done = item.is_done
    for field, value in update_data.items():
        setattr(item, field, value)
    if new_assignees is not None:
        item.assignee_ids = new_assignees

    # done_at/done_by Logik ("eine:r für alle": wer abhakt, erledigt für alle).
    # Erinnerungen werden beim Erledigen NICHT als gesendet markiert
    # (der Scheduler überspringt erledigte Todos) — sonst wären sie nach „Rückgängig“
    # still verloren (CASA-06).
    if "is_done" in update_data:
        if update_data["is_done"] is True:
            if not was_done:
                item.done_at = datetime.now(timezone.utc)
                item.done_by_user_id = membership.user_id
        else:
            item.done_at = None
            item.done_by_user_id = None
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
    _reload(db, item)

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
# POST /{todo_id}/claim  — "Ich übernehme": mich zu den Zuständigen hinzufügen
# ---------------------------------------------------------------------------
@router.post("/{todo_id}/claim", response_model=TodoResponse)
def claim_todo(
    household_id: uuid.UUID,
    todo_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Fügt die aufrufende Person hinzu — auch wenn schon andere zuständig sind.

    Idempotent: bereits eingetragen → 200 ohne Änderung (kein Event). Parallele
    Claims sind über den PK (todo_id, user_id) und ON CONFLICT DO NOTHING sicher.
    """
    item = _load_todo(db, household_id, todo_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.TODO_NOT_FOUND, "Todo not found in this household"),
        )
    if item.is_done:
        raise HTTPException(
            status_code=422,
            detail=error_detail(ErrorCode.TODO_IS_DONE, "Cannot claim a done todo"),
        )

    insert = postgresql.insert if db.get_bind().dialect.name == "postgresql" else sqlite.insert
    result = db.execute(
        insert(TodoAssignee)
        .values(
            todo_id=todo_id,
            user_id=membership.user_id,
            household_id=household_id,
            created_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(index_elements=["todo_id", "user_id"])
    )
    if result.rowcount == 1:
        # Core-Statements umgehen den ORM-Hook → version selbst erhöhen
        db.execute(
            update(Todo)
            .where(Todo.id == todo_id)
            .values(version=Todo.version + 1, updated_at=datetime.now(timezone.utc))
        )
    db.commit()
    _reload(db, item)

    if result.rowcount == 1:
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
    _reload(db, todo)
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
    _reload(db, todo)
    emit_to_household_sync(household_id, "todo_updated", _todo_response(todo))
