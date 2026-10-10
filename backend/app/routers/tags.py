"""Tags (NFC-Chips / QR-Sticker) — Verwaltung und Scan.

Verwaltung: ``/api/households/{household_id}/tags/`` — lesen dürfen alle
Mitglieder, Anlegen/Ändern/Löschen/Token-Neuerzeugung nur Admins.

Scan: ``POST /api/tags/resolve/{token}`` und ``POST /api/tags/{token}/execute``.
Der Token allein berechtigt zu nichts: beide Endpunkte verlangen einen
eingeloggten User, der Mitglied des Tag-Haushalts ist. Reihenfolge der
Prüfungen (siehe docs/security/tags-review.md):

1. Token unbekannt → 404 ``TAG_NOT_FOUND``
2. User nicht Mitglied des Tag-Haushalts → 403 ``NOT_HOUSEHOLD_MEMBER``
   (auch für deaktivierte Tags — Fremde erfahren nichts über den Zustand)
3. Tag deaktiviert → 410 ``TAG_DISABLED`` (der Chip existiert, ist aber
   ausser Betrieb; ein Admin kann ihn wieder aktivieren)
4. Ziel gelöscht → 404 ``TAG_TARGET_NOT_FOUND``

Tokens stehen nie in Log-Meldungen dieses Moduls; Access-Logs werden durch
``app.core.log_redaction`` geschwärzt.
"""

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.deps import (
    get_current_user,
    verify_household_access,
    verify_household_admin,
)
from app.core.error_codes import ErrorCode, error_detail
from app.core.patch_schema import PatchModel
from app.core.rate_limit import limiter
from app.database import get_db
from app.models import Household, HouseholdMember, Tag, User
from app.services.tag_actions import (
    TAG_ACTIONS,
    TagAction,
    TagContext,
    get_action,
    target_types,
)
from app.socket_manager import emit_to_household_sync

# Obergrenze pro Haushalt (Schutz vor versehentlichem Massenanlegen)
MAX_TAGS_PER_HOUSEHOLD = 200
# Längster Token, den wir je ausgeben; längere Pfade gar nicht erst abfragen
MAX_TOKEN_LENGTH = 64
# Pro IP. shared_limit mit festem Scope ist Pflicht: slowapi zählt sonst pro
# URL (key_style="url") — jeder geratene Token hätte sein eigenes Kontingent.
SCAN_RATE_LIMIT = "30/minute"


def generate_tag_token() -> str:
    """192 Bit Zufall, URL-sicher (32 Zeichen, ``[A-Za-z0-9_-]``)."""
    return secrets.token_urlsafe(24)


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class TagCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    target_type: str = Field(..., min_length=1, max_length=30)
    target_id: uuid.UUID | None = None
    action: str = Field(..., min_length=1, max_length=50)

    @field_validator("label")
    @classmethod
    def label_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("label must not be blank")
        return v.strip()


class TagUpdate(PatchModel):
    # null auf NOT-NULL-Spalten von Tag → 422 (app/core/patch_schema.py)
    __orm_model__ = Tag

    label: str | None = Field(None, min_length=1, max_length=80)
    enabled: bool | None = None
    # Chip neu zuordnen, ohne ihn neu zu beschreiben — wird zusammen validiert
    target_type: str | None = Field(None, min_length=1, max_length=30)
    target_id: uuid.UUID | None = None
    action: str | None = Field(None, min_length=1, max_length=50)

    @field_validator("label")
    @classmethod
    def label_not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("label must not be blank")
        return v.strip() if v is not None else v


class TagResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    token: str
    label: str
    target_type: str
    target_id: uuid.UUID | None
    target_name: str | None = None
    target_missing: bool = False
    action: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    last_used_at: datetime | None
    use_count: int
    enabled: bool

    model_config = ConfigDict(from_attributes=True)


class TargetOptionResponse(BaseModel):
    id: uuid.UUID
    name: str


class TargetActionInfo(BaseModel):
    key: str
    target_optional: bool
    navigate_only: bool


class TargetTypeResponse(BaseModel):
    target_type: str
    actions: list[TargetActionInfo]
    options: list[TargetOptionResponse]


class TagResolveResponse(BaseModel):
    tag_id: uuid.UUID
    label: str
    household_id: uuid.UUID
    household_name: str
    action: str
    target_type: str
    target_id: uuid.UUID | None
    target_name: str | None
    navigate_only: bool
    navigate_to: str | None
    description: str
    details: dict[str, Any]
    can_execute: bool
    reason: str | None


class TagExecuteRequest(BaseModel):
    # pet.feed: Slot überschreiben (Default nach Tageszeit)
    slot: Literal["morning", "evening"] | None = None


class TagExecuteResponse(BaseModel):
    tag_id: uuid.UUID
    action: str
    household_id: uuid.UUID
    target_name: str | None
    changed: bool
    result: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=error_detail(ErrorCode.TAG_NOT_FOUND, "Tag not found"),
    )


def _get_tag_or_404(db: Session, tag_id: uuid.UUID, household_id: uuid.UUID) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None or tag.household_id != household_id:
        raise _not_found()
    return tag


def _validate_definition(
    db: Session,
    household_id: uuid.UUID,
    target_type: str,
    action_key: str,
    target_id: uuid.UUID | None,
) -> TagAction:
    action = get_action(action_key)
    if action is None or action.target_type != target_type:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.TAG_ACTION_INVALID,
                "Unknown action or action does not match target type",
            ),
        )
    if target_id is None:
        if not action.target_optional:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(ErrorCode.TAG_TARGET_INVALID, "target_id is required for this action"),
            )
    elif action.load_target(db, household_id, target_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.TAG_TARGET_INVALID, "Target not found in this household"),
        )
    return action


def _target_display_name(target: Any) -> str | None:
    return getattr(target, "name", None) or getattr(target, "title", None)


def _tag_response(db: Session, tag: Tag) -> TagResponse:
    response = TagResponse.model_validate(tag)
    action = get_action(tag.action)
    if tag.target_id is not None:
        target = action.load_target(db, tag.household_id, tag.target_id) if action else None
        if target is None:
            response.target_missing = True
        else:
            response.target_name = _target_display_name(target)
    return response


def _emit_tag(db: Session, event: str, tag: Tag) -> None:
    emit_to_household_sync(
        tag.household_id, event, _tag_response(db, tag).model_dump(mode="json")
    )


def _load_scanned_tag(db: Session, token: str, user: User) -> tuple[Tag, HouseholdMember, Household]:
    """Token → Tag, inkl. Mitgliedschafts- und Aktiv-Prüfung (Reihenfolge siehe Modul-Doku)."""
    if not token or len(token) > MAX_TOKEN_LENGTH:
        raise _not_found()
    tag = db.query(Tag).filter(Tag.token == token).first()
    if tag is None:
        raise _not_found()
    membership = (
        db.query(HouseholdMember)
        .filter_by(household_id=tag.household_id, user_id=user.id)
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(ErrorCode.NOT_HOUSEHOLD_MEMBER, "Not a member of this household"),
        )
    if not tag.enabled:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=error_detail(ErrorCode.TAG_DISABLED, "Tag is disabled"),
        )
    household = db.get(Household, tag.household_id)
    return tag, membership, household


def _build_context(db: Session, tag: Tag, membership: HouseholdMember, household: Household) -> tuple[TagAction, TagContext]:
    action = get_action(tag.action)
    if action is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.TAG_ACTION_INVALID, "Tag action is no longer supported"),
        )
    target = None
    if tag.target_id is not None:
        target = action.load_target(db, tag.household_id, tag.target_id)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail(ErrorCode.TAG_TARGET_NOT_FOUND, "Tag target no longer exists"),
            )
    return action, TagContext(db=db, tag=tag, membership=membership, household=household, target=target)


def _record_use(db: Session, tag: Tag) -> None:
    tag.last_used_at = datetime.now(timezone.utc)
    # SQL-Ausdruck: atomar bei parallelen Scans
    tag.use_count = Tag.use_count + 1
    db.commit()
    db.refresh(tag)
    _emit_tag(db, "tag_updated", tag)


# ---------------------------------------------------------------------------
# Verwaltung (pro Haushalt)
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/tags",
    tags=["tags"],
)


@router.get("/", response_model=list[TagResponse])
def list_tags(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    tags = (
        db.query(Tag)
        .filter(Tag.household_id == household_id)
        .order_by(Tag.label, Tag.created_at)
        .all()
    )
    return [_tag_response(db, t) for t in tags]


# Muss VOR /{tag_id} stehen
@router.get("/targets", response_model=list[TargetTypeResponse])
def list_targets(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Zieltypen mit möglichen Aktionen und Zielen — für das Anlegen-Formular."""
    result = []
    for target_type in target_types():
        actions = [a for a in TAG_ACTIONS.values() if a.target_type == target_type]
        result.append(
            TargetTypeResponse(
                target_type=target_type,
                actions=[
                    TargetActionInfo(key=a.key, target_optional=a.target_optional, navigate_only=a.navigate_only)
                    for a in actions
                ],
                options=[
                    TargetOptionResponse(id=o.id, name=o.name)
                    for o in actions[0].list_targets(db, household_id)
                ],
            )
        )
    return result


@router.post("/", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
def create_tag(
    household_id: uuid.UUID,
    body: TagCreate,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    _validate_definition(db, household_id, body.target_type, body.action, body.target_id)

    count = db.query(Tag).filter(Tag.household_id == household_id).count()
    if count >= MAX_TAGS_PER_HOUSEHOLD:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.TOO_MANY_TAGS, f"At most {MAX_TAGS_PER_HOUSEHOLD} tags per household"),
        )

    tag = Tag(
        household_id=household_id,
        token=generate_tag_token(),
        label=body.label,
        target_type=body.target_type,
        target_id=body.target_id,
        action=body.action,
        created_by_user_id=membership.user_id,
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)

    _emit_tag(db, "tag_created", tag)
    return _tag_response(db, tag)


@router.patch("/{tag_id}", response_model=TagResponse)
def update_tag(
    household_id: uuid.UUID,
    tag_id: uuid.UUID,
    body: TagUpdate,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    tag = _get_tag_or_404(db, tag_id, household_id)
    data = body.model_dump(exclude_unset=True)

    if {"target_type", "target_id", "action"} & data.keys():
        target_type = data.get("target_type") or tag.target_type
        action = data.get("action") or tag.action
        target_id = data["target_id"] if "target_id" in data else tag.target_id
        _validate_definition(db, household_id, target_type, action, target_id)
        tag.target_type = target_type
        tag.action = action
        tag.target_id = target_id

    if data.get("label") is not None:
        tag.label = data["label"]
    if data.get("enabled") is not None:
        tag.enabled = data["enabled"]

    db.commit()
    db.refresh(tag)

    _emit_tag(db, "tag_updated", tag)
    return _tag_response(db, tag)


@router.post("/{tag_id}/regenerate-token", response_model=TagResponse)
def regenerate_tag_token(
    household_id: uuid.UUID,
    tag_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    """Neuer Token — der alte Chip/QR-Code ist danach wirkungslos (404)."""
    tag = _get_tag_or_404(db, tag_id, household_id)
    tag.token = generate_tag_token()
    db.commit()
    db.refresh(tag)

    _emit_tag(db, "tag_updated", tag)
    return _tag_response(db, tag)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    household_id: uuid.UUID,
    tag_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    tag = _get_tag_or_404(db, tag_id, household_id)
    db.delete(tag)
    db.commit()

    emit_to_household_sync(
        household_id,
        "tag_deleted",
        {"id": str(tag_id), "household_id": str(household_id)},
    )


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

scan_router = APIRouter(prefix="/api/tags", tags=["tags"])


@scan_router.post("/resolve/{token}", response_model=TagResolveResponse)
@limiter.shared_limit(SCAN_RATE_LIMIT, scope="tag-resolve")
def resolve_tag(
    request: Request,
    token: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Was würde dieser Tag tun? Ändert nichts — ausser bei reinen
    Navigations-Tags, deren Nutzung hier gezählt wird (es folgt kein execute)."""
    tag, membership, household = _load_scanned_tag(db, token, current_user)
    action, ctx = _build_context(db, tag, membership, household)
    description = action.describe(ctx)

    navigate_to = action.navigate_to(ctx) if action.navigate_to else None
    if action.navigate_only:
        _record_use(db, tag)

    return TagResolveResponse(
        tag_id=tag.id,
        label=tag.label,
        household_id=household.id,
        household_name=household.name,
        action=tag.action,
        target_type=tag.target_type,
        target_id=tag.target_id,
        target_name=description.target_name,
        navigate_only=action.navigate_only,
        navigate_to=navigate_to,
        description=description.description,
        details=description.details,
        can_execute=description.can_execute and not action.navigate_only,
        reason=description.reason,
    )


@scan_router.post("/{token}/execute", response_model=TagExecuteResponse)
@limiter.shared_limit(SCAN_RATE_LIMIT, scope="tag-execute")
def execute_tag(
    request: Request,
    token: str,
    body: TagExecuteRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tag, membership, household = _load_scanned_tag(db, token, current_user)
    action, ctx = _build_context(db, tag, membership, household)
    if action.execute is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.TAG_NOT_EXECUTABLE, "This tag only navigates"),
        )

    params = body.model_dump(exclude_none=True) if body else {}
    result = action.execute(ctx, params)
    target_name = _target_display_name(ctx.target) if ctx.target is not None else None
    _record_use(db, tag)

    return TagExecuteResponse(
        tag_id=tag.id,
        action=tag.action,
        household_id=household.id,
        target_name=target_name,
        changed=bool(result.get("changed", True)),
        result=result,
    )
