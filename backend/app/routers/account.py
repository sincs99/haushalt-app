"""Konto-Funktionen: Passwort vergessen/zurücksetzen, E-Mail bestätigen, Passwort ändern, Konto löschen.

Alle Links in E-Mails zeigen auf das Frontend (``settings.public_base_url``), das den Token
aus der URL liest und hierher schickt. Die Endpunkte verraten nie, ob eine Adresse
registriert ist (immer 202 bei «Passwort vergessen»).
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.error_codes import ErrorCode, error_detail
from app.core.rate_limit import limiter
from app.core.security import hash_password, verify_password
from app.database import get_db
from app.models import HouseholdMember, PushSubscription, RefreshToken, User
from app.routers.auth import TokenResponse, _create_token_pair, _deliver
from app.services import membership as membership_service
from app.services.account_tokens import (
    PURPOSE_EMAIL_VERIFICATION,
    PURPOSE_PASSWORD_RESET,
    consume_token,
    issue_token,
)
from app.services.mail import send_mail
from app.services.mail_templates import (
    email_verification_mail,
    password_changed_mail,
    password_reset_mail,
    request_language,
)
from app.socket_manager import disconnect_user_sync, emit_to_household_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/account", tags=["account"])


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=8, max_length=128)


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class DeleteAccountRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)


class AccountStatus(BaseModel):
    mail_enabled: bool
    email_verified: bool


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _require_mail() -> None:
    if not settings.mail_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail(ErrorCode.MAIL_DISABLED, "E-mail delivery is not configured"),
        )


def _revoke_all_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    ).update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)


def send_verification_mail(
    db: Session, user: User, lang: str, background: BackgroundTasks
) -> None:
    """Stellt einen Bestätigungs-Token aus (ohne Commit) und plant den Versand."""
    raw = issue_token(db, user, PURPOSE_EMAIL_VERIFICATION)
    background.add_task(send_mail, email_verification_mail(user.email, user.display_name, raw, lang))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/status", response_model=AccountStatus)
def account_status(current_user: User = Depends(get_current_user)):
    return AccountStatus(
        mail_enabled=settings.mail_enabled,
        email_verified=current_user.email_verified_at is not None,
    )


@router.post("/password/forgot", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/minute;10/hour")
def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Schickt einen Reset-Link, falls die Adresse registriert ist. Antwortet immer 202."""
    _require_mail()
    user = db.query(User).filter_by(email=data.email).first()
    if user is not None and user.deleted_at is None:
        raw = issue_token(db, user, PURPOSE_PASSWORD_RESET)
        db.commit()
        background.add_task(
            send_mail,
            password_reset_mail(user.email, user.display_name, raw, request_language(request)),
        )
    else:
        # Gleiches Timing-Verhalten wie bei bekannter Adresse (Token-Erzeugung ist billig,
        # der Versand läuft ohnehin im Hintergrund)
        secrets.token_urlsafe(32)
    return {"status": "accepted"}


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    """Setzt das Passwort per Token neu und meldet alle Geräte ab."""
    user = consume_token(db, data.token, PURPOSE_PASSWORD_RESET)
    if user is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.ACCOUNT_TOKEN_INVALID, "Token is invalid or expired"),
        )
    user.password_hash = hash_password(data.password)
    # Wer den Link aus der Mail öffnen kann, besitzt das Postfach
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
    _revoke_all_sessions(db, user.id)
    db.commit()
    disconnect_user_sync(user.id, "revoked")
    return None


@router.post("/email/verify", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
def verify_email(
    request: Request,
    data: VerifyEmailRequest,
    db: Session = Depends(get_db),
):
    """Bestätigt die E-Mail-Adresse per Token (kein Login nötig — der Link kommt aus der Mail)."""
    user = consume_token(db, data.token, PURPOSE_EMAIL_VERIFICATION)
    if user is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.ACCOUNT_TOKEN_INVALID, "Token is invalid or expired"),
        )
    if user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
    db.commit()
    return None


@router.post("/email/resend", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("3/hour")
def resend_verification(
    request: Request,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_mail()
    if current_user.email_verified_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.EMAIL_ALREADY_VERIFIED, "E-mail address already verified"),
        )
    send_verification_mail(db, current_user, request_language(request), background)
    db.commit()
    return {"status": "accepted"}


@router.put("/password", response_model=TokenResponse)
@limiter.limit("5/minute")
def change_password(
    request: Request,
    response: Response,
    data: ChangePasswordRequest,
    background: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Passwort ändern. Alle anderen Geräte werden abgemeldet; der Aufrufer erhält ein neues Token-Paar."""
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.PASSWORD_INCORRECT, "Current password is incorrect"),
        )
    current_user.password_hash = hash_password(data.new_password)
    _revoke_all_sessions(db, current_user.id)
    db.commit()
    disconnect_user_sync(current_user.id, "revoked")
    if settings.mail_enabled:
        background.add_task(
            send_mail,
            password_changed_mail(current_user.email, current_user.display_name, request_language(request)),
        )
    pair, _ = _create_token_pair(str(current_user.id), db)
    return _deliver(pair, request, response)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/minute")
def delete_account(
    request: Request,
    data: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Konto löschen (App-Store-Pflicht, DSGVO Art. 17).

    Personenbezogene Daten werden entfernt, die Zeile bleibt anonymisiert bestehen, weil
    Ausgaben und Ausgleichszahlungen ehemaliger Mitglieder auf sie verweisen (gleiches
    Muster wie beim Verlassen eines Haushalts). Alle Haushalte werden verlassen; ist das
    Konto das letzte Mitglied, wird der Haushalt samt Dateien gelöscht.
    """
    if not verify_password(data.password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.PASSWORD_INCORRECT, "Password is incorrect"),
        )
    user_id = current_user.id
    left_households: list[uuid.UUID] = []

    memberships = db.query(HouseholdMember).filter_by(user_id=user_id).all()
    for membership in memberships:
        household_id = membership.household_id
        if not membership_service.leave(db, membership).household_deleted:
            left_households.append(household_id)

    user = db.get(User, user_id)
    now = datetime.now(timezone.utc)
    user.email = f"deleted-{user_id}@deleted.invalid"
    user.display_name = "Gelöschtes Konto"
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.email_verified_at = None
    user.deleted_at = now
    _revoke_all_sessions(db, user_id)
    db.query(PushSubscription).filter_by(user_id=user_id).delete(synchronize_session=False)
    db.commit()

    for household_id in left_households:
        emit_to_household_sync(
            household_id,
            "household_member_left",
            {"household_id": str(household_id), "user_id": str(user_id)},
            evict_user_id=user_id,
        )
    disconnect_user_sync(user_id, "revoked")
    logger.info("Account %s deleted (anonymized)", user_id)
    return None
