from datetime import datetime, timedelta, timezone
import hashlib

import bcrypt
import jwt
import secrets

from app.core.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=ALGORITHM)


def get_access_token_expires_in() -> int:
    """Gibt die Access-Token-Lebensdauer in Sekunden zurück."""
    return settings.access_token_expire_minutes * 60


def decode_access_token(token: str) -> str:
    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[ALGORITHM])
    return payload["sub"]  # user_id


# ---------------------------------------------------------------------------
# Refresh-Token-Utilities
# ---------------------------------------------------------------------------


def create_refresh_token() -> str:
    """Erzeugt einen opaken Refresh-Token (256-bit random)."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """SHA-256-Hash eines Refresh-Tokens für DB-Speicherung."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Invite-Code-Generierung
# ---------------------------------------------------------------------------

_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ohne O/0, I/1


def generate_invite_code(length: int = 8) -> str:
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(length))
