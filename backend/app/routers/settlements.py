import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Household, HouseholdMember, Settlement
from app.services.client_ids import commit_or_get_existing, get_existing_by_client_id
from app.services.finance_rules import MAX_AMOUNT_RAPPEN, assert_date_in_range
from app.services.household_checks import assert_settlement_parties
from app.services.household_time import household_today
from app.services.locking import lock_household, lock_row
from app.socket_manager import emit_to_household_sync

# Gleicher Ausgleich (Richtung + Betrag) innerhalb dieser Frist → vermutlich doppelt erfasst
DUPLICATE_WINDOW = timedelta(minutes=10)

# Plausibilitätswarnungen (PD-F3) — warnen, nicht hart ablehnen
WARNING_DUPLICATE_RECENT = "DUPLICATE_RECENT"
WARNING_EXCEEDS_OPEN_DEBT = "EXCEEDS_OPEN_DEBT"

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class SettlementCreate(BaseModel):
    # Client-generierte ID: Wiederholung (Retry, Doppelklick) liefert den bestehenden Ausgleich
    id: uuid.UUID | None = None
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    amount_rappen: int = Field(..., gt=0, le=MAX_AMOUNT_RAPPEN)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    settled_date: date | None = None  # Default: heute (server-seitig)
    note: str | None = Field(None, max_length=200)


class SettlementCheckResponse(BaseModel):
    warnings: list[str]
    open_debt_rappen: int


class SettlementResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    amount_rappen: int
    currency: str
    settled_date: date
    note: str | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    deleted_at: datetime | None = None
    deleted_by_user_id: uuid.UUID | None = None
    # Nur in der Create-Antwort: Plausibilitätswarnungen zum Zeitpunkt des Speicherns
    # (z. B. gleichzeitig von beiden Seiten erfasst) — der Ausgleich ist trotzdem gespeichert
    warnings: list[str] = []

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/settlements",
    tags=["settlements"],
)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=error_detail(ErrorCode.SETTLEMENT_NOT_FOUND, "Settlement not found in this household"),
    )


def _payload(settlement: Settlement) -> dict:
    return SettlementResponse.model_validate(settlement).model_dump(mode="json")


def plausibility_warnings(
    db: Session, household_id: uuid.UUID, body: "SettlementCreate"
) -> tuple[list[str], int]:
    """Warnungen für einen neuen Ausgleich + offene Schuld from→to (Rappen).

    Offene Schuld = was ``from`` insgesamt schuldet, höchstens so viel, wie ``to`` zugute
    hat (min(-saldo_from, saldo_to), nie negativ). Mehr zu zahlen ist möglich (Vorschuss),
    aber auffällig — z. B. wenn beide Seiten dieselbe Zahlung erfassen (CASA-08).
    """
    from app.services.balance_service import compute_all_balances

    warnings: list[str] = []
    cutoff = datetime.now(timezone.utc) - DUPLICATE_WINDOW
    duplicate = (
        db.query(Settlement.id)
        .filter(
            Settlement.household_id == household_id,
            Settlement.from_user_id == body.from_user_id,
            Settlement.to_user_id == body.to_user_id,
            Settlement.amount_rappen == body.amount_rappen,
            Settlement.deleted_at.is_(None),
            Settlement.created_at >= cutoff,
        )
        .first()
    )
    if duplicate:
        warnings.append(WARNING_DUPLICATE_RECENT)

    saldi = {
        b["user_id"]: b["saldo_rappen"]
        for b in compute_all_balances(db, household_id)["balances"]
    }
    open_debt = max(0, min(-saldi.get(body.from_user_id, 0), saldi.get(body.to_user_id, 0)))
    if body.amount_rappen > open_debt:
        warnings.append(WARNING_EXCEEDS_OPEN_DEBT)
    return warnings, open_debt


# GET / — Liste der Settlements (seitenweise)
@router.get("/", response_model=list[SettlementResponse])
def list_settlements(
    household_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    deleted: bool = Query(False, description="true: nur gelöschte Ausgleiche (Verlauf)"),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    q = db.query(Settlement).filter(Settlement.household_id == household_id)
    if deleted:
        q = q.filter(Settlement.deleted_at.isnot(None)).order_by(Settlement.deleted_at.desc())
    else:
        q = q.filter(Settlement.deleted_at.is_(None)).order_by(
            Settlement.settled_date.desc(), Settlement.created_at.desc(), Settlement.id
        )
    return q.offset(offset).limit(limit).all()


# POST /check — Plausibilität eines geplanten Ausgleichs prüfen (ohne Speichern)
@router.post("/check", response_model=SettlementCheckResponse)
def check_settlement(
    household_id: uuid.UUID,
    body: SettlementCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """PD-F3: Die UI fragt vor dem Speichern nach und lässt Warnungen bestätigen
    (doppelt erfasst? mehr als die offene Schuld?). Gespeichert wird trotzdem immer."""
    warnings, open_debt = plausibility_warnings(db, household_id, body)
    return SettlementCheckResponse(warnings=warnings, open_debt_rappen=open_debt)


# POST / — Neues Settlement
@router.post("/", response_model=SettlementResponse, status_code=status.HTTP_201_CREATED)
def create_settlement(
    household_id: uuid.UUID,
    body: SettlementCreate,
    response: Response,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Wiederholter Create mit gleicher Client-ID → bestehender Ausgleich, kein neues Event
    existing = get_existing_by_client_id(db, Settlement, body.id, household_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing

    # from != to
    if body.from_user_id == body.to_user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.SELF_SETTLEMENT_NOT_ALLOWED, "from_user_id and to_user_id must be different"),
        )

    # Mitglieder oder Ex-Mitglieder mit Ledger-Einträgen (mind. eine Seite aktuell)
    assert_settlement_parties(db, household_id, body.from_user_id, body.to_user_id)

    # Currency-Check
    household = db.get(Household, household_id)
    if body.currency is not None and body.currency != household.currency:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.CURRENCY_MISMATCH,
                f"Currency {body.currency} does not match household currency {household.currency}",
            ),
        )
    today = household_today(db, household)
    assert_date_in_range(body.settled_date, today, "settled_date")

    # Prüfen und Anlegen serialisiert pro Haushalt: erfassen Schuldner und Gläubiger
    # dieselbe Zahlung gleichzeitig, sieht der zweite den ersten als Duplikat und bekommt
    # die Warnung in der Antwort (warnen, nicht ablehnen — PD-F3)
    lock_household(db, household_id)
    warnings, _ = plausibility_warnings(db, household_id, body)

    settlement = Settlement(
        household_id=household_id,
        from_user_id=body.from_user_id,
        to_user_id=body.to_user_id,
        amount_rappen=body.amount_rappen,
        currency=household.currency,
        settled_date=body.settled_date or today,
        note=body.note,
        created_by_user_id=membership.user_id,  # aktueller User
    )
    if body.id is not None:
        settlement.id = body.id
    db.add(settlement)
    existing = commit_or_get_existing(db, Settlement, body.id, household_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return existing
    db.refresh(settlement)

    emit_to_household_sync(household_id, "settlement_created", _payload(settlement))
    result = SettlementResponse.model_validate(settlement)
    result.warnings = warnings
    return result


# DELETE /{settlement_id} — Settlement löschen (Soft Delete, wiederherstellbar)
@router.delete("/{settlement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_settlement(
    household_id: uuid.UUID,
    settlement_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    settlement = lock_row(db, Settlement, settlement_id)
    if settlement is None or settlement.household_id != household_id:
        raise _not_found()
    if settlement.deleted_at is not None:
        return  # idempotent

    settlement.deleted_at = datetime.now(timezone.utc)
    settlement.deleted_by_user_id = membership.user_id
    db.commit()

    emit_to_household_sync(
        household_id,
        "settlement_deleted",
        {
            "id": str(settlement_id),
            "household_id": str(household_id),
            "deleted_by_user_id": str(membership.user_id),
        },
    )


# POST /{settlement_id}/restore — Gelöschten Ausgleich wiederherstellen (Undo, Verlauf)
@router.post("/{settlement_id}/restore", response_model=SettlementResponse)
def restore_settlement(
    household_id: uuid.UUID,
    settlement_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    settlement = lock_row(db, Settlement, settlement_id)
    if settlement is None or settlement.household_id != household_id:
        raise _not_found()
    if settlement.deleted_at is None:
        return settlement  # idempotent

    settlement.deleted_at = None
    settlement.deleted_by_user_id = None
    db.commit()
    db.refresh(settlement)

    # Für alle Clients wie ein neuer Ausgleich (Listen-Upsert, Salden neu laden)
    emit_to_household_sync(household_id, "settlement_created", _payload(settlement))
    return settlement
