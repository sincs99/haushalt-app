"""
Documents Router — Ablage für Verträge, Rechnungen, Garantien etc. pro Household.

Jedes Dokument referenziert genau eine StoredFile. Dateien werden entweder
vorab über /files hochgeladen (POST / mit file_id) oder direkt per Multipart
(POST /upload). Beim Löschen eines Dokuments wird die Datei mit entfernt.
"""

import uuid
from datetime import date, datetime
from pathlib import PurePath
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Document, HouseholdMember, Pet, StoredFile
from app.routers.files import (
    StoredFileResponse,
    household_storage_quota,
    household_storage_used,
    remove_from_storage,
    store_upload,
)
from app.socket_manager import emit_to_household_sync

DocumentCategory = Literal["contract", "invoice", "warranty", "insurance", "other"]

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


def _strip_title(v):
    if v is None:
        return v
    if not v.strip():
        raise ValueError("Title must not be blank")
    return v.strip()


def _normalize_notes(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


class DocumentMeta(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    category: DocumentCategory = "other"
    notes: str | None = Field(None, max_length=2000)
    document_date: date | None = None
    expiry_date: date | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v):
        return _strip_title(v)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_empty_notes(cls, v):
        return _normalize_notes(v)


class DocumentCreate(DocumentMeta):
    file_id: uuid.UUID


class DocumentUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=150)
    category: DocumentCategory | None = None
    notes: str | None = Field(None, max_length=2000)
    document_date: date | None = None
    expiry_date: date | None = None

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, v):
        return _strip_title(v)

    @field_validator("notes", mode="before")
    @classmethod
    def normalize_empty_notes(cls, v):
        return _normalize_notes(v)

    @model_validator(mode="after")
    def required_fields_not_null(self):
        for name in ("title", "category"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} must not be null")
        return self


class DocumentResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    title: str
    category: DocumentCategory
    notes: str | None
    document_date: date | None
    expiry_date: date | None
    file: StoredFileResponse
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class StorageUsageResponse(BaseModel):
    used_bytes: int
    quota_bytes: int


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/documents",
    tags=["documents"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_document_or_404(db: Session, document_id: uuid.UUID, household_id: uuid.UUID) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.DOCUMENT_NOT_FOUND, "Document not found in this household"),
        )
    return doc


def _emit(household_id: uuid.UUID, event: str, doc: Document) -> None:
    emit_to_household_sync(
        household_id,
        event,
        DocumentResponse.model_validate(doc).model_dump(mode="json"),
    )


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ---------------------------------------------------------------------------
# GET  /  — Liste (Filter: Kategorie, Titelsuche; paginiert)
# ---------------------------------------------------------------------------
@router.get("/", response_model=DocumentListResponse)
def list_documents(
    household_id: uuid.UUID,
    category: DocumentCategory | None = Query(None),
    q: str | None = Query(None, max_length=150),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    query = db.query(Document).filter(Document.household_id == household_id)
    if category is not None:
        query = query.filter(Document.category == category)
    if q and q.strip():
        query = query.filter(Document.title.ilike(f"%{_escape_like(q.strip())}%", escape="\\"))

    total = query.count()
    items = (
        query.order_by(Document.created_at.desc(), Document.id)
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"items": items, "total": total}


# ---------------------------------------------------------------------------
# GET  /storage  — Speicherverbrauch des Haushalts
# ---------------------------------------------------------------------------
@router.get("/storage", response_model=StorageUsageResponse)
def get_storage_usage(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return {
        "used_bytes": household_storage_used(db, household_id),
        "quota_bytes": household_storage_quota(),
    }


# ---------------------------------------------------------------------------
# GET  /{document_id}  — Einzelnes Dokument
# ---------------------------------------------------------------------------
@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    household_id: uuid.UUID,
    document_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return _get_document_or_404(db, document_id, household_id)


# ---------------------------------------------------------------------------
# POST /  — Dokument aus bereits hochgeladener Datei anlegen
# ---------------------------------------------------------------------------
@router.post("/", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(
    household_id: uuid.UUID,
    body: DocumentCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    stored_file = db.get(StoredFile, body.file_id)
    if stored_file is None or stored_file.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.FILE_MISMATCH,
                "File not found or does not belong to this household",
            ),
        )

    # Eine Datei gehört zu höchstens einem Dokument und nicht gleichzeitig einem Pet
    in_use = (
        db.query(Document.id).filter(Document.file_id == body.file_id).first()
        or db.query(Pet.id).filter(Pet.photo_file_id == body.file_id).first()
    )
    if in_use is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.FILE_IN_USE, "File is already in use"),
        )

    doc = Document(
        household_id=household_id,
        created_by_user_id=membership.user_id,
        **body.model_dump(),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    _emit(household_id, "document_created", doc)
    return doc


# ---------------------------------------------------------------------------
# POST /upload  — Datei + Metadaten in einem Multipart-Request
# ---------------------------------------------------------------------------
@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    household_id: uuid.UUID,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    category: str = Form("other"),
    notes: str | None = Form(None),
    document_date: str | None = Form(None),
    expiry_date: str | None = Form(None),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Metadaten vor dem Upload validieren; ohne Titel → Dateiname ohne Endung
    fallback_title = PurePath(file.filename or "").stem[:150] or "Document"
    try:
        meta = DocumentMeta.model_validate(
            {
                "title": title if title and title.strip() else fallback_title,
                "category": category,
                "notes": notes,
                "document_date": document_date or None,
                "expiry_date": expiry_date or None,
            }
        )
    except ValidationError as e:
        raise RequestValidationError(e.errors(include_url=False))

    stored_file = await store_upload(db, household_id, membership.user_id, file)
    doc = Document(
        household_id=household_id,
        file_id=stored_file.id,
        created_by_user_id=membership.user_id,
        **meta.model_dump(),
    )
    db.add(doc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        remove_from_storage(stored_file.storage_path)
        raise
    db.refresh(doc)

    _emit(household_id, "document_created", doc)
    return doc


# ---------------------------------------------------------------------------
# PATCH /{document_id}  — Metadaten aktualisieren (partial update)
# ---------------------------------------------------------------------------
@router.patch("/{document_id}", response_model=DocumentResponse)
def update_document(
    household_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DocumentUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    doc = _get_document_or_404(db, document_id, household_id)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)

    db.commit()
    db.refresh(doc)

    _emit(household_id, "document_updated", doc)
    return doc


# ---------------------------------------------------------------------------
# DELETE /{document_id}  — Dokument inkl. Datei löschen
# ---------------------------------------------------------------------------
@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    household_id: uuid.UUID,
    document_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    doc = _get_document_or_404(db, document_id, household_id)
    stored_file = doc.file
    file_id = stored_file.id
    storage_path = stored_file.storage_path

    db.delete(doc)
    db.delete(stored_file)
    db.commit()

    remove_from_storage(storage_path)

    emit_to_household_sync(
        household_id,
        "document_deleted",
        {"id": str(document_id), "file_id": str(file_id)},
    )
