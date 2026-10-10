"""KI-Assistent: Status, Opt-in pro Haushalt und die Features (Rezept, Pflanzenpflege).

Jede Feature-Anfrage durchläuft:
1. Mitgliedschaft (``verify_household_access``)
2. Schlüssel konfiguriert (sonst 503 ``AI_NOT_CONFIGURED``)
3. Opt-in des Haushalts ``ai_enabled`` (sonst 403 ``AI_NOT_ENABLED``)
4. IP-Limit (slowapi, 10/min), Tageslimit des Haushalts (429 ``AI_DAILY_LIMIT_REACHED``)
   und der Person über alle Haushalte (429 ``AI_USER_DAILY_LIMIT_REACHED``, PD-A2)

Ergebnisse werden nicht gespeichert; das Frontend übernimmt sie über die
bestehenden Endpunkte (Rezepte, Einkaufsliste).
"""

import uuid
from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user, verify_household_access, verify_household_admin
from app.core.error_codes import ErrorCode, error_detail
from app.core.rate_limit import limiter
from app.database import get_db
from app.models import Household, HouseholdMember, User
from app.services.ai import plant_care, recipe, usage
from app.services.ai.errors import (
    AiBusy,
    AiDailyLimitReached,
    AiError,
    AiInvalidOutput,
    AiNotConfigured,
    AiPlantNotRecognized,
    AiRefused,
    AiUnavailable,
    AiUserDailyLimitReached,
)
from app.services.ai.schemas import (
    PlantCareAdvice,
    PlantCareRequest,
    RecipeSuggestionRequest,
    RecipeSuggestionResponse,
)
from app.socket_manager import emit_to_household_sync

AI_RATE_LIMIT = "10/minute"

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AiStatusResponse(BaseModel):
    enabled: bool
    daily_limit: int
    user_daily_limit: int


class AiSettingsResponse(BaseModel):
    ai_enabled: bool
    available: bool
    calls_today: int
    daily_limit: int
    # Persönliches Limit der anfragenden Person (über alle Haushalte)
    user_calls_today: int
    user_daily_limit: int


class AiSettingsUpdate(BaseModel):
    ai_enabled: bool


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

status_router = APIRouter(prefix="/api/ai", tags=["ai"])

router = APIRouter(prefix="/api/households/{household_id}/ai", tags=["ai"])


@status_router.get("/status", response_model=AiStatusResponse)
def get_ai_status(current_user: User = Depends(get_current_user)):
    """Ist der KI-Assistent auf diesem Server eingerichtet? (ohne Schlüssel: ``enabled=false``)"""
    return AiStatusResponse(
        enabled=settings.ai_available,
        daily_limit=settings.ai_daily_limit_per_household,
        user_daily_limit=settings.ai_daily_limit_per_user,
    )


def _get_household(db: Session, household_id: uuid.UUID) -> Household:
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.HOUSEHOLD_NOT_FOUND, "Household not found"),
        )
    return household


def _settings_response(db: Session, household: Household, user_id: uuid.UUID) -> AiSettingsResponse:
    return AiSettingsResponse(
        ai_enabled=household.ai_enabled,
        available=settings.ai_available,
        calls_today=usage.calls_today(db, household.id),
        daily_limit=settings.ai_daily_limit_per_household,
        user_calls_today=usage.user_calls_today(db, user_id),
        user_daily_limit=settings.ai_daily_limit_per_user,
    )


@router.get("/settings", response_model=AiSettingsResponse)
def get_ai_settings(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return _settings_response(db, _get_household(db, household_id), membership.user_id)


@router.put("/settings", response_model=AiSettingsResponse)
def update_ai_settings(
    household_id: uuid.UUID,
    body: AiSettingsUpdate,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    """Opt-in ein-/ausschalten (nur Admin). Auch ohne Schlüssel möglich, wirkt dann erst später."""
    household = _get_household(db, household_id)
    household.ai_enabled = body.ai_enabled
    db.commit()
    emit_to_household_sync(
        household_id,
        "household_updated",
        {"id": str(household.id), "name": household.name, "ai_enabled": household.ai_enabled},
    )
    return _settings_response(db, household, membership.user_id)


def require_ai_enabled(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
) -> uuid.UUID:
    """Mitglied + Schlüssel vorhanden + Opt-in des Haushalts."""
    if not settings.ai_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_detail(ErrorCode.AI_NOT_CONFIGURED, "AI assistant is not configured"),
        )
    if not _get_household(db, household_id).ai_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(ErrorCode.AI_NOT_ENABLED, "AI assistant is not enabled for this household"),
        )
    return household_id


# Fehler → (HTTP-Status, Code, Meldung). Reihenfolge: speziellste Klasse zuerst.
_ERROR_MAP: list[tuple[type[AiError], int, str, str]] = [
    (AiNotConfigured, 503, ErrorCode.AI_NOT_CONFIGURED, "AI assistant is not configured"),
    (AiDailyLimitReached, 429, ErrorCode.AI_DAILY_LIMIT_REACHED, "Daily AI limit reached for this household"),
    (AiUserDailyLimitReached, 429, ErrorCode.AI_USER_DAILY_LIMIT_REACHED, "Your personal daily AI limit is reached"),
    (AiRefused, 422, ErrorCode.AI_REFUSED, "The AI declined this request"),
    (AiPlantNotRecognized, 422, ErrorCode.AI_PLANT_NOT_RECOGNIZED, "The input was not recognized as a plant"),
    (AiInvalidOutput, 502, ErrorCode.AI_INVALID_OUTPUT, "The AI returned an unusable answer"),
    (AiBusy, 503, ErrorCode.AI_BUSY, "AI assistant is busy, try again shortly"),
    (AiUnavailable, 502, ErrorCode.AI_UNAVAILABLE, "AI service is unavailable"),
]

# Bei diesen Fehlern hat die API nicht geantwortet → Aufruf zählt nicht zum Tageslimit
_NOT_BILLED = (AiNotConfigured, AiBusy, AiUnavailable)


def _to_http(exc: AiError) -> HTTPException:
    for cls, code, error_code, message in _ERROR_MAP:
        if isinstance(exc, cls):
            return HTTPException(status_code=code, detail=error_detail(error_code, message))
    return HTTPException(status_code=502, detail=error_detail(ErrorCode.AI_UNAVAILABLE, "AI service error"))


ReqT = TypeVar("ReqT")
ResT = TypeVar("ResT")


def _run_feature(
    db: Session,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    feature: Callable[[ReqT], tuple[ResT, object]],
    body: ReqT,
) -> ResT:
    """Tageslimits reservieren → Feature aufrufen → Tokens verbuchen."""
    try:
        day = usage.reserve_call(db, household_id, user_id)
    except (AiDailyLimitReached, AiUserDailyLimitReached) as exc:
        raise _to_http(exc)

    try:
        result, call_usage = feature(body)
    except AiError as exc:
        if exc.usage is not None:
            usage.record_tokens(db, household_id, day, exc.usage)
        elif isinstance(exc, _NOT_BILLED):
            usage.release_call(db, household_id, user_id, day)
        raise _to_http(exc)
    except Exception:
        # Unerwarteter Fehler (Bug, unbekannte SDK-Ausnahme): keine verwertbare Antwort →
        # Reservierung zurückgeben statt das Limit still zu verbrauchen (CASA-33)
        usage.release_call(db, household_id, user_id, day)
        raise

    usage.record_tokens(db, household_id, day, call_usage)
    return result


@router.post("/recipe", response_model=RecipeSuggestionResponse)
@limiter.limit(AI_RATE_LIMIT)
def suggest_recipe(
    request: Request,
    body: RecipeSuggestionRequest,
    household_id: uuid.UUID = Depends(require_ai_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rezeptvorschlag aus vorhandenen Zutaten. Wird nicht gespeichert."""
    return _run_feature(db, household_id, current_user.id, recipe.generate_recipe, body)


@router.post("/plant-care", response_model=PlantCareAdvice)
@limiter.limit(AI_RATE_LIMIT)
def suggest_plant_care(
    request: Request,
    body: PlantCareRequest,
    household_id: uuid.UUID = Depends(require_ai_enabled),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pflegehinweise zu einer Pflanze (unabhängig von einem Pflanzen-Modell)."""
    return _run_feature(db, household_id, current_user.id, plant_care.get_plant_care, body)
