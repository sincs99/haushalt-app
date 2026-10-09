"""Öffentliche Konfiguration für das Frontend (ohne Login).

Nur Schalter, die das Frontend zum Ein-/Ausblenden von Funktionen braucht —
keine Geheimnisse, keine internen Adressen.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(prefix="/api/config", tags=["config"])


class PublicConfig(BaseModel):
    # E-Mail-Versand aktiv → «Passwort vergessen» und E-Mail-Bestätigung sichtbar
    mail_enabled: bool


@router.get("", response_model=PublicConfig)
def public_config():
    return PublicConfig(mail_enabled=settings.mail_enabled)
