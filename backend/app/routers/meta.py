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
    # Tarife aktiv (SaaS) → Tarif-Karte in den Einstellungen
    billing_enabled: bool
    # Stripe eingerichtet → Upgrade-Button (nur Web; native Apps nutzen die Store-Abrechnung)
    checkout_available: bool


@router.get("", response_model=PublicConfig)
def public_config():
    return PublicConfig(
        mail_enabled=settings.mail_enabled,
        billing_enabled=settings.billing_enabled,
        checkout_available=settings.billing_enabled and settings.stripe_configured,
    )
