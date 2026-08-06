"""Gemeinsame Invite-Code-Generierung mit Eindeutigkeits-Prüfung."""
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode, error_detail
from app.core.security import generate_invite_code
from app.models import Household

logger = logging.getLogger(__name__)
MAX_RETRIES = 5


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
