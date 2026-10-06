"""Client-generierte IDs für idempotente Creates (docs/offline-first-phase2.md, B1).

Offline-fähige Clients erzeugen die UUID einer neuen Entität selbst und senden sie
beim Create mit. Wird derselbe Create wiederholt (Retry nach Timeout, Outbox-Replay),
liefert der Server die bereits existierende Entität zurück statt ein Duplikat anzulegen.
"""

import uuid
from typing import TypeVar

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode, error_detail

T = TypeVar("T")


def get_existing_by_client_id(
    db: Session, model: type[T], client_id: uuid.UUID | None, household_id: uuid.UUID
) -> T | None:
    """Liefert die Entität mit ``client_id`` aus diesem Haushalt oder None.

    Gehört die ID zu einem anderen Haushalt → 409 ohne Details (kein Daten-Leak).
    """
    if client_id is None:
        return None
    existing = db.get(model, client_id)
    if existing is None:
        return None
    if existing.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.ENTITY_ID_CONFLICT, "Id is already in use"),
        )
    return existing


def commit_or_get_existing(
    db: Session, model: type[T], client_id: uuid.UUID | None, household_id: uuid.UUID
) -> T | None:
    """Committet einen neuen Create. Bei PK-Kollision durch parallelen Request mit
    derselben Client-ID wird die konkurrierend angelegte Entität zurückgegeben.

    Rückgabe None = eigener Insert war erfolgreich.
    """
    try:
        db.commit()
        return None
    except IntegrityError:
        db.rollback()
        existing = get_existing_by_client_id(db, model, client_id, household_id)
        if existing is None:
            raise
        return existing
