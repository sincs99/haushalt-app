"""
Files Router — Upload, Download, Delete von Dateien pro Household.

MIME-Whitelist: image/jpeg, image/png, image/webp, application/pdf
Max 10 MB. Bilder werden mit Pillow validiert und auf max 1600px verkleinert.
"""

import io
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import BinaryIO
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Document, DocumentFile, HouseholdMember, Pet, Plant, StoredFile
from app.services.storage import LocalStorageService
from app.socket_manager import emit_to_household_sync

# Decompression Bomb Schutz: max 25 Megapixel
Image.MAX_IMAGE_PIXELS = 25_000_000

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
PILLOW_FORMATS = ["JPEG", "PNG", "WEBP"]
PDF_MAGIC = b"%PDF-"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
CHUNK_SIZE = 64 * 1024  # 64 KB
MAX_IMAGE_DIMENSION = 1600
JPEG_QUALITY = 85

# ---------------------------------------------------------------------------
# Storage-Service (Singleton-artig)
# ---------------------------------------------------------------------------

_storage = LocalStorageService()

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class StoredFileResponse(BaseModel):
    id: uuid.UUID
    original_name: str
    mime_type: str
    size_bytes: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/files",
    tags=["files"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_filename(name: str) -> str:
    """ASCII-Fallback für Content-Disposition (filename="...")."""
    # Nur ASCII-Alphanumerik, Punkte, Bindestriche, Unterstriche — keine
    # Quotes, CR/LF oder Nicht-Latin-1-Zeichen, die den Header brechen
    sanitized = re.sub(r"[^A-Za-z0-9.\-_]", "_", name)
    return sanitized or "download"


def content_disposition(name: str, disposition: str) -> str:
    """Baut einen sicheren Content-Disposition-Header (RFC 6266 / RFC 5987).

    filename= enthält einen ASCII-Fallback, filename*= den UTF-8-kodierten
    Originalnamen, damit Umlaute etc. beim Download erhalten bleiben.
    """
    fallback = _sanitize_filename(name)
    encoded = quote(name, safe="")
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def read_upload_limited(file: BinaryIO, max_size: int = MAX_FILE_SIZE) -> bytes:
    """Liest den Upload in Chunks und bricht ab, sobald max_size überschritten ist.

    Verhindert, dass beliebig große Uploads komplett in den RAM geladen werden.
    Synchron (auf UploadFile.file), damit Upload-Endpoints als `def` im
    Threadpool laufen und Bildverarbeitung/DB-Zugriffe den Event-Loop nicht blockieren.
    """
    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = file.read(CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_size:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.FILE_TOO_LARGE,
                    f"File exceeds maximum size of {max_size // (1024 * 1024)} MB",
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _process_image(data: bytes, content_type: str) -> tuple[bytes, str, str]:
    """Validiert und verarbeitet Bild: verkleinern, Format konvertieren.

    Returns: (processed_bytes, final_mime_type, file_extension)
    """
    # Nur die erlaubten Decoder zulassen (kleinere Angriffsfläche als alle Pillow-Formate)
    img = Image.open(io.BytesIO(data), formats=PILLOW_FORMATS)
    # Pixel-Limit VOR dem Dekomprimieren prüfen — Pillow warnt zwischen 1x und
    # 2x MAX_IMAGE_PIXELS nur, statt abzubrechen
    if img.width * img.height > Image.MAX_IMAGE_PIXELS:
        raise ValueError("Image exceeds pixel limit")
    img.load()  # Validiert den Bildinhalt vollständig
    img = ImageOps.exif_transpose(img)  # EXIF-Rotation anwenden

    # Transparenz erkennen
    has_transparency = img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )

    # Auf max 1600px längste Kante verkleinern
    max_dim = max(img.size)
    if max_dim > MAX_IMAGE_DIMENSION:
        ratio = MAX_IMAGE_DIMENSION / max_dim
        new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    buf = io.BytesIO()

    if has_transparency:
        # PNG mit Transparenz beibehalten
        if img.mode == "P":
            img = img.convert("RGBA")
        img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf.read(), "image/png", ".png"
    else:
        # Alles andere als JPEG speichern
        if img.mode != "RGB":
            img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
        buf.seek(0)
        return buf.read(), "image/jpeg", ".jpeg"


def validate_upload(raw_data: bytes, content_type: str) -> tuple[bytes, str, str]:
    """Prüft MIME-Typ und Inhalt (Magic Bytes / Pillow), verarbeitet Bilder.

    Der Client-Header allein ist fälschbar, deshalb wird der Inhalt immer
    gegen den deklarierten Typ validiert.

    Returns: (processed_bytes, final_mime_type, file_extension)
    """
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.FILE_TYPE_NOT_ALLOWED,
                f"File type '{content_type}' is not allowed",
            ),
        )

    if content_type in IMAGE_MIME_TYPES:
        try:
            return _process_image(raw_data, content_type)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.FILE_TYPE_NOT_ALLOWED,
                    "File content is not a valid image",
                ),
            )

    # PDF Magic-Byte-Validierung, PDF wird unverändert gespeichert
    if not raw_data.startswith(PDF_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.FILE_TYPE_NOT_ALLOWED, "Invalid PDF file"),
        )
    return raw_data, content_type, ".pdf"


def household_storage_used(db: Session, household_id: uuid.UUID) -> int:
    """Summe aller gespeicherten Dateigrößen eines Haushalts in Bytes."""
    return (
        db.query(func.coalesce(func.sum(StoredFile.size_bytes), 0))
        .filter(StoredFile.household_id == household_id)
        .scalar()
    )


def household_storage_quota() -> int:
    return settings.household_storage_quota_mb * 1024 * 1024


def check_storage_quota(db: Session, household_id: uuid.UUID, incoming_bytes: int) -> None:
    """Wirft STORAGE_QUOTA_EXCEEDED, wenn die neue Datei die Quota sprengen würde."""
    if household_storage_used(db, household_id) + incoming_bytes > household_storage_quota():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.STORAGE_QUOTA_EXCEEDED,
                f"Household storage quota of {settings.household_storage_quota_mb} MB exceeded",
            ),
        )


def store_upload(
    db: Session, household_id: uuid.UUID, user_id: uuid.UUID, file: UploadFile
) -> StoredFile:
    """Liest, validiert und speichert einen Upload; legt den StoredFile-Eintrag an.

    Committet nicht — der Aufrufer entscheidet über die Transaktion.
    """
    # Chunk-basiertes Lesen mit frühzeitigem Abbruch (RAM-Exhaustion-Schutz)
    raw_data = read_upload_limited(file.file)
    processed_data, final_mime, ext = validate_upload(raw_data, file.content_type or "")
    check_storage_quota(db, household_id, len(processed_data))
    original_name = (file.filename or "upload")[:255]

    storage_path = _storage.save(
        household_id=str(household_id),
        filename=original_name,
        data=processed_data,
        ext=ext,
    )

    stored_file = StoredFile(
        household_id=household_id,
        original_name=original_name,
        mime_type=final_mime,
        size_bytes=len(processed_data),
        storage_path=storage_path,
        uploaded_by_user_id=user_id,
    )
    db.add(stored_file)
    db.flush()
    return stored_file


def file_in_use(
    db: Session,
    file_ids: list[uuid.UUID],
    exclude_pet_id: uuid.UUID | None = None,
    exclude_plant_id: uuid.UUID | None = None,
) -> str | None:
    """Prüft, ob eine der Dateien von einem Pet-/Pflanzenfoto oder einem Dokument referenziert wird.

    Gibt eine Beschreibung der ersten Referenz zurück (für die Fehlermeldung), sonst None.
    Eine Datei gehört zu höchstens einem Dokument bzw. Pet — sonst würde das Löschen
    des einen die Datei des anderen mitlöschen.
    """
    pet_query = db.query(Pet).filter(Pet.photo_file_id.in_(file_ids))
    if exclude_pet_id is not None:
        pet_query = pet_query.filter(Pet.id != exclude_pet_id)
    pet_ref = pet_query.first()
    if pet_ref is not None:
        return f"pet '{pet_ref.name}'"

    plant_query = db.query(Plant).filter(Plant.photo_file_id.in_(file_ids))
    if exclude_plant_id is not None:
        plant_query = plant_query.filter(Plant.id != exclude_plant_id)
    plant_ref = plant_query.first()
    if plant_ref is not None:
        return f"plant '{plant_ref.name}'"

    doc_ref = (
        db.query(Document)
        .join(DocumentFile, DocumentFile.document_id == Document.id)
        .filter(DocumentFile.file_id.in_(file_ids))
        .first()
    )
    if doc_ref is not None:
        return f"document '{doc_ref.title}'"
    return None


def file_in_use_error(reference: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=error_detail(ErrorCode.FILE_IN_USE, f"File is referenced by {reference}"),
    )


# Hochgeladene, aber nie einem Pet, einer Pflanze oder einem Dokument zugeordnete Dateien (z.B. Tab
# während eines mehrseitigen Uploads geschlossen) werden nach dieser Frist gelöscht
ORPHAN_FILE_GRACE = timedelta(hours=24)


def delete_orphan_files(db: Session, now: datetime | None = None) -> int:
    """Löscht verwaiste StoredFiles (DB + Storage), die älter als ORPHAN_FILE_GRACE sind.

    Gibt die Anzahl gelöschter Dateien zurück.
    """
    cutoff = (now or datetime.now(timezone.utc)) - ORPHAN_FILE_GRACE
    orphans = (
        db.query(StoredFile)
        .filter(StoredFile.created_at < cutoff)
        .filter(~db.query(Pet.id).filter(Pet.photo_file_id == StoredFile.id).exists())
        .filter(~db.query(Plant.id).filter(Plant.photo_file_id == StoredFile.id).exists())
        .filter(~db.query(DocumentFile.file_id).filter(DocumentFile.file_id == StoredFile.id).exists())
        .all()
    )
    paths = [f.storage_path for f in orphans]
    for f in orphans:
        db.delete(f)
    db.commit()

    for path in paths:
        remove_from_storage(path)
    return len(paths)


def remove_from_storage(storage_path: str) -> None:
    """Best-effort: Physische Datei nach erfolgreichem Commit entfernen."""
    try:
        _storage.delete(storage_path)
    except Exception:
        pass  # Datei wird ggf. zum Waisen, aber DB ist konsistent


def file_response_headers(stored_file: StoredFile) -> dict[str, str]:
    """Sicherheits-Header für Datei-Downloads.

    Nur (re-encodierte) Bilder werden inline ausgeliefert; PDFs als attachment.
    Das Frontend lädt Dateien ohnehin als Blob, die Disposition greift nur bei
    direktem Aufruf der URL.
    """
    disposition = "inline" if stored_file.mime_type in IMAGE_MIME_TYPES else "attachment"
    return {
        "Content-Disposition": content_disposition(stored_file.original_name, disposition),
        "X-Content-Type-Options": "nosniff",
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# POST / — Datei hochladen
@router.post("/", response_model=StoredFileResponse, status_code=status.HTTP_201_CREATED)
def upload_file(
    household_id: uuid.UUID,
    file: UploadFile = File(...),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    stored_file = store_upload(db, household_id, membership.user_id, file)
    db.commit()
    db.refresh(stored_file)

    emit_to_household_sync(
        household_id,
        "file_uploaded",
        StoredFileResponse.model_validate(stored_file).model_dump(mode="json"),
    )

    return stored_file


# GET /{file_id} — Datei herunterladen
@router.get("/{file_id}")
def download_file(
    household_id: uuid.UUID,
    file_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    stored_file = db.get(StoredFile, file_id)
    if stored_file is None or stored_file.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.FILE_NOT_FOUND, "File not found in this household"
            ),
        )

    try:
        file_handle = _storage.open(stored_file.storage_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.FILE_NOT_FOUND, "File not found on storage"
            ),
        )

    return StreamingResponse(
        file_handle,
        media_type=stored_file.mime_type,
        headers=file_response_headers(stored_file),
    )


# DELETE /{file_id} — Datei löschen
@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(
    household_id: uuid.UUID,
    file_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    stored_file = db.get(StoredFile, file_id)
    if stored_file is None or stored_file.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.FILE_NOT_FOUND, "File not found in this household"
            ),
        )

    # Referenzprüfung: Pet-/Pflanzenfoto oder Dokumentseite? (Löschen dann über /pets, /plants bzw. /documents)
    reference = file_in_use(db, [file_id])
    if reference is not None:
        raise file_in_use_error(reference)

    # Pfad merken, dann DB-Eintrag zuerst löschen
    storage_path = stored_file.storage_path
    db.delete(stored_file)
    db.commit()

    remove_from_storage(storage_path)

    emit_to_household_sync(
        household_id,
        "file_deleted",
        {"id": str(file_id)},
    )
