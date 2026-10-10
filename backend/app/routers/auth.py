import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.error_codes import ErrorCode, error_detail
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_access_token_expires_in,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.database import get_db
from app.models import Household, HouseholdMember, RefreshToken, User
from app.services import entitlements
from app.services.invite_code import (
    generate_unique_invite_code,
    is_invite_code_expired,
    new_invite_code_expiry,
)
from app.socket_manager import disconnect_user_sync

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Wird für Login-Versuche mit unbekannter E-Mail verwendet (Timing-Angleichung)
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))

# ---------------------------------------------------------------------------
# Refresh-Token als HttpOnly-Cookie (Web-Client) + CSRF-Schutz
# ---------------------------------------------------------------------------
#
# Der Web-Client (PWA) bekommt den Refresh-Token NICHT im Body, sondern als
# HttpOnly-Cookie ``casa_rt`` — für JavaScript und damit für XSS unsichtbar.
# Er kennzeichnet alle Auth-Requests mit dem Header ``X-Requested-With: casa``.
# Dieser Header hat zwei Aufgaben:
#
#   1. Er schaltet die Cookie-Auslieferung ein. Ohne Header verhält sich die API
#      wie bisher (Refresh-Token im Body) — für Swagger-UI (/docs → "Authorize")
#      und künftige native Clients (Capacitor) ohne Browser-Cookie-Jar.
#   2. Er ist der CSRF-Schutz für ``/refresh`` und ``/logout``, sobald der Token
#      aus dem Cookie gelesen wird: HTML-Formulare können keine eigenen Header
#      setzen, und ein fremder Origin kann ihn per fetch/XHR nur mit einem
#      CORS-Preflight senden, den ausschliesslich die konfigurierten Origins
#      bestehen. Dazu kommen SameSite=Strict und Path=/api/auth auf dem Cookie.
#
# Wird der Token im Body mitgeschickt, hat er Vorrang vor dem Cookie (native
# Clients, einmalige Migration alter localStorage-Tokens im Web-Client).

REFRESH_COOKIE_NAME = "casa_rt"
REFRESH_COOKIE_PATH = "/api/auth"
CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "casa"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str
    household_name: str | None = None
    invite_code: str | None = None
    # Zustimmung zu Nutzungsbedingungen und Datenschutz (Pflicht bei LEGAL_TERMS_REQUIRED)
    accept_terms: bool = False

    @model_validator(mode="after")
    def exactly_one_household_method(self):
        """Genau eines von household_name oder invite_code muss gesetzt sein."""
        has_name = self.household_name is not None and self.household_name.strip() != ""
        has_code = self.invite_code is not None and self.invite_code.strip() != ""
        if has_name == has_code:  # Beide gesetzt oder beide leer
            raise ValueError("Exactly one of household_name or invite_code must be provided")
        return self


class TokenResponse(BaseModel):
    access_token: str
    # None, wenn der Refresh-Token als HttpOnly-Cookie geliefert wurde (Web-Client)
    refresh_token: str | None
    token_type: str = "bearer"
    expires_in: int  # Sekunden bis Access-Token abläuft


class RefreshRequest(BaseModel):
    # Optional: fehlt er, wird der Token aus dem Cookie ``casa_rt`` gelesen
    refresh_token: str | None = None


class LogoutRequest(BaseModel):
    # Optional: fehlt er, wird der Token aus dem Cookie ``casa_rt`` gelesen
    refresh_token: str | None = None


class HouseholdOut(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    currency: str
    ai_enabled: bool = False
    # Geltender Tarif (free/premium; "selfhosted" ohne BILLING_ENABLED)
    plan: str = "selfhosted"


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool = False
    is_platform_admin: bool = False
    households: list[HouseholdOut]


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _uses_cookie_delivery(request: Request) -> bool:
    """True für den Web-Client, der sich per ``X-Requested-With: casa`` ausweist."""
    return request.headers.get(CSRF_HEADER_NAME, "").strip().lower() == CSRF_HEADER_VALUE


def _set_refresh_cookie(response: Response, raw_refresh: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=raw_refresh,
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        path=REFRESH_COOKIE_PATH,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _cleared_cookie_headers() -> dict[str, str]:
    """Set-Cookie-Header, der den Cookie löscht — für Fehler-Responses (HTTPException)."""
    tmp = Response()
    _clear_refresh_cookie(tmp)
    return {"set-cookie": tmp.headers["set-cookie"]}


def _deliver(pair: TokenResponse, request: Request, response: Response) -> TokenResponse:
    """Web-Client: Refresh-Token nur als Cookie, nicht im Body. Sonst unverändert im Body."""
    if _uses_cookie_delivery(request):
        _set_refresh_cookie(response, pair.refresh_token)
        return pair.model_copy(update={"refresh_token": None})
    return pair


def _resolve_refresh_token(request: Request, body_token: str | None) -> tuple[str | None, bool]:
    """Ermittelt den Refresh-Token aus Body (Vorrang) oder Cookie.

    Returns:
        (raw_token oder None, from_cookie)

    Raises:
        HTTPException 403, wenn der Token aus dem Cookie käme, der CSRF-Header
        aber fehlt — der Token wird dann nicht angefasst.
    """
    if body_token:
        return body_token, False
    cookie_token = request.cookies.get(REFRESH_COOKIE_NAME)
    if not cookie_token:
        return None, False
    if not _uses_cookie_delivery(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(
                ErrorCode.CSRF_HEADER_MISSING,
                f"Header '{CSRF_HEADER_NAME}: {CSRF_HEADER_VALUE}' is required for cookie-based requests",
            ),
        )
    return cookie_token, True


def _refresh_rejected(code: str, message: str, from_cookie: bool) -> HTTPException:
    """401 für /refresh. Kam der Token aus dem Cookie, wird dieser gleich gelöscht,
    damit der Browser den toten Token nicht bei jedem Start erneut schickt."""
    return HTTPException(
        status_code=401,
        detail=error_detail(code, message),
        headers=_cleared_cookie_headers() if from_cookie else None,
    )


def _create_token_pair(user_id: str, db: Session) -> tuple[TokenResponse, RefreshToken]:
    """Erzeugt Access- + Refresh-Token-Paar und persistiert den Refresh-Token.

    Returns:
        Tuple aus (TokenResponse für den Client, RefreshToken DB-Objekt).
    """
    access_token = create_access_token(user_id)
    raw_refresh = create_refresh_token()

    rt = RefreshToken(
        user_id=uuid.UUID(user_id),
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    db.commit()
    db.refresh(rt)  # Damit rt.id verfügbar ist

    response = TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        token_type="bearer",
        expires_in=get_access_token_expires_in(),
    )
    return response, rt


def _cleanup_expired_tokens(user_id: uuid.UUID, db: Session) -> None:
    """Löscht abgelaufene und lang-revozierte Refresh-Tokens eines Users."""
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        (
            (RefreshToken.expires_at < now)
            | (
                RefreshToken.revoked_at.isnot(None)
                & (RefreshToken.revoked_at < seven_days_ago)
            )
        ),
    ).delete(synchronize_session=False)
    db.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/register", response_model=TokenResponse)
@limiter.limit("3/hour")
def register(
    request: Request,
    response: Response,
    data: RegisterRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if settings.legal_terms_required and not data.accept_terms:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.TERMS_ACCEPTANCE_REQUIRED, "Terms of service and privacy policy must be accepted"
            ),
        )
    existing = db.query(User).filter_by(email=data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail=error_detail(ErrorCode.EMAIL_ALREADY_REGISTERED, "Email already registered"))

    # Haushalt zuerst prüfen (Einladungscode, Ablauf, Mitglieder-Limit), damit bei einem
    # Fehler kein halb angelegtes Konto zurückbleibt
    household: Household | None = None
    if data.invite_code:
        code = data.invite_code.strip().upper()
        household = (
            db.query(Household)
            .filter(func.upper(Household.invite_code) == code)
            .first()
        )
        if household is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail(ErrorCode.INVITE_CODE_NOT_FOUND, "Invite code not found"),
            )
        if is_invite_code_expired(household):
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=error_detail(ErrorCode.INVITE_CODE_EXPIRED, "Invite code has expired"),
            )
        if not entitlements.can_add_member(db, household):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=error_detail(
                    ErrorCode.PLAN_MEMBER_LIMIT_REACHED, "This household has reached its member limit"
                ),
            )

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
    )
    if data.accept_terms:
        user.terms_accepted_at = datetime.now(timezone.utc)
        user.terms_version = settings.legal_terms_version
    db.add(user)
    db.flush()

    if household is not None:
        # ── Pfad B: Mit Einladungscode beitreten ──
        membership = HouseholdMember(household_id=household.id, user_id=user.id, role="member")
    else:
        # ── Pfad A: Neuen Haushalt erstellen (Standard, wie bisher) ──
        invite_code = generate_unique_invite_code(db)
        household = Household(
            name=data.household_name.strip(),
            invite_code=invite_code,
            invite_code_expires_at=new_invite_code_expiry(),
        )
        db.add(household)
        db.flush()
        membership = HouseholdMember(household_id=household.id, user_id=user.id, role="admin")

    db.add(membership)
    db.flush()

    # Bestätigungs-Mail (nur wenn Versand konfiguriert ist; die App bleibt ohne nutzbar)
    if settings.mail_enabled:
        from app.routers.account import send_verification_mail
        from app.services.mail_templates import request_language

        send_verification_mail(db, user, request_language(request), background)

    pair, _ = _create_token_pair(str(user.id), db)
    return _deliver(pair, request, response)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter_by(email=form_data.username).first()
    # Auch bei unbekannter E-Mail einen bcrypt-Vergleich durchführen, damit die
    # Antwortzeit nicht verrät, ob ein Account existiert (User-Enumeration).
    password_hash = user.password_hash if user else _DUMMY_PASSWORD_HASH
    password_ok = verify_password(form_data.password, password_hash)
    if not user or not password_ok or user.deleted_at is not None:
        raise HTTPException(status_code=401, detail=error_detail(ErrorCode.INVALID_CREDENTIALS, "Incorrect email or password"))
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(ErrorCode.ACCOUNT_DISABLED, "Account is disabled"),
        )

    pair, _ = _create_token_pair(str(user.id), db)
    return _deliver(pair, request, response)


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
def refresh_endpoint(
    request: Request,
    response: Response,
    data: RefreshRequest | None = None,
    db: Session = Depends(get_db),
):
    """Token-Rotation: tausche gültigen Refresh-Token gegen neues Token-Paar.

    Der alte Token kommt aus dem Body (native Clients, Migration) oder aus dem
    HttpOnly-Cookie (Web-Client, nur mit CSRF-Header). Das neue Paar wird auf
    demselben Weg ausgeliefert, auf dem der Client sich ausweist (siehe oben).
    """
    raw_token, from_cookie = _resolve_refresh_token(request, data.refresh_token if data else None)
    if raw_token is None:
        raise HTTPException(
            status_code=401,
            detail=error_detail(ErrorCode.REFRESH_TOKEN_INVALID, "Refresh token missing"),
        )

    token_hash = hash_refresh_token(raw_token)
    old_token = db.query(RefreshToken).filter_by(token_hash=token_hash).first()

    # 1) Token nicht gefunden
    if old_token is None:
        raise _refresh_rejected(ErrorCode.REFRESH_TOKEN_INVALID, "Refresh token invalid", from_cookie)

    # 2) Reuse-Detection MIT Grace Window
    if old_token.revoked_at is not None:
        # Prüfe ob innerhalb der Grace Period UND ein Replacement existiert
        revoked_at = old_token.revoked_at
        if revoked_at.tzinfo is None:
            revoked_at = revoked_at.replace(tzinfo=timezone.utc)

        grace_ok = (
            old_token.replaced_by_id is not None
            and (datetime.now(timezone.utc) - revoked_at).total_seconds()
            <= settings.refresh_token_reuse_grace_seconds
        )

        if grace_ok:
            # Benign retry / zweiter Tab → Replacement-Token prüfen
            replacement = db.get(RefreshToken, old_token.replaced_by_id)
            if replacement and replacement.revoked_at is None:
                # Replacement noch gültig → davon ableiten (nochmal rotieren)
                replacement_expires = replacement.expires_at
                if replacement_expires.tzinfo is None:
                    replacement_expires = replacement_expires.replace(tzinfo=timezone.utc)

                if replacement_expires >= datetime.now(timezone.utc):
                    # Replacement revoken und neues Paar erstellen
                    replacement.revoked_at = datetime.now(timezone.utc)
                    db.flush()

                    pair, new_rt = _create_token_pair(str(old_token.user_id), db)
                    replacement.replaced_by_id = new_rt.id
                    db.commit()
                    return _deliver(pair, request, response)

        # Grace Window nicht anwendbar → volle Reuse-Detection
        db.query(RefreshToken).filter(
            RefreshToken.user_id == old_token.user_id,
            RefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": datetime.now(timezone.utc)})
        db.commit()
        # Alle Sitzungen sind widerrufen → auch offene Socket-Verbindungen beenden
        disconnect_user_sync(old_token.user_id, "revoked")
        raise _refresh_rejected(
            ErrorCode.REFRESH_TOKEN_REUSED, "Refresh token reuse detected", from_cookie
        )

    # 3) Token abgelaufen (SQLite gibt naive datetimes, PostgreSQL aware)
    expires_at = old_token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise _refresh_rejected(ErrorCode.REFRESH_TOKEN_EXPIRED, "Refresh token expired", from_cookie)

    # 4) Konto gesperrt oder gelöscht → kein neues Paar
    owner = db.get(User, old_token.user_id)
    if owner is None or owner.deleted_at is not None or not owner.is_active:
        raise _refresh_rejected(ErrorCode.ACCOUNT_DISABLED, "Account is disabled", from_cookie)

    # 5) Alles OK → alten Token revoken, neues Paar erstellen
    old_token.revoked_at = datetime.now(timezone.utc)
    db.flush()

    pair, new_rt = _create_token_pair(str(old_token.user_id), db)
    old_token.replaced_by_id = new_rt.id
    db.commit()

    # 6) Lazy Cleanup: alte Tokens dieses Users aufräumen
    try:
        _cleanup_expired_tokens(old_token.user_id, db)
    except Exception:
        logger.warning("Refresh token cleanup failed for user %s", old_token.user_id, exc_info=True)

    return _deliver(pair, request, response)


@router.post("/logout", status_code=204)
@limiter.limit("30/minute")
def logout_endpoint(
    request: Request,
    response: Response,
    data: LogoutRequest | None = None,
    db: Session = Depends(get_db),
):
    """Revoke einen Refresh-Token (Body oder Cookie) und löscht den Cookie.

    Idempotent: unbekannte/bereits revoked/fehlende Tokens → trotzdem 204.
    """
    raw_token, _from_cookie = _resolve_refresh_token(request, data.refresh_token if data else None)
    if raw_token:
        token_hash = hash_refresh_token(raw_token)
        existing = db.query(RefreshToken).filter_by(token_hash=token_hash).first()
        if existing and existing.revoked_at is None:
            existing.revoked_at = datetime.now(timezone.utc)
            db.commit()
            # Offene Socket-Verbindungen des Users serverseitig trennen. Der Access-Token
            # trägt keine Geräte-Kennung, deshalb trifft das alle Verbindungen des Users;
            # andere Geräte verbinden sich mit ihrem weiterhin gültigen Token selbst neu.
            disconnect_user_sync(existing.user_id, "logout")

    if _uses_cookie_delivery(request) or REFRESH_COOKIE_NAME in request.cookies:
        _clear_refresh_cookie(response)
    return None


@router.get("/me", response_model=MeResponse)
def get_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Gibt den aktuell eingeloggten User inkl. Household-Zugehörigkeiten zurück."""
    memberships = (
        db.query(HouseholdMember)
        .options(joinedload(HouseholdMember.household))
        .filter_by(user_id=current_user.id)
        .all()
    )
    households = [
        HouseholdOut(
            id=m.household.id,
            name=m.household.name,
            role=m.role,
            currency=m.household.currency,
            ai_enabled=m.household.ai_enabled,
            plan=entitlements.effective_plan(m.household),
        )
        for m in memberships
    ]

    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        email_verified=current_user.email_verified_at is not None,
        is_platform_admin=current_user.is_platform_admin,
        households=households,
    )
