"""Einmal-Tokens für Konto-Aktionen (Tabelle ``user_tokens``).

Zwecke: ``password_reset`` und ``email_verification``. Der Token selbst steht nur im
Link der E-Mail; in der DB liegt sein SHA-256-Hash. Beim Ausstellen werden ältere,
noch offene Tokens desselben Zwecks entwertet — es gilt immer nur der letzte Link.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User, UserToken

PURPOSE_PASSWORD_RESET = "password_reset"
PURPOSE_EMAIL_VERIFICATION = "email_verification"


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _ttl(purpose: str) -> timedelta:
    if purpose == PURPOSE_PASSWORD_RESET:
        return timedelta(minutes=settings.password_reset_token_minutes)
    return timedelta(hours=settings.email_verification_token_hours)


def issue_token(db: Session, user: User, purpose: str) -> str:
    """Erzeugt einen neuen Token (ohne Commit) und entwertet offene Tokens desselben Zwecks."""
    now = datetime.now(timezone.utc)
    db.flush()  # zuvor hinzugefügte Tokens müssen für das UPDATE sichtbar sein
    db.query(UserToken).filter(
        UserToken.user_id == user.id,
        UserToken.purpose == purpose,
        UserToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    raw = secrets.token_urlsafe(32)
    db.add(
        UserToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=_hash(raw),
            expires_at=now + _ttl(purpose),
        )
    )
    db.flush()
    return raw


def consume_token(db: Session, raw: str, purpose: str) -> User | None:
    """Löst einen Token ein (markiert ihn als benutzt) und liefert den User, sonst None."""
    if not raw or len(raw) > 128:
        return None
    token = db.query(UserToken).filter_by(token_hash=_hash(raw), purpose=purpose).first()
    if token is None or token.used_at is not None:
        return None
    expires_at = token.expires_at
    if expires_at.tzinfo is None:  # SQLite liefert naive Datetimes
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if expires_at < now:
        return None
    user = db.get(User, token.user_id)
    if user is None or user.deleted_at is not None:
        return None
    token.used_at = now
    return user


def purge_expired_tokens(db: Session, older_than_days: int = 7) -> int:
    """Räumt abgelaufene/benutzte Tokens auf (Hintergrund-Job)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    deleted = (
        db.query(UserToken)
        .filter((UserToken.expires_at < cutoff) | (UserToken.used_at < cutoff))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def new_token_id() -> uuid.UUID:
    return uuid.uuid4()
