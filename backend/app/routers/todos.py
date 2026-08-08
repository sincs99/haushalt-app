import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import HouseholdMember, Todo
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class TodoCreate(BaseModel):
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


class TodoUpdate(BaseModel):
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

    model_config = ConfigDict(from_attributes=True)


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
    query = db.query(Todo).filter(Todo.household_id == household_id)

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
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    todo = Todo(
        household_id=household_id,
        title=body.title,
        description=body.description,
        assigned_to_user_id=body.assigned_to_user_id,
        due_date=body.due_date,
        tags=body.tags,
        created_by_user_id=membership.user_id,
    )
    db.add(todo)
    db.commit()
    db.refresh(todo)

    emit_to_household_sync(
        household_id,
        "todo_created",
        TodoResponse.model_validate(todo).model_dump(mode="json"),
    )
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
    item = db.get(Todo, todo_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Todo not found in this household",
        )

    update_data = body.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(item, field, value)

    # done_at Logik
    if "is_done" in update_data:
        if update_data["is_done"] is True:
            item.done_at = datetime.now(timezone.utc)
        else:
            item.done_at = None

    db.commit()
    db.refresh(item)

    emit_to_household_sync(
        household_id,
        "todo_updated",
        TodoResponse.model_validate(item).model_dump(mode="json"),
    )
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
    item = db.get(Todo, todo_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.TODO_NOT_FOUND, "Todo not found in this household"),
        )

    # Atomares UPDATE: nur wenn assigned_to_user_id noch NULL ist (TOCTOU-sicher)
    result = db.execute(
        update(Todo)
        .where(Todo.id == todo_id, Todo.assigned_to_user_id.is_(None))
        .values(assigned_to_user_id=membership.user_id)
    )

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.TODO_ALREADY_CLAIMED, "Todo is already assigned"),
        )

    db.commit()
    db.refresh(item)

    emit_to_household_sync(
        household_id,
        "todo_updated",
        TodoResponse.model_validate(item).model_dump(mode="json"),
    )
    return item
