import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import (
    Event,
    EventPoll,
    EventPollOption,
    EventPollVote,
    HouseholdMember,
    MealPlanEntry,
    Recipe,
)
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
    event_category: str = Field(default="sonstiges", max_length=50)


class MealDecideRequest(BaseModel):
    option_id: uuid.UUID


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
    return query.order_by(EventPoll.created_at.desc()).all()


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

    # F-1 FIX: Validiere, dass alle recipe_ids zum Household gehören
    if body.poll_type == "meal":
        recipe_ids = [opt.recipe_id for opt in body.options if opt.recipe_id is not None]
        if recipe_ids:
            valid_count = (
                db.query(func.count(Recipe.id))
                .filter(Recipe.id.in_(recipe_ids), Recipe.household_id == household_id)
                .scalar()
            )
            if valid_count != len(set(recipe_ids)):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_detail(
                        ErrorCode.POLL_OPTION_INVALID,
                        "One or more recipe_ids do not belong to this household",
                    ),
                )

    for opt in body.options:
        option = EventPollOption(
            poll_id=poll.id,
            household_id=household_id,
            label=opt.label,
            starts_at=opt.starts_at,
            recipe_id=opt.recipe_id,
        )
        db.add(option)

    db.commit()
    db.refresh(poll)

    # Reload mit eager-load für Response
    poll = _get_poll_or_404(poll.id, household_id, db)

    emit_to_household_sync(
        str(household_id),
        "poll_created",
        PollResponse.model_validate(poll).model_dump(mode="json"),
    )
    return poll


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
    return _get_poll_or_404(poll_id, household_id, db)


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
            EventPollVote.option_id.in_(option_ids),
            EventPollVote.user_id == user_id,
        )
        .first()
    )

    if existing_vote is not None:
        if existing_vote.option_id == body.option_id:
            # Gleiche Option → keine Änderung, Poll neu laden
            poll = _get_poll_or_404(poll_id, household_id, db)
            return poll
        # Andere Option → alte Stimme löschen
        db.delete(existing_vote)
        db.flush()

    # Neue Stimme erstellen
    vote = EventPollVote(
        option_id=body.option_id,
        user_id=user_id,
        household_id=household_id,
    )
    db.add(vote)
    db.commit()

    # Reload für Response
    poll = _get_poll_or_404(poll_id, household_id, db)

    emit_to_household_sync(
        str(household_id),
        "poll_voted",
        PollResponse.model_validate(poll).model_dump(mode="json"),
    )
    return poll


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

    # Prüfe: Poll noch offen?
    if poll.status != "offen":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.POLL_ALREADY_DECIDED, "Poll has already been decided"),
        )

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

    # Event erstellen
    event_starts_at = chosen_option.starts_at or datetime.now(timezone.utc)
    event = Event(
        household_id=household_id,
        title=body.event_title,
        starts_at=event_starts_at,
        all_day=False,
        category=body.event_category,
        participant_ids=[],
        created_by_user_id=membership.user_id,
    )
    db.add(event)
    db.flush()

    # Poll schließen
    poll.status = "entschieden"
    poll.decided_event_id = event.id
    db.commit()

    # Reload für Response
    poll = _get_poll_or_404(poll_id, household_id, db)

    emit_to_household_sync(
        str(household_id),
        "poll_decided",
        PollResponse.model_validate(poll).model_dump(mode="json"),
    )
    emit_to_household_sync(
        str(household_id),
        "event_created",
        {"id": str(event.id), "title": event.title},
    )
    return poll


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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(
                ErrorCode.POLL_ALREADY_DECIDED,
                "Poll already decided",
            ),
        )

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

    # MealPlanEntry erzeugen (Upsert: wenn Datum schon belegt, updaten)
    meal_date = poll.decided_meal_date or date.today()

    existing = (
        db.query(MealPlanEntry)
        .filter(
            MealPlanEntry.household_id == household_id,
            MealPlanEntry.date == meal_date,
        )
        .first()
    )

    if existing:
        existing.recipe_id = chosen_option.recipe_id
        existing.free_text = chosen_option.label if not chosen_option.recipe_id else None
    else:
        entry = MealPlanEntry(
            household_id=household_id,
            date=meal_date,
            recipe_id=chosen_option.recipe_id,
            free_text=chosen_option.label if not chosen_option.recipe_id else None,
        )
        db.add(entry)

    # Poll schließen
    poll.status = "entschieden"
    poll.decided_meal_date = meal_date
    db.commit()

    # Reload
    poll = _get_poll_or_404(poll_id, household_id, db)

    # Socket-Events
    emit_to_household_sync(
        str(household_id),
        "poll_decided",
        PollResponse.model_validate(poll).model_dump(mode="json"),
    )
    emit_to_household_sync(
        str(household_id),
        "meal_plan_updated",
        {"date": str(meal_date)},
    )

    return poll
