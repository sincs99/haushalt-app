"""
Lokaler Dateispeicher-Service.

Speichert Dateien im Filesystem unter UPLOAD_DIR (Default: data/uploads).
Schnittstelle bewusst schmal — später kommt SupabaseStorageService.
"""

import os
import uuid
from pathlib import Path
from typing import BinaryIO


class LocalStorageService:
    """Filesystem-basierter Storage-Service."""

    def __init__(self, upload_dir: str | None = None):
        self.upload_dir = Path(upload_dir or os.getenv("UPLOAD_DIR", "data/uploads"))

    def _safe_path(self, storage_path: str) -> Path:
        """Stellt sicher, dass der Pfad innerhalb des Upload-Verzeichnisses liegt."""
        abs_path = (self.upload_dir / storage_path).resolve()
        upload_root = self.upload_dir.resolve()
        if not str(abs_path).startswith(str(upload_root)):
            raise ValueError(f"Path traversal detected: {storage_path}")
        return abs_path

    def save(self, household_id: str, filename: str, data: bytes, ext: str) -> str:
        """Speichert Datei, gibt relativen storage_path zurück.

        Pfad-Konvention: {household_id}/{uuid}{ext}
        """
        rel_dir = Path(household_id)
        unique_name = f"{uuid.uuid4()}{ext}"
        rel_path = rel_dir / unique_name

        abs_path = self._safe_path(str(rel_path))
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(data)

        return str(rel_path)

    def open(self, storage_path: str) -> BinaryIO:
        """Öffnet gespeicherte Datei."""
        abs_path = self._safe_path(storage_path)
        return abs_path.open("rb")  # type: ignore[return-value]

    def delete(self, storage_path: str) -> None:
        """Löscht Datei vom Filesystem."""
        abs_path = self._safe_path(storage_path)
        if abs_path.exists():
            abs_path.unlink()
