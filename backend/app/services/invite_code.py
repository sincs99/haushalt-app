"""Gemeinsame Invite-Code-Generierung mit Eindeutigkeits-Prüfung."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode, error_detail
from app.core.security import generate_invite_code
from app.models import Household

logger = logging.getLogger(__name__)
MAX_RETRIES = 5

# Gültigkeitsdauer eines Einladungscodes ab Erzeugung/Rotation (H-12)
INVITE_CODE_TTL = timedelta(days=7)


def new_invite_code_expiry() -> datetime:
    """Ablaufzeitpunkt (UTC) für einen frisch erzeugten Code."""
    return datetime.now(timezone.utc) + INVITE_CODE_TTL


def is_invite_code_expired(household: Household) -> bool:
    """True, wenn der Code abgelaufen ist. NULL = läuft nicht ab."""
    expires_at = household.invite_code_expires_at
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:  # SQLite liefert naive Werte
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def rotate_household_invite_code(db: Session, household: Household) -> None:
    """Setzt neuen Code samt neuem Ablaufdatum (kein Commit)."""
    household.invite_code = generate_unique_invite_code(db)
    household.invite_code_expires_at = new_invite_code_expiry()


def generate_unique_invite_code(db: Session) -> str:
    """Erzeugt einen eindeutigen Invite-Code mit Retry-Logik."""
    for attempt in range(MAX_RETRIES):
        code = generate_invite_code()
        existing = db.query(Household).filter_by(invite_code=code).first()
        if existing is None:
            return code
        if attempt == MAX_RETRIES - 1:
            logger.error(
                "Failed to generate unique invite code after %d attempts",
                MAX_RETRIES,
            )
            raise HTTPException(
                status_code=500,
                detail=error_detail(
                    ErrorCode.INVITE_CODE_GENERATION_FAILED,
                    "Could not generate unique invite code",
                ),
            )
    # Should never reach here, but satisfy type checker
    raise HTTPException(
        status_code=500,
        detail=error_detail(
            ErrorCode.INVITE_CODE_GENERATION_FAILED,
            "Could not generate unique invite code",
        ),
    )
