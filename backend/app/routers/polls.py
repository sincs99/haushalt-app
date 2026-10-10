import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import (
    Calendar,
    Event,
    EventPoll,
    EventPollOption,
    EventPollVote,
    Household,
    HouseholdMember,
    MealPlanEntry,
    Recipe,
)
from app.routers.events import _event_response
from app.routers.food import meal_plan_entry_payload, upsert_meal_plan_entry
from app.services.event_times import (
    all_day_start_utc,
    household_tz,
    to_household_time,
    to_utc,
    wall_time_to_utc,
)
from app.services.household_time import household_today
from app.services.locking import lock_row
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class PollVoteResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PollOptionCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=100)
    starts_at: datetime | None = None
    recipe_id: uuid.UUID | None = None


class PollOptionResponse(BaseModel):
    id: uuid.UUID
    label: str
    starts_at: datetime | None
    recipe_id: uuid.UUID | None
    votes: list[PollVoteResponse]

    model_config = ConfigDict(from_attributes=True)


class PollCreate(BaseModel):
    question: str = Field(..., min_length=1, max_length=200)
    options: list[PollOptionCreate] = Field(..., min_length=2, max_length=20)
    poll_type: str = Field(default="event", pattern=r"^(event|meal)$")
    meal_date: date | None = None


class PollResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    question: str
    status: str
    poll_type: str
    created_by_user_id: uuid.UUID
    decided_event_id: uuid.UUID | None
    decided_meal_date: date | None
    created_at: datetime
    options: list[PollOptionResponse]

    model_config = ConfigDict(from_attributes=True)


class VoteRequest(BaseModel):
    option_id: uuid.UUID


class DecideRequest(BaseModel):
    option_id: uuid.UUID
    event_title: str = Field(..., min_length=1, max_length=150)
    calendar_id: uuid.UUID


class MealDecideRequest(BaseModel):
    option_id: uuid.UUID
    # Belegten Tag überschreiben (PD-M1); ohne → 409 MEAL_PLAN_OCCUPIED
    replace: bool = False


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/polls",
    tags=["polls"],
)


# ---------------------------------------------------------------------------
# Hilfsfunktion: Poll laden (household-scoped, mit eager-load)
# ---------------------------------------------------------------------------
def _get_poll_or_404(
    poll_id: uuid.UUID,
    household_id: uuid.UUID,
    db: Session,
) -> EventPoll:
    poll = (
        db.query(EventPoll)
        .options(joinedload(EventPoll.options).joinedload(EventPollOption.votes))
        .filter(EventPoll.id == poll_id, EventPoll.household_id == household_id)
        .first()
    )
    if poll is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.POLL_NOT_FOUND, "Poll not found in this household"),
        )
    return poll


def _tz(db: Session, household_id: uuid.UUID):
    household = db.get(Household, household_id)
    return household_tz(household.timezone if household else None)


def _poll_response(poll: EventPoll, tz) -> PollResponse:
    """Response mit Optionszeiten in Haushaltszeit wie bei Terminen (CASA-60, PD-K5)."""
    response = PollResponse.model_validate(poll)
    for option in response.options:
        option.starts_at = to_household_time(option.starts_at, tz)
    return response


def _already_decided() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=error_detail(ErrorCode.POLL_ALREADY_DECIDED, "Poll has already been decided"),
    )


def _claim_poll(db: Session, poll_id: uuid.UUID) -> None:
    """Setzt den Status atomar von 'offen' auf 'entschieden'.

    Zwei gleichzeitige Entscheidungen sahen beide 'offen' und legten je einen Termin
    an. Das bedingte UPDATE lässt nur einen Request gewinnen; der andere bekommt
    POLL_ALREADY_DECIDED. Committet wird zusammen mit dem Ergebnis (Termin/Menüplan).
    """
    claimed = db.execute(
        update(EventPoll)
        .where(EventPoll.id == poll_id, EventPoll.status == "offen")
        .values(status="entschieden")
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed != 1:
        db.rollback()
        raise _already_decided()
    db.expire_all()


# ---------------------------------------------------------------------------
# GET /  — Alle Polls des Households
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[PollResponse])
def list_polls(
    household_id: uuid.UUID,
    status_filter: str | None = Query(None, alias="status"),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    query = (
        db.query(EventPoll)
        .options(joinedload(EventPoll.options).joinedload(EventPollOption.votes))
        .filter(EventPoll.household_id == household_id)
    )
    if status_filter is not None:
        query = query.filter(EventPoll.status == status_filter)
    tz = _tz(db, household_id)
    return [_poll_response(p, tz) for p in query.order_by(EventPoll.created_at.desc()).all()]


# ---------------------------------------------------------------------------
# POST /  — Poll erstellen
# ---------------------------------------------------------------------------
@router.post("/", response_model=PollResponse, status_code=status.HTTP_201_CREATED)
def create_poll(
    household_id: uuid.UUID,
    body: PollCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Für meal-Polls ist meal_date Pflicht
    if body.poll_type == "meal" and body.meal_date is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(
                ErrorCode.POLL_MEAL_DATE_REQUIRED,
                "meal_date is required for meal polls",
            ),
        )

    # Termin-Optionen brauchen eine Uhrzeit (PD-K2) — sonst entstünde beim
    # Entscheiden ein Termin "jetzt"
    if body.poll_type == "event" and any(opt.starts_at is None for opt in body.options):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.POLL_OPTION_TIME_REQUIRED,
                "Every option of an event poll needs starts_at",
            ),
        )

    poll = EventPoll(
        household_id=household_id,
        question=body.question,
        status="offen",
        poll_type=body.poll_type,
        created_by_user_id=membership.user_id,
    )
    # Für meal-Polls: decided_meal_date vorbelegen
    if body.poll_type == "meal":
        poll.decided_meal_date = body.meal_date
    db.add(poll)
    db.flush()

    # F-1 / CASA-21: recipe_ids müssen zum Household gehören — für ALLE Typen, sonst
    # hängt eine Termin-Abstimmung an einem fremden Rezept (Löschen dort setzt hier NULL)
    recipe_ids = {opt.recipe_id for opt in body.options if opt.recipe_id is not None}
    if recipe_ids:
        valid_count = (
            db.query(func.count(Recipe.id))
            .filter(Recipe.id.in_(recipe_ids), Recipe.household_id == household_id)
            .scalar()
        )
        if valid_count != len(recipe_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_detail(
                    ErrorCode.POLL_OPTION_INVALID,
                    "One or more recipe_ids do not belong to this household",
                ),
            )

    # Optionszeiten ohne Offset gelten wie bei Terminen als Haushaltszeit
    # (Sommerzeit-Lücke → 422 EVENT_TIME_NONEXISTENT)
    tz = _tz(db, household_id)
    for opt in body.options:
        option = EventPollOption(
            poll_id=poll.id,
            household_id=household_id,
            label=opt.label,
            starts_at=wall_time_to_utc(opt.starts_at, tz) if opt.starts_at is not None else None,
            recipe_id=opt.recipe_id,
        )
        db.add(option)

    db.commit()
    db.refresh(poll)

    # Reload mit eager-load für Response
    poll = _get_poll_or_404(poll.id, household_id, db)

    response = _poll_response(poll, tz)
    emit_to_household_sync(
        str(household_id),
        "poll_created",
        response.model_dump(mode="json"),
    )
    return response


# ---------------------------------------------------------------------------
# GET /{poll_id}  — Einzelner Poll
# ---------------------------------------------------------------------------
@router.get("/{poll_id}", response_model=PollResponse)
def get_poll(
    household_id: uuid.UUID,
    poll_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return _poll_response(_get_poll_or_404(poll_id, household_id, db), _tz(db, household_id))


# ---------------------------------------------------------------------------
# DELETE /{poll_id}  — Poll löschen
# ---------------------------------------------------------------------------
@router.delete("/{poll_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_poll(
    household_id: uuid.UUID,
    poll_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    poll = _get_poll_or_404(poll_id, household_id, db)
    db.delete(poll)
    db.commit()

    emit_to_household_sync(
        str(household_id),
        "poll_deleted",
        {"id": str(poll_id)},
    )


# ---------------------------------------------------------------------------
# POST /{poll_id}/vote  — Stimme abgeben / wechseln
# ---------------------------------------------------------------------------
@router.post("/{poll_id}/vote", response_model=PollResponse)
def vote_poll(
    household_id: uuid.UUID,
    poll_id: uuid.UUID,
    body: VoteRequest,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    poll = _get_poll_or_404(poll_id, household_id, db)

    # Entschiedene Abstimmungen sind abgeschlossen
    if poll.status != "offen":
        raise _already_decided()

    # Prüfe, dass option_id zu einer Option dieses Polls gehört
    option_ids = {opt.id for opt in poll.options}
    if body.option_id not in option_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.POLL_OPTION_INVALID, "Option does not belong to this poll"),
        )

    user_id = membership.user_id

    # Bestehende Stimme des Users in diesem Poll suchen
    existing_vote = (
        db.query(EventPollVote)
        .filter(
            EventPollVote.poll_id == poll_id,
            EventPollVote.user_id == user_id,
        )
        .first()
    )

    if existing_vote is not None:
        if existing_vote.option_id == body.option_id:
            # Gleiche Option → keine Änderung, Poll neu laden
            poll = _get_poll_or_404(poll_id, household_id, db)
            return _poll_response(poll, _tz(db, household_id))
        # Andere Option → alte Stimme löschen
        db.delete(existing_vote)
        db.flush()

    # Neue Stimme erstellen. Unique (poll_id, user_id): bei gleichzeitigen Requests
    # derselben Person gewinnt eine Stimme, die andere wird verworfen.
    vote = EventPollVote(
        poll_id=poll_id,
        option_id=body.option_id,
        user_id=user_id,
        household_id=household_id,
    )
    db.add(vote)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()

    # Reload für Response
    poll = _get_poll_or_404(poll_id, household_id, db)

    response = _poll_response(poll, _tz(db, household_id))
    emit_to_household_sync(
        str(household_id),
        "poll_voted",
        response.model_dump(mode="json"),
    )
    return response


# ---------------------------------------------------------------------------
# POST /{poll_id}/decide  — Poll entscheiden → Event erstellen
# ---------------------------------------------------------------------------
@router.post("/{poll_id}/decide", response_model=PollResponse)
def decide_poll(
    household_id: uuid.UUID,
    poll_id: uuid.UUID,
    body: DecideRequest,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    poll = _get_poll_or_404(poll_id, household_id, db)

    # Essens-Abstimmungen werden über /meal-decide entschieden (Menüplan statt Termin)
    if poll.poll_type != "event":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.POLL_TYPE_MISMATCH, "This is not an event poll"),
        )

    # Prüfe: Poll noch offen?
    if poll.status != "offen":
        raise _already_decided()

    # Prüfe, dass option_id zu einer Option dieses Polls gehört
    chosen_option = None
    for opt in poll.options:
        if opt.id == body.option_id:
            chosen_option = opt
            break

    if chosen_option is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.POLL_OPTION_INVALID, "Option does not belong to this poll"),
        )

    # Atomar schließen: nur ein gleichzeitiger Request darf entscheiden
    _claim_poll(db, poll_id)

    # Kalender NACH dem Claim in derselben Transaktion prüfen und sperren (CASA-20):
    # ein paralleles Löschen des Kalenders kann den Termin dann nicht mehr verlieren.
    # Ist er weg, wird der Claim zurückgerollt — die Abstimmung bleibt offen.
    calendar = lock_row(db, Calendar, body.calendar_id)
    if calendar is None or calendar.household_id != household_id:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.CALENDAR_MISMATCH, "Calendar does not belong to this household"),
        )

    # Event erstellen
    tz = _tz(db, household_id)
    if chosen_option.starts_at is not None:
        # Naive Werte aus der DB (SQLite) sind bereits UTC
        event_starts_at = to_utc(chosen_option.starts_at, timezone.utc)
        all_day = False
    else:
        # Altbestand ohne Uhrzeit (neue Termin-Optionen brauchen eine, PD-K2):
        # ganztägig am heutigen Haushaltsdatum statt "jetzt" mit Mikrosekunden
        event_starts_at = all_day_start_utc(household_today(db, household_id), tz)
        all_day = True
    event = Event(
        household_id=household_id,
        calendar_id=body.calendar_id,
        title=body.event_title,
        starts_at=event_starts_at,
        all_day=all_day,
        participant_ids=[],
        created_by_user_id=membership.user_id,
    )
    db.add(event)
    db.flush()

    # Poll schließen (Status wurde bereits atomar gesetzt)
    poll.decided_event_id = event.id
    db.commit()

    # Reload für Response
    poll = _get_poll_or_404(poll_id, household_id, db)

    response = _poll_response(poll, tz)
    emit_to_household_sync(
        str(household_id),
        "poll_decided",
        response.model_dump(mode="json"),
    )
    # Vollständiger Termin wie bei POST /events (Zeiten in Haushaltszeit): der
    # Kalender fügt das Objekt direkt in seine Liste ein
    emit_to_household_sync(
        str(household_id),
        "event_created",
        _event_response(event, tz).model_dump(mode="json"),
    )
    return response


# ---------------------------------------------------------------------------
# POST /{poll_id}/meal-decide  — Meal-Poll entscheiden → MealPlanEntry
# ---------------------------------------------------------------------------
@router.post("/{poll_id}/meal-decide", response_model=PollResponse)
def meal_decide_poll(
    household_id: uuid.UUID,
    poll_id: uuid.UUID,
    body: MealDecideRequest,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    poll = _get_poll_or_404(poll_id, household_id, db)

    # Prüfe: Poll muss meal-Typ sein
    if poll.poll_type != "meal":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(
                ErrorCode.POLL_TYPE_MISMATCH,
                "This is not a meal poll",
            ),
        )

    # Prüfe: Poll noch offen
    if poll.status != "offen":
        raise _already_decided()

    # Gewählte Option finden
    chosen_option = None
    for opt in poll.options:
        if opt.id == body.option_id:
            chosen_option = opt
            break
    if chosen_option is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(
                ErrorCode.POLL_OPTION_INVALID,
                "Option not in this poll",
            ),
        )

    # Atomar schließen: nur ein gleichzeitiger Request darf entscheiden
    _claim_poll(db, poll_id)

    # MealPlanEntry atomar anlegen (ON CONFLICT). Belegter Tag ohne replace → Claim
    # zurückrollen und 409 mit dem bestehenden Eintrag; die UI fragt nach (PD-M1).
    meal_date = poll.decided_meal_date or household_today(db, household_id)
    recipe_id = chosen_option.recipe_id
    free_text = chosen_option.label if not recipe_id else None
    entry = upsert_meal_plan_entry(
        db, household_id, meal_date, recipe_id, free_text, overwrite=body.replace
    )
    if entry is None:
        db.rollback()
        existing = (
            db.query(MealPlanEntry)
            .filter(MealPlanEntry.household_id == household_id, MealPlanEntry.date == meal_date)
            .first()
        )
        detail = error_detail(ErrorCode.MEAL_PLAN_OCCUPIED, "A meal is already planned for this date")
        if existing is not None:
            detail["entry"] = meal_plan_entry_payload(existing)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    # Poll schließen (Status wurde bereits atomar gesetzt)
    poll.decided_meal_date = meal_date
    db.commit()
    entry_payload = meal_plan_entry_payload(entry)

    # Reload
    poll = _get_poll_or_404(poll_id, household_id, db)

    # Socket-Events
    response = _poll_response(poll, _tz(db, household_id))
    emit_to_household_sync(
        str(household_id),
        "poll_decided",
        response.model_dump(mode="json"),
    )
    # Vollständiger Eintrag wie bei PUT /meal-plan — sonst zeigen andere Geräte
    # den Tag als leer an (CASA-19a)
    emit_to_household_sync(str(household_id), "meal_plan_updated", entry_payload)

    return response
