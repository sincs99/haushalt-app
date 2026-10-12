"""E-Mail-Versand (Passwort zurücksetzen, E-Mail-Verifizierung).

Backends (``settings.effective_mail_backend``):

- ``smtp``: Versand über ``smtplib`` (STARTTLS, SSL oder ohne TLS für lokale Relays)
- ``console``: Mail wird nur geloggt (Entwicklung, Tests)
- ``off``: kein Versand; Aufrufer prüfen vorher ``settings.mail_enabled`` und blenden
  die Funktionen aus

Der Versand läuft in FastAPI-``BackgroundTasks`` — eine langsame SMTP-Verbindung
verzögert so keine Antwort. Fehler werden geloggt, nie an den Client durchgereicht
(sie würden sonst verraten, ob eine Adresse existiert).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    text: str


def _send_smtp(mail: Mail) -> None:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.set_content(mail.text)

    mode = settings.smtp_tls.strip().lower()
    timeout = settings.smtp_timeout_seconds
    if mode == "ssl":
        context = ssl.create_default_context()
        server: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=timeout, context=context
        )
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
    try:
        server.ehlo()
        if mode == "starttls":
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
    finally:
        try:
            server.quit()
        except Exception:
            pass


def send_mail(mail: Mail) -> bool:
    """Versendet eine Mail über das konfigurierte Backend. True bei Erfolg."""
    backend = settings.effective_mail_backend
    if backend == "off":
        logger.info("Mail backend is off — mail to %s (%s) dropped", mail.to, mail.subject)
        return False
    if backend == "console":
        logger.info("MAIL (console backend) to=%s subject=%r\n%s", mail.to, mail.subject, mail.text)
        return True
    if backend != "smtp":
        logger.error("Unknown MAIL_BACKEND %r — mail to %s dropped", backend, mail.to)
        return False
    try:
        _send_smtp(mail)
        logger.info("Mail sent to %s (%s)", mail.to, mail.subject)
        return True
    except Exception:
        logger.exception("Sending mail to %s failed", mail.to)
        return False
