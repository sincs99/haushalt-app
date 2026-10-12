"""Homescreen-Widget (Scriptable auf dem iPhone) mit Nur-Lese-Schlüssel.

Zwei Router:

- ``manage_router`` (normaler Login): Schlüssel anzeigen, erzeugen/ersetzen,
  widerrufen — pro Person und Haushalt höchstens einer.
- ``router``: ``GET /api/widget/summary`` mit ``Authorization: Bearer hw_…``.
  Der Schlüssel erlaubt nur diesen einen Lese-Endpoint, läuft nicht ab und
  ist an Person und Haushalt gebunden. Verlässt die Person den Haushalt (oder
  wird entfernt), wird er im selben Commit gelöscht (PD-H1); als Rückfall prüft
  jeder Abruf die Mitgliedschaft.

Gespeichert wird nur der SHA-256-Hash; der Klartext erscheint einmal beim Erzeugen.
Doku: docs/widget.md
"""

import secrets
import uuid
import zoneinfo
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.core.rate_limit import limiter
from app.core.security import hash_refresh_token
from app.database import get_db
from app.models import (
    Event,
    Household,
    HouseholdMember,
    ShoppingItem,
    User,
    WidgetToken,
)
from app.services.attention import due_items, household_today
from app.services.event_times import on_day, to_household_time
from app.services.locking import lock_household
from app.services.membership import locked_membership

TOKEN_PREFIX = "hw_"
MAX_DUE_ITEMS = 8
MAX_SHOPPING_ITEMS = 6
MAX_EVENTS = 4


def _hash(token: str) -> str:
    return hash_refresh_token(token)  # SHA-256, wie Refresh-Tokens


# ---------------------------------------------------------------------------
# Schlüssel verwalten (Login nötig)
# ---------------------------------------------------------------------------

manage_router = APIRouter(
    prefix="/api/households/{household_id}/widget-token",
    tags=["widget"],
)


class WidgetTokenStatus(BaseModel):
    exists: bool
    token_prefix: str | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None


class WidgetTokenCreated(BaseModel):
    token: str
    token_prefix: str
    created_at: datetime


def _own_token(db: Session, membership: HouseholdMember) -> WidgetToken | None:
    return (
        db.query(WidgetToken)
        .filter(
            WidgetToken.user_id == membership.user_id,
            WidgetToken.household_id == membership.household_id,
        )
        .first()
    )


@manage_router.get("", response_model=WidgetTokenStatus)
def get_widget_token(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    token = _own_token(db, membership)
    if token is None:
        return WidgetTokenStatus(exists=False)
    return WidgetTokenStatus(
        exists=True,
        token_prefix=token.token_prefix,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
    )


@manage_router.post("", response_model=WidgetTokenCreated, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
def create_widget_token(
    request: Request,
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Erzeugt einen neuen Schlüssel; ein bestehender wird dabei ungültig.

    Parallele Aufrufe (Doppelklick, zwei Geräte) laufen unter der Haushaltssperre
    nacheinander (CASA-24): jeder ersetzt den vorherigen, am Ende gilt genau ein
    Schlüssel — der zuletzt ausgegebene. Die Sperre serialisiert auch mit
    Austritt/Entfernen, die den Schlüssel löschen (PD-H1).
    """
    if lock_household(db, household_id) is None or locked_membership(db, household_id, membership.user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(ErrorCode.NOT_HOUSEHOLD_MEMBER, "Not a member of this household"),
        )
    existing = _own_token(db, membership)
    if existing is not None:
        db.delete(existing)
        db.flush()

    plain = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = WidgetToken(
        user_id=membership.user_id,
        household_id=membership.household_id,
        token_hash=_hash(plain),
        token_prefix=plain[:10],
    )
    db.add(token)
    db.flush()
    # Antwort vor dem Commit bauen: Danach kann ein paralleler Aufruf den Schlüssel
    # schon ersetzt haben (ein refresh() fände die Zeile nicht mehr)
    result = WidgetTokenCreated(token=plain, token_prefix=token.token_prefix, created_at=token.created_at)
    db.commit()
    return result


@manage_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_widget_token(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    token = _own_token(db, membership)
    if token is not None:
        db.delete(token)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Widget-Daten (nur mit Widget-Schlüssel)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/widget", tags=["widget"])


class WidgetDueItem(BaseModel):
    kind: str
    title: str
    overdue: bool
    mine: bool


class WidgetShopping(BaseModel):
    open_count: int
    items: list[str]


class WidgetEvent(BaseModel):
    title: str
    time: str | None  # "HH:MM", None bei ganztägig


class WidgetSummary(BaseModel):
    household: str
    user: str
    date: date
    generated_at: datetime
    due_count: int
    due: list[WidgetDueItem]
    shopping: WidgetShopping
    events: list[WidgetEvent]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=error_detail(ErrorCode.WIDGET_TOKEN_INVALID, "Invalid or revoked widget key"),
    )


def _resolve_token(db: Session, authorization: str | None) -> WidgetToken:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized()
    plain = authorization.removeprefix("Bearer ").strip()
    if not plain.startswith(TOKEN_PREFIX):
        raise _unauthorized()
    token = db.query(WidgetToken).filter(WidgetToken.token_hash == _hash(plain)).first()
    if token is None:
        raise _unauthorized()

    still_member = (
        db.query(HouseholdMember)
        .filter(
            HouseholdMember.household_id == token.household_id,
            HouseholdMember.user_id == token.user_id,
        )
        .first()
    )
    if still_member is None:
        # Person hat den Haushalt verlassen → Schlüssel aufräumen
        db.delete(token)
        db.commit()
        raise _unauthorized()
    return token


@router.get("/summary", response_model=WidgetSummary)
@limiter.limit("30/minute")
def widget_summary(
    request: Request,
    response: Response,
    lang: str = Query("de", pattern="^(de|en)$"),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
):
    token = _resolve_token(db, authorization)
    household = db.get(Household, token.household_id)
    user = db.get(User, token.user_id)
    tz = zoneinfo.ZoneInfo(household.timezone or "Europe/Zurich")
    today = household_today(household)

    due = due_items(db, household, token.user_id, locale=lang)

    shopping_query = db.query(ShoppingItem).filter(
        ShoppingItem.household_id == household.id,
        ShoppingItem.is_checked == False,  # noqa: E712
    )
    shopping_items = shopping_query.order_by(ShoppingItem.created_at.asc()).limit(MAX_SHOPPING_ITEMS).all()

    events = (
        db.query(Event)
        .filter(
            Event.household_id == household.id,
            # Auch mehrtägige Termine, die heute noch laufen (PD-K3)
            on_day(today, tz),
        )
        .order_by(Event.all_day.desc(), Event.starts_at.asc())
        .limit(MAX_EVENTS)
        .all()
    )

    token.last_used_at = datetime.now(timezone.utc)
    db.commit()

    # Persönliche Daten: nicht in Proxies/Browser-Caches ablegen
    response.headers["Cache-Control"] = "no-store"
    return WidgetSummary(
        household=household.name,
        user=user.display_name,
        date=today,
        generated_at=datetime.now(timezone.utc),
        due_count=len(due),
        due=[WidgetDueItem(**vars(i)) for i in due[:MAX_DUE_ITEMS]],
        shopping=WidgetShopping(
            open_count=shopping_query.count(),
            items=[f"{i.quantity} {i.name}" if i.quantity else i.name for i in shopping_items],
        ),
        events=[
            WidgetEvent(
                title=e.title,
                # Ganztägig oder seit einem früheren Tag laufend → keine Startzeit
                time=None
                if e.all_day or to_household_time(e.starts_at, tz).date() != today
                else to_household_time(e.starts_at, tz).strftime("%H:%M"),
            )
            for e in events
        ],
    )
