"""
Lokaler Dateispeicher-Service.

Speichert Dateien im Filesystem unter UPLOAD_DIR (Default: data/uploads).
Schnittstelle bewusst schmal — später kommt SupabaseStorageService.
"""

import logging
import os
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO

logger = logging.getLogger(__name__)


def canonical_storage_path(storage_path: str) -> str:
    """Use portable relative keys, including paths written by older Windows builds."""
    path = PurePosixPath(storage_path.replace("\\", "/"))
    if (
        path.is_absolute()
        or PureWindowsPath(storage_path).drive
        or ".." in path.parts
        or not path.parts
        or any(":" in part for part in path.parts)
    ):
        raise ValueError(f"Invalid relative storage path: {storage_path}")
    return path.as_posix()


class LocalStorageService:
    """Filesystem-basierter Storage-Service."""

    def __init__(self, upload_dir: str | None = None):
        self.upload_dir = Path(upload_dir or os.getenv("UPLOAD_DIR", "data/uploads"))

    def _safe_path(self, storage_path: str) -> Path:
        """Stellt sicher, dass der Pfad innerhalb des Upload-Verzeichnisses liegt."""
        abs_path = (self.upload_dir / canonical_storage_path(storage_path)).resolve()
        upload_root = self.upload_dir.resolve()
        if not abs_path.is_relative_to(upload_root):
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
        # Exclusive creation never overwrites a pre-existing object. If writing
        # fails (e.g. disk full), remove the partial object before propagating.
        created = False
        try:
            target = abs_path.open("xb")
            created = True
            with target:
                target.write(data)
                target.flush()
        except BaseException:
            if created:
                try:
                    abs_path.unlink(missing_ok=True)
                except OSError:
                    logger.exception("Could not remove partial upload %s", rel_path)
            raise

        return canonical_storage_path(str(rel_path))

    def open(self, storage_path: str) -> BinaryIO:
        """Öffnet gespeicherte Datei."""
        abs_path = self._safe_path(storage_path)
        return abs_path.open("rb")  # type: ignore[return-value]

    def delete(self, storage_path: str) -> None:
        """Löscht Datei vom Filesystem."""
        abs_path = self._safe_path(storage_path)
        if abs_path.exists():
            abs_path.unlink()

    def list_files(self) -> Iterator[tuple[str, float]]:
        """Alle gespeicherten Dateien als (storage_path, mtime) — für die Waisen-Bereinigung."""
        root = self.upload_dir.resolve()
        if not root.is_dir():
            return
        for path in root.rglob("*"):
            if path.is_file():
                yield path.relative_to(root).as_posix(), path.stat().st_mtime

    def delete_household(self, household_id: str) -> None:
        """Löscht alle Dateien eines Haushalts (Ordner {household_id}/).

        Erfasst auch Dateien ohne DB-Eintrag (z.B. nach abgebrochenen Uploads).
        """
        abs_path = self._safe_path(household_id)
        if abs_path == self.upload_dir.resolve():
            raise ValueError("Refusing to delete the upload root")
        if abs_path.is_dir():
            shutil.rmtree(abs_path)
