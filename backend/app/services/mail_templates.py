"""Texte der System-Mails (DE/EN). Reiner Text — keine HTML-Mails, keine Tracking-Links."""

from __future__ import annotations

from fastapi import Request

from app.core.config import settings
from app.services.mail import Mail

SUPPORTED_LANGUAGES = ("de", "en")


def request_language(request: Request | None) -> str:
    """Sprache aus ``Accept-Language`` (Frontend sendet die UI-Sprache); Standard Deutsch."""
    if request is None:
        return "de"
    header = request.headers.get("accept-language", "")
    for part in header.split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in SUPPORTED_LANGUAGES:
            return code
    return "de"


def _link(path: str, token: str) -> str:
    return f"{settings.public_base_url}{path}?token={token}"


def password_reset_mail(to: str, display_name: str, token: str, lang: str) -> Mail:
    link = _link("/reset-password", token)
    minutes = settings.password_reset_token_minutes
    if lang == "en":
        return Mail(
            to=to,
            subject="Reset your password",
            text=(
                f"Hi {display_name},\n\n"
                "someone (hopefully you) asked to reset the password of your Haushalt App account.\n"
                f"Open this link to choose a new password (valid for {minutes} minutes):\n\n"
                f"{link}\n\n"
                "If you did not request this, you can ignore this e-mail. Your password stays unchanged.\n"
            ),
        )
    return Mail(
        to=to,
        subject="Passwort zurücksetzen",
        text=(
            f"Hallo {display_name},\n\n"
            "jemand (hoffentlich du) möchte das Passwort deines Haushalt-App-Kontos zurücksetzen.\n"
            f"Öffne diesen Link, um ein neues Passwort zu wählen (gültig für {minutes} Minuten):\n\n"
            f"{link}\n\n"
            "Falls du das nicht warst, kannst du diese E-Mail ignorieren. Dein Passwort bleibt unverändert.\n"
        ),
    )


def email_verification_mail(to: str, display_name: str, token: str, lang: str) -> Mail:
    link = _link("/verify-email", token)
    hours = settings.email_verification_token_hours
    if lang == "en":
        return Mail(
            to=to,
            subject="Confirm your e-mail address",
            text=(
                f"Hi {display_name},\n\n"
                "welcome to Haushalt App! Please confirm your e-mail address by opening this link "
                f"(valid for {hours} hours):\n\n"
                f"{link}\n\n"
                "If you did not create an account, you can ignore this e-mail.\n"
            ),
        )
    return Mail(
        to=to,
        subject="E-Mail-Adresse bestätigen",
        text=(
            f"Hallo {display_name},\n\n"
            "willkommen bei der Haushalt App! Bitte bestätige deine E-Mail-Adresse über diesen Link "
            f"(gültig für {hours} Stunden):\n\n"
            f"{link}\n\n"
            "Falls du kein Konto erstellt hast, kannst du diese E-Mail ignorieren.\n"
        ),
    )


def password_changed_mail(to: str, display_name: str, lang: str) -> Mail:
    if lang == "en":
        return Mail(
            to=to,
            subject="Your password was changed",
            text=(
                f"Hi {display_name},\n\n"
                "the password of your Haushalt App account was just changed and all other devices were signed out.\n"
                "If this was not you, reset your password right away via \"Forgot password\" on the login page.\n"
            ),
        )
    return Mail(
        to=to,
        subject="Dein Passwort wurde geändert",
        text=(
            f"Hallo {display_name},\n\n"
            "das Passwort deines Haushalt-App-Kontos wurde soeben geändert; alle anderen Geräte wurden abgemeldet.\n"
            "Falls du das nicht warst, setze dein Passwort sofort über «Passwort vergessen» auf der Anmeldeseite zurück.\n"
        ),
    )
