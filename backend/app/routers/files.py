"""
Files Router — Upload, Download, Delete von Dateien pro Household.

MIME-Whitelist: image/jpeg, image/png, image/webp, application/pdf
Max 10 MB. Bilder werden mit Pillow validiert und auf max 1600px verkleinert.
"""

import io
import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import HouseholdMember, Pet, StoredFile
from app.services.storage import LocalStorageService
from app.socket_manager import emit_to_household_sync

# Decompression Bomb Schutz: max 25 Megapixel
Image.MAX_IMAGE_PIXELS = 25_000_000

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
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
    """Entfernt unsichere Zeichen aus Dateinamen für Content-Disposition."""
    # Nur alphanumerische Zeichen, Punkte, Bindestriche, Unterstriche
    sanitized = re.sub(r'[^\w.\-]', '_', name)
    return sanitized or "download"


def _process_image(data: bytes, content_type: str) -> tuple[bytes, str, str]:
    """Validiert und verarbeitet Bild: verkleinern, Format konvertieren.

    Returns: (processed_bytes, final_mime_type, file_extension)
    """
    img = Image.open(io.BytesIO(data))
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# POST / — Datei hochladen
@router.post("/", response_model=StoredFileResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    household_id: uuid.UUID,
    file: UploadFile = File(...),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Chunk-basiertes Lesen mit frühzeitigem Abbruch (RAM-Exhaustion-Schutz)
    chunks: list[bytes] = []
    total_size = 0
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.FILE_TOO_LARGE,
                    f"File exceeds maximum size of {MAX_FILE_SIZE // (1024 * 1024)} MB",
                ),
            )
        chunks.append(chunk)
    raw_data = b"".join(chunks)

    # MIME-Typ-Prüfung
    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.FILE_TYPE_NOT_ALLOWED,
                f"File type '{content_type}' is not allowed",
            ),
        )

    # PDF Magic-Byte-Validierung
    if content_type == "application/pdf":
        if not raw_data[:5] == b"%PDF-":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.FILE_TYPE_NOT_ALLOWED, "Invalid PDF file"
                ),
            )

    original_name = file.filename or "upload"

    # Bildverarbeitung
    if content_type in IMAGE_MIME_TYPES:
        try:
            processed_data, final_mime, ext = _process_image(raw_data, content_type)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.FILE_TYPE_NOT_ALLOWED,
                    "File content is not a valid image",
                ),
            )
    else:
        # PDF unverändert speichern
        processed_data = raw_data
        final_mime = content_type
        ext = ".pdf"

    # Speichern
    storage_path = _storage.save(
        household_id=str(household_id),
        filename=original_name,
        data=processed_data,
        ext=ext,
    )

    # DB-Eintrag
    stored_file = StoredFile(
        household_id=household_id,
        original_name=original_name,
        mime_type=final_mime,
        size_bytes=len(processed_data),
        storage_path=storage_path,
        uploaded_by_user_id=membership.user_id,
    )
    db.add(stored_file)
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

    safe_name = _sanitize_filename(stored_file.original_name)

    return StreamingResponse(
        file_handle,
        media_type=stored_file.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"'
        },
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

    # Referenzprüfung: Wird die Datei von einem Pet referenziert?
    pet_ref = db.query(Pet).filter(Pet.photo_file_id == file_id).first()
    if pet_ref is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.FILE_IN_USE,
                f"File is referenced by pet '{pet_ref.name}'",
            ),
        )

    # Pfad merken, dann DB-Eintrag zuerst löschen
    storage_path = stored_file.storage_path
    db.delete(stored_file)
    db.commit()

    # Best-effort: Physische Datei nach erfolgreichem Commit entfernen
    try:
        _storage.delete(storage_path)
    except Exception:
        pass  # Datei wird ggf. zum Waisen, aber DB ist konsistent

    emit_to_household_sync(
        household_id,
        "file_deleted",
        {"id": str(file_id)},
    )
