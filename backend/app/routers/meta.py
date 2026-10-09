"""Öffentliche Konfiguration für das Frontend (ohne Login).

Nur Schalter, die das Frontend zum Ein-/Ausblenden von Funktionen braucht —
keine Geheimnisse, keine internen Adressen.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings

router = APIRouter(prefix="/api/config", tags=["config"])


class OperatorInfo(BaseModel):
    name: str
    address_lines: list[str]
    email: str


class PublicConfig(BaseModel):
    # E-Mail-Versand aktiv → «Passwort vergessen» und E-Mail-Bestätigung sichtbar
    mail_enabled: bool
    # Tarife aktiv (SaaS) → Tarif-Karte in den Einstellungen
    billing_enabled: bool
    # Stripe eingerichtet → Upgrade-Button (nur Web; native Apps nutzen die Store-Abrechnung)
    checkout_available: bool
    # Registrierung verlangt Zustimmung zu Nutzungsbedingungen/Datenschutz
    terms_required: bool
    terms_version: str
    # Betreiberangaben für Impressum/Datenschutz (leer beim Self-Hosting ohne Konfiguration)
    operator: OperatorInfo


@router.get("", response_model=PublicConfig)
def public_config():
    return PublicConfig(
        mail_enabled=settings.mail_enabled,
        billing_enabled=settings.billing_enabled,
        checkout_available=settings.billing_enabled and settings.stripe_configured,
        terms_required=settings.legal_terms_required,
        terms_version=settings.legal_terms_version,
        operator=OperatorInfo(
            name=settings.operator_name.strip(),
            address_lines=settings.operator_address_lines,
            email=settings.operator_email.strip(),
        ),
    )
