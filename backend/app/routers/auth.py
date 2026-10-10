import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy.exc import IntegrityError
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
from app.models import HouseholdMember, RefreshToken, User
from app.services.locking import lock_row
from app.services.membership import create_household_with_admin, join_by_invite_code
from app.socket_manager import disconnect_user_sync, emit_to_household_sync

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
    # IANA-Zeitzone des Haushalts: „heute“ für Fälligkeiten im Frontend (CASA-39)
    timezone: str = "Europe/Zurich"


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
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
    """Erzeugt Access- + Refresh-Token-Paar und legt den Refresh-Token an (flush, KEIN Commit).

    Der Aufrufer committet — bei der Rotation zusammen mit ``revoked_at`` und
    ``replaced_by_id`` des alten Tokens, damit kein Zwischenzustand sichtbar wird
    ("widerrufen, aber ohne Nachfolger"), den ein paralleler Refresh als Reuse
    fehldeuten würde (CASA-11).

    Returns:
        Tuple aus (TokenResponse für den Client, RefreshToken DB-Objekt mit id).
    """
    access_token = create_access_token(user_id)
    raw_refresh = create_refresh_token()

    rt = RefreshToken(
        id=uuid.uuid4(),
        user_id=uuid.UUID(user_id),
        token_hash=hash_refresh_token(raw_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(rt)
    db.flush()

    response = TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        token_type="bearer",
        expires_in=get_access_token_expires_in(),
    )
    return response, rt


def _rotate(db: Session, token: RefreshToken) -> TokenResponse:
    """Ersetzt einen (gesperrten) aktiven Token durch einen neuen — ein einziger Commit."""
    pair, new_rt = _create_token_pair(str(token.user_id), db)
    token.revoked_at = datetime.now(timezone.utc)
    token.replaced_by_id = new_rt.id
    db.commit()
    return pair


def _as_aware(dt: datetime) -> datetime:
    # SQLite gibt naive datetimes, PostgreSQL aware
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# Schutz gegen Zyklen/Endlosketten in replaced_by_id (sollte nie vorkommen)
MAX_REPLACEMENT_CHAIN = 50


def _active_successor(db: Session, token: RefreshToken) -> RefreshToken | None:
    """Folgt der Ersetzungskette bis zum aktiven Nachfolger (gesperrt) oder None.

    Mehrere Tabs/Geräte mit demselben Cookie können innerhalb des Grace Windows
    mehrmals mit dem alten Token kommen; jeder Aufruf hängt einen weiteren
    Nachfolger an. Deshalb nicht nur einen Schritt prüfen, sondern bis zum Ende.
    """
    current = token
    for _ in range(MAX_REPLACEMENT_CHAIN):
        if current.replaced_by_id is None:
            return None
        nxt = lock_row(db, RefreshToken, current.replaced_by_id)
        if nxt is None:
            return None
        if nxt.revoked_at is None:
            return nxt
        current = nxt
    return None


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
    db: Session = Depends(get_db),
):
    email_taken = HTTPException(
        status_code=400, detail=error_detail(ErrorCode.EMAIL_ALREADY_REGISTERED, "Email already registered")
    )
    existing = db.query(User).filter_by(email=data.email).first()
    if existing:
        raise email_taken

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        display_name=data.display_name,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        # Parallele Registrierung derselben E-Mail (CASA-24): Unique-Constraint greift
        db.rollback()
        raise email_taken

    joined = None
    if data.invite_code:
        # ── Pfad B: Mit Einladungscode beitreten (gleiche Regeln/Sperre wie /join) ──
        household, membership = join_by_invite_code(db, data.invite_code, user.id)
        joined = {
            "household_id": str(household.id),
            "user_id": str(user.id),
            "display_name": user.display_name,
            "role": membership.role,
        }
    else:
        # ── Pfad A: Neuen Haushalt erstellen (Standard, wie bisher) ──
        household, _ = create_household_with_admin(db, data.household_name, user.id)

    household_id = household.id
    pair, _ = _create_token_pair(str(user.id), db)
    db.commit()

    if joined is not None:
        # Wie POST /households/join: andere Mitglieder aktualisieren ihre Listen (CASA-46)
        emit_to_household_sync(household_id, "household_member_joined", joined)
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
    if not user or not password_ok:
        raise HTTPException(status_code=401, detail=error_detail(ErrorCode.INVALID_CREDENTIALS, "Incorrect email or password"))

    pair, _ = _create_token_pair(str(user.id), db)
    db.commit()
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
    # Zeile sperren (CASA-11): Parallele Refreshes mit demselben Token laufen
    # nacheinander; der zweite sieht danach "widerrufen MIT Nachfolger" (Grace-Pfad)
    old_token = (
        db.query(RefreshToken)
        .filter_by(token_hash=token_hash)
        .with_for_update()
        .populate_existing()
        .first()
    )

    # 1) Token nicht gefunden
    if old_token is None:
        raise _refresh_rejected(ErrorCode.REFRESH_TOKEN_INVALID, "Refresh token invalid", from_cookie)

    now = datetime.now(timezone.utc)

    # 2) Reuse-Detection MIT Grace Window
    if old_token.revoked_at is not None:
        grace_ok = (
            old_token.replaced_by_id is not None
            and (now - _as_aware(old_token.revoked_at)).total_seconds()
            <= settings.refresh_token_reuse_grace_seconds
        )
        if grace_ok:
            # Benign retry / zweiter Tab → aktiven Nachfolger der Kette weiterrotieren
            successor = _active_successor(db, old_token)
            if successor is not None and _as_aware(successor.expires_at) >= now:
                return _deliver(_rotate(db, successor), request, response)

        # Grace Window nicht anwendbar → volle Reuse-Detection
        user_id = old_token.user_id
        db.query(RefreshToken).filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": now})
        db.commit()
        # Alle Sitzungen sind widerrufen → auch offene Socket-Verbindungen beenden
        disconnect_user_sync(user_id, "revoked")
        raise _refresh_rejected(
            ErrorCode.REFRESH_TOKEN_REUSED, "Refresh token reuse detected", from_cookie
        )

    # 3) Token abgelaufen
    if _as_aware(old_token.expires_at) < now:
        raise _refresh_rejected(ErrorCode.REFRESH_TOKEN_EXPIRED, "Refresh token expired", from_cookie)

    # 4) Alles OK → alten Token widerrufen + Nachfolger anlegen, ein Commit
    user_id = old_token.user_id
    pair = _rotate(db, old_token)

    # 5) Lazy Cleanup: alte Tokens dieses Users aufräumen
    try:
        _cleanup_expired_tokens(user_id, db)
    except Exception:
        db.rollback()
        logger.warning("Refresh token cleanup failed for user %s", user_id, exc_info=True)

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
            timezone=m.household.timezone or "Europe/Zurich",
        )
        for m in memberships
    ]

    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        households=households,
    )
