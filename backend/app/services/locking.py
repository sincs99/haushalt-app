"""Zeilensperren für Check-then-Act-Abläufe (F0-2, Ursache von CASA-01/10/20/24/26/…).

Muster: Wer eine Invariante prüft und danach schreibt (z. B. "letzter Admin?",
"Quota frei?", "Kalender leer?"), sperrt zuerst die passende Zeile mit
``SELECT … FOR UPDATE``. Parallele Requests derselben Sperre laufen dann
nacheinander; die Sperre endet mit ``commit()``/``rollback()`` der Session.

- ``lock_household``: grobe Sperre pro Haushalt — für Mitgliedschaft, Kalender,
  Quota und andere haushaltsweite Invarianten. Immer ZUERST sperren (vor anderen
  Zeilen), damit keine Deadlocks durch unterschiedliche Reihenfolgen entstehen.
- ``lock_row``: feine Sperre auf eine einzelne Zeile (z. B. Ausgabe, Kalender).

Beide lesen die Zeile unter der Sperre neu (``populate_existing``), damit keine
veralteten Werte aus der Identity-Map weiterverwendet werden. Auf SQLite (Tests)
rendert SQLAlchemy kein ``FOR UPDATE`` — die Helfer sind dort ein normales SELECT.
"""

import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Household

T = TypeVar("T")


def lock_row(db: Session, model: type[T], row_id: uuid.UUID) -> T | None:
    """Sperrt die Zeile ``model.id == row_id`` bis zum Transaktionsende. None = nicht gefunden."""
    return db.get(model, row_id, with_for_update=True, populate_existing=True)


def lock_household(db: Session, household_id: uuid.UUID) -> Household | None:
    """Sperrt die ``households``-Zeile (serialisiert haushaltsweite Check-then-Act-Abläufe)."""
    return db.execute(
        select(Household)
        .where(Household.id == household_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
