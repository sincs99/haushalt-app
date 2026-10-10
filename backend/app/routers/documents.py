"""
Documents Router — Ablage für Verträge, Rechnungen, Garantien etc. pro Household.

Ein Dokument besteht aus einer oder mehreren Dateien (Seiten, z.B. mehrseitige
Scans). Dateien werden entweder vorab einzeln über /files hochgeladen und dann
per file_ids angehängt (POST /, POST /{id}/files) oder direkt per Multipart
(POST /upload). Beim Löschen eines Dokuments werden alle Dateien mit entfernt.
"""

import uuid
from datetime import date, datetime
from pathlib import PurePath
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy.orm import Session, selectinload

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.core.rate_limit import limiter
from app.database import get_db
from app.models import Document, DocumentFile, HouseholdMember, StoredFile
from app.routers.files import (
    UPLOAD_RATE_LIMIT,
    StoredFileResponse,
    file_in_use,
    file_in_use_error,
    household_storage_quota,
    household_storage_used,
    remove_from_storage,
    store_upload,
)
from app.socket_manager import emit_to_household_sync

DocumentCategory = Literal["contract", "invoice", "warranty", "insurance", "other"]

MAX_FILES_PER_DOCUMENT = 30

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


def _unique_ids(v: list[uuid.UUID]) -> list[uuid.UUID]:
    if len(set(v)) != len(v):
        raise ValueError("file_ids must be unique")
    return v


class DocumentCreate(DocumentMeta):
    file_ids: list[uuid.UUID] = Field(..., min_length=1)

    @field_validator("file_ids")
    @classmethod
    def file_ids_unique(cls, v):
        return _unique_ids(v)


class DocumentFilesBody(BaseModel):
    file_ids: list[uuid.UUID] = Field(..., min_length=1)

    @field_validator("file_ids")
    @classmethod
    def file_ids_unique(cls, v):
        return _unique_ids(v)


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
    files: list[StoredFileResponse]
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


def _too_many_files() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=error_detail(
            ErrorCode.DOCUMENT_TOO_MANY_FILES,
            f"A document can have at most {MAX_FILES_PER_DOCUMENT} files",
        ),
    )


def _claim_files(db: Session, household_id: uuid.UUID, file_ids: list[uuid.UUID]) -> list[StoredFile]:
    """Prüft, dass alle Dateien zum Haushalt gehören und noch frei sind.

    Eine Datei gehört zu höchstens einem Dokument und nicht gleichzeitig einem Pet.
    """
    files = db.query(StoredFile).filter(StoredFile.id.in_(file_ids)).all()
    by_id = {f.id: f for f in files}
    if len(by_id) != len(file_ids) or any(f.household_id != household_id for f in files):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.FILE_MISMATCH,
                "File not found or does not belong to this household",
            ),
        )

    reference = file_in_use(db, file_ids)
    if reference is not None:
        raise file_in_use_error(reference)
    return [by_id[fid] for fid in file_ids]


def _append_files(doc: Document, files: list[StoredFile]) -> None:
    if len(doc.file_links) + len(files) > MAX_FILES_PER_DOCUMENT:
        raise _too_many_files()
    start = max((link.position for link in doc.file_links), default=-1) + 1
    for offset, f in enumerate(files):
        doc.file_links.append(DocumentFile(file=f, position=start + offset))


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
        # Seiten + Dateien in zwei Zusatz-Queries statt pro Dokument nachladen (N+1)
        query.options(selectinload(Document.file_links).selectinload(DocumentFile.file))
        .order_by(Document.created_at.desc(), Document.id)
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
        "quota_bytes": household_storage_quota(db, household_id),
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
# POST /  — Dokument aus bereits hochgeladenen Dateien anlegen
# ---------------------------------------------------------------------------
@router.post("/", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
def create_document(
    household_id: uuid.UUID,
    body: DocumentCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    if len(body.file_ids) > MAX_FILES_PER_DOCUMENT:
        raise _too_many_files()
    files = _claim_files(db, household_id, body.file_ids)

    doc = Document(
        household_id=household_id,
        created_by_user_id=membership.user_id,
        **body.model_dump(exclude={"file_ids"}),
    )
    _append_files(doc, files)
    db.add(doc)
    db.commit()
    db.refresh(doc)

    _emit(household_id, "document_created", doc)
    return doc


# ---------------------------------------------------------------------------
# POST /upload  — Dateien + Metadaten in einem Multipart-Request
#
# Für API-Clients mit wenigen Seiten. Der Request-Body ist durch nginx begrenzt
# (client_max_body_size); große mehrseitige Dokumente seitenweise über /files
# hochladen und per POST / mit file_ids anlegen (so macht es das Frontend).
# ---------------------------------------------------------------------------
@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(UPLOAD_RATE_LIMIT)
def upload_document(
    request: Request,
    household_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    title: str | None = Form(None),
    category: str = Form("other"),
    notes: str | None = Form(None),
    document_date: str | None = Form(None),
    expiry_date: str | None = Form(None),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    if len(files) > MAX_FILES_PER_DOCUMENT:
        raise _too_many_files()

    # Metadaten vor dem Upload validieren; ohne Titel → erster Dateiname ohne Endung
    fallback_title = PurePath(files[0].filename or "").stem[:150] or "Document"
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

    doc = Document(
        household_id=household_id,
        created_by_user_id=membership.user_id,
        **meta.model_dump(),
    )
    stored: list[StoredFile] = []
    try:
        for upload in files:
            stored.append(store_upload(db, household_id, membership.user_id, upload))
        _append_files(doc, stored)
        db.add(doc)
        db.commit()
    except Exception:
        # Alles oder nichts: bereits gespeicherte Dateien wieder entfernen
        db.rollback()
        for f in stored:
            remove_from_storage(f.storage_path)
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

    old_expiry = doc.expiry_date
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)
    if doc.expiry_date != old_expiry:
        # Neues Ablaufdatum → Erinnerungen neu planen
        doc.expiry_soon_notified_at = None
        doc.expiry_notified_at = None

    db.commit()
    db.refresh(doc)

    _emit(household_id, "document_updated", doc)
    return doc


# ---------------------------------------------------------------------------
# POST /{document_id}/files  — Bereits hochgeladene Dateien als Seiten anhängen
# ---------------------------------------------------------------------------
@router.post("/{document_id}/files", response_model=DocumentResponse)
def add_document_files(
    household_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DocumentFilesBody,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    doc = _get_document_or_404(db, document_id, household_id)
    _append_files(doc, _claim_files(db, household_id, body.file_ids))
    db.commit()
    db.refresh(doc)

    _emit(household_id, "document_updated", doc)
    return doc


# ---------------------------------------------------------------------------
# PUT /{document_id}/files/order  — Seiten neu anordnen
# ---------------------------------------------------------------------------
@router.put("/{document_id}/files/order", response_model=DocumentResponse)
def reorder_document_files(
    household_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DocumentFilesBody,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    doc = _get_document_or_404(db, document_id, household_id)
    links = {link.file_id: link for link in doc.file_links}
    if set(body.file_ids) != set(links) or len(body.file_ids) != len(links):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.FILE_MISMATCH,
                "file_ids must contain exactly the files of this document",
            ),
        )
    for position, file_id in enumerate(body.file_ids):
        links[file_id].position = position
    db.commit()
    db.expire(doc, ["file_links"])

    _emit(household_id, "document_updated", doc)
    return doc


# ---------------------------------------------------------------------------
# DELETE /{document_id}/files/{file_id}  — Einzelne Seite inkl. Datei löschen
# ---------------------------------------------------------------------------
@router.delete("/{document_id}/files/{file_id}", response_model=DocumentResponse)
def remove_document_file(
    household_id: uuid.UUID,
    document_id: uuid.UUID,
    file_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    doc = _get_document_or_404(db, document_id, household_id)
    link = next((link for link in doc.file_links if link.file_id == file_id), None)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.FILE_NOT_FOUND, "File is not part of this document"),
        )
    if len(doc.file_links) == 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.DOCUMENT_LAST_FILE,
                "A document needs at least one file; delete the document instead",
            ),
        )

    stored_file = link.file
    storage_path = stored_file.storage_path
    doc.file_links.remove(link)
    db.delete(stored_file)
    db.commit()
    db.refresh(doc)

    remove_from_storage(storage_path)

    _emit(household_id, "document_updated", doc)
    return doc


# ---------------------------------------------------------------------------
# DELETE /{document_id}  — Dokument inkl. aller Dateien löschen
# ---------------------------------------------------------------------------
@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    household_id: uuid.UUID,
    document_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    doc = _get_document_or_404(db, document_id, household_id)
    files = doc.files
    file_ids = [str(f.id) for f in files]
    storage_paths = [f.storage_path for f in files]

    db.delete(doc)
    for f in files:
        db.delete(f)
    db.commit()

    for path in storage_paths:
        remove_from_storage(path)

    emit_to_household_sync(
        household_id,
        "document_deleted",
        {"id": str(document_id), "file_ids": file_ids},
    )
