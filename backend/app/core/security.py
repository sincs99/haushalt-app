import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

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
    return decode_access_token_with_expiry(token)[0]  # user_id


def decode_access_token_with_expiry(token: str) -> tuple[str, float]:
    """Wie decode_access_token, liefert zusätzlich den Ablauf (Unix-Zeit in Sekunden).

    Für Socket-Verbindungen, die länger leben als ein einzelnes Access-Token.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
    return payload["sub"], float(payload["exp"])


# ---------------------------------------------------------------------------
# Refresh-Token-Utilities
# ---------------------------------------------------------------------------


def create_refresh_token() -> str:
    """Erzeugt einen opaken Refresh-Token (256-bit random)."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Key-bound digest: rotating the JWT secret invalidates refresh authority too.

    There is deliberately no fallback to the old unkeyed SHA-256 hashes: the
    first deployment of this change requires existing sessions to log in again.
    """
    return hmac.new(
        settings.jwt_secret_key.encode(),
        b"casa:refresh-token:v1\x00" + token.encode(),
        hashlib.sha256,
    ).hexdigest()


# ---------------------------------------------------------------------------
# Invite-Code-Generierung
# ---------------------------------------------------------------------------

_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ohne O/0, I/1


def generate_invite_code(length: int = 8) -> str:
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(length))
