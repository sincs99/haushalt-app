import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import HouseholdMember, Note
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class NoteCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    body: str = Field("", max_length=5000)
    tag: str | None = Field(None, max_length=50)
    pinned: bool = False

    @field_validator("tag", mode="before")
    @classmethod
    def normalize_empty_tag(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v.strip() if isinstance(v, str) else v

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title must not be blank")
        return v.strip()


class NoteUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=150)
    body: str | None = Field(None, max_length=5000)
    tag: str | None = Field(None, max_length=50)
    pinned: bool | None = None

    @field_validator("tag", mode="before")
    @classmethod
    def normalize_empty_tag(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v.strip() if isinstance(v, str) else v

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Title must not be blank")
        return v.strip() if v is not None else v


class NoteResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    title: str
    body: str
    tag: str | None
    pinned: bool
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/notes",
    tags=["notes"],
)


# ---------------------------------------------------------------------------
# GET  /  — Liste aller Notizen
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[NoteResponse])
def list_notes(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return (
        db.query(Note)
        .filter(Note.household_id == household_id)
        .order_by(Note.pinned.desc(), Note.created_at.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# POST /  — Neue Notiz erstellen
# ---------------------------------------------------------------------------
@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(
    household_id: uuid.UUID,
    body: NoteCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    note = Note(
        household_id=household_id,
        title=body.title,
        body=body.body,
        tag=body.tag,
        pinned=body.pinned,
        created_by_user_id=membership.user_id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    emit_to_household_sync(
        household_id,
        "note_created",
        NoteResponse.model_validate(note).model_dump(mode="json"),
    )
    return note


# ---------------------------------------------------------------------------
# PATCH /{note_id}  — Notiz aktualisieren (partial update)
# ---------------------------------------------------------------------------
@router.patch("/{note_id}", response_model=NoteResponse)
def update_note(
    household_id: uuid.UUID,
    note_id: uuid.UUID,
    body: NoteUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = db.get(Note, note_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.NOTE_NOT_FOUND, "Note not found in this household"),
        )

    update_data = body.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(item, field, value)

    db.commit()
    db.refresh(item)

    emit_to_household_sync(
        household_id,
        "note_updated",
        NoteResponse.model_validate(item).model_dump(mode="json"),
    )
    return item


# ---------------------------------------------------------------------------
# DELETE /{note_id}  — Notiz löschen
# ---------------------------------------------------------------------------
@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    household_id: uuid.UUID,
    note_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    item = db.get(Note, note_id)
    if item is None or item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.NOTE_NOT_FOUND, "Note not found in this household"),
        )

    db.delete(item)
    db.commit()

    emit_to_household_sync(
        household_id,
        "note_deleted",
        {"id": str(note_id)},
    )
