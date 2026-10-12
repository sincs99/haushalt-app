"""
Periodisches Aufräumen verwaister Uploads.

Dateien werden zuerst über /files hochgeladen und danach einem Pet, einer Pflanze oder einem Dokument
zugeordnet. Bricht der Client dazwischen ab (Tab geschlossen, Netzwerkfehler),
bleibt die Datei ohne Referenz liegen und zählt weiter zur Speicher-Quota.

Zweiter Schritt: Upload-Ordner (``UPLOAD_DIR/<household_id>/``) gelöschter Haushalte.
Normalerweise löscht ``POST /leave`` sie direkt; liegen bleiben sie nur, wenn das
fehlschlägt oder ein Haushalt ohne App-Code verschwindet (Migration hh1a2b3c4d5e
löscht verwaiste Haushalte mit 0 Mitgliedern, CASA-10).
"""

import asyncio
import logging
import uuid

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Household
from app.routers.files import _storage, delete_orphan_files, delete_untracked_storage_files
from app.services.storage import LocalStorageService

logger = logging.getLogger("uvicorn.error")

CLEANUP_INTERVAL_SECONDS = 60 * 60


def delete_orphan_household_dirs(db: Session, storage: LocalStorageService | None = None) -> int:
    """Löscht Upload-Ordner, deren Haushalt nicht (mehr) existiert. Gibt die Anzahl zurück.

    Erst die Ordner auflisten, DANACH die Haushalte abfragen: Ein Haushalt, der
    dazwischen entsteht, hat in der Liste noch keinen Ordner. Ordnernamen, die keine
    UUID sind, werden nie angefasst.
    """
    storage = storage or _storage
    root = storage.upload_dir
    if not root.is_dir():
        return 0
    candidates: dict[uuid.UUID, str] = {}
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        try:
            candidates[uuid.UUID(entry.name)] = entry.name
        except ValueError:
            continue
    if not candidates:
        return 0
    existing = {
        row[0] for row in db.query(Household.id).filter(Household.id.in_(list(candidates))).all()
    }
    deleted = 0
    for household_id, name in candidates.items():
        if household_id in existing:
            continue
        try:
            storage.delete_household(name)
            deleted += 1
        except Exception:
            logger.warning("Could not delete upload dir of deleted household %s", name, exc_info=True)
    return deleted


def run_once() -> None:
    db = SessionLocal()
    try:
        deleted = delete_orphan_files(db)
        if deleted:
            logger.info("Deleted %d orphaned uploaded file(s)", deleted)
        # Dateien auf der Platte ohne DB-Zeile (Commit nach dem Schreiben gescheitert)
        untracked = delete_untracked_storage_files(db)
        if untracked:
            logger.info("Deleted %d untracked file(s) from storage", untracked)
    except Exception:
        db.rollback()
        logger.exception("Orphan file cleanup failed")
    try:
        dirs = delete_orphan_household_dirs(db)
        if dirs:
            logger.info("Deleted upload dirs of %d deleted household(s)", dirs)
    except Exception:
        db.rollback()
        logger.exception("Household upload dir cleanup failed")
    finally:
        db.close()


async def cleanup_loop() -> None:
    while True:
        # Erst warten: beim Start ist nichts dringend, und kurze Starts (Tests) bleiben unberührt
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        # Sync-DB + Filesystem → Thread, damit der Event-Loop frei bleibt
        await asyncio.to_thread(run_once)
