"""
Periodisches Aufräumen verwaister Uploads.

Dateien werden zuerst über /files hochgeladen und danach einem Pet, einer Pflanze oder einem Dokument
zugeordnet. Bricht der Client dazwischen ab (Tab geschlossen, Netzwerkfehler),
bleibt die Datei ohne Referenz liegen und zählt weiter zur Speicher-Quota.
"""

import asyncio
import logging

from app.database import SessionLocal
from app.routers.files import delete_orphan_files, delete_untracked_storage_files

logger = logging.getLogger("uvicorn.error")

CLEANUP_INTERVAL_SECONDS = 60 * 60


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
    finally:
        db.close()


async def cleanup_loop() -> None:
    while True:
        # Erst warten: beim Start ist nichts dringend, und kurze Starts (Tests) bleiben unberührt
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        # Sync-DB + Filesystem → Thread, damit der Event-Loop frei bleibt
        await asyncio.to_thread(run_once)
