import uuid
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.core.patch_schema import PatchModel
from app.database import get_db
from app.models import Expense, ExpenseShare, Household, HouseholdMember
from app.services.finance_rules import (
    MAX_AMOUNT_RAPPEN,
    add_months,
    assert_date_in_range,
    is_before_last_settlement,
    last_settlement_by_pair,
    parse_if_match,
    validate_month,
)
from app.services.household_checks import assert_users_allowed, assert_users_in_household
from app.services.household_time import household_today
from app.services.locking import lock_row
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class ExpenseShareInput(BaseModel):
    user_id: uuid.UUID
    amount_rappen: int = Field(..., ge=0, le=MAX_AMOUNT_RAPPEN)


class ExpenseCreate(BaseModel):
    description: str = Field(..., min_length=1, max_length=200)
    amount_rappen: int = Field(..., gt=0, le=MAX_AMOUNT_RAPPEN)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    paid_by_user_id: uuid.UUID
    expense_date: date | None = None  # Default: heute (server-seitig)
    category: str | None = Field(None, max_length=50)
    split_type: Literal["even", "custom"]
    shares: list[ExpenseShareInput] | None = None
    participant_ids: list[uuid.UUID] | None = None

    @field_validator("description")
    @classmethod
    def description_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Description must not be blank")
        return v.strip()

    @model_validator(mode="after")
    def validate_split_fields(self):
        if self.split_type == "custom":
            if not self.shares:
                raise ValueError("shares required for split_type='custom'")
            if self.participant_ids is not None:
                raise ValueError("participant_ids not allowed for split_type='custom'")
        elif self.split_type == "even":
            if self.shares is not None:
                raise ValueError("shares not allowed for split_type='even'")
        return self


class ExpenseUpdate(PatchModel):
    # null auf NOT-NULL-Spalten von Expense → 422 (app/core/patch_schema.py)
    __orm_model__ = Expense

    description: str | None = Field(None, min_length=1, max_length=200)
    amount_rappen: int | None = Field(None, gt=0, le=MAX_AMOUNT_RAPPEN)
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    paid_by_user_id: uuid.UUID | None = None
    expense_date: date | None = None
    category: str | None = Field(None, max_length=50)
    split_type: Literal["even", "custom"] | None = None
    shares: list[ExpenseShareInput] | None = None
    participant_ids: list[uuid.UUID] | None = None

    @field_validator("description")
    @classmethod
    def description_must_not_be_blank(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Description must not be blank")
        return v.strip() if v is not None else v

    @model_validator(mode="after")
    def validate_split_fields(self):
        if self.split_type == "custom":
            if self.shares is not None and len(self.shares) == 0:
                raise ValueError("shares must not be empty for split_type='custom'")
            if self.participant_ids is not None:
                raise ValueError("participant_ids not allowed for split_type='custom'")
        elif self.split_type == "even":
            if self.shares is not None:
                raise ValueError("shares not allowed for split_type='even'")
        return self


class ExpenseShareResponse(BaseModel):
    user_id: uuid.UUID
    amount_rappen: int

    model_config = ConfigDict(from_attributes=True)


class ExpenseResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    description: str
    amount_rappen: int
    currency: str
    split_type: str
    paid_by_user_id: uuid.UUID | None
    expense_date: date
    category: str | None
    recurring_bill_id: uuid.UUID | None
    booked_month: date | None = None
    created_at: datetime
    updated_at: datetime
    shares: list[ExpenseShareResponse]
    # Optimistic Locking + Nachvollziehbarkeit (PD-F1/PD-F7)
    version: int
    created_by_user_id: uuid.UUID | None = None
    updated_by_user_id: uuid.UUID | None = None
    deleted_at: datetime | None = None
    deleted_by_user_id: uuid.UUID | None = None
    # Datiert auf/vor dem letzten Ausgleich zwischen Beteiligten → Ändern/Löschen
    # verschiebt bereits ausgeglichene Salden (PD-F2, UI warnt)
    before_last_settlement: bool = False

    model_config = ConfigDict(from_attributes=True)


class BalanceEntry(BaseModel):
    user_id: uuid.UUID
    paid_rappen: int      # Summe aller Expenses, die dieser User bezahlt hat
    owed_rappen: int      # Summe aller Shares dieses Users
    settled_out_rappen: int   # Summe von Settlements, in denen dieser User FROM ist (hat gezahlt)
    settled_in_rappen: int    # Summe von Settlements, in denen dieser User TO ist (hat empfangen)
    saldo_rappen: int     # paid - owed + settled_out - settled_in


class SettlementEntry(BaseModel):
    from_user_id: uuid.UUID    # Schuldner
    to_user_id: uuid.UUID      # Gläubiger
    amount_rappen: int


class BalancesResponse(BaseModel):
    balances: list[BalanceEntry]
    settlements: list[SettlementEntry]
    unassigned_rappen: int  # Summe von Expenses mit paid_by_user_id IS NULL


# ---------------------------------------------------------------------------
# Service-Funktionen
# ---------------------------------------------------------------------------


def split_evenly(amount_rappen: int, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Ganzzahldivision, Rest-Rappen von vorne verteilen.
    Sortiert user_ids deterministisch nach UUID-String.

    Doppelte user_ids werden abgelehnt — im Dict würden sie zusammenfallen und die
    Anteile ergäben nicht mehr den Gesamtbetrag.
    """
    if len(set(user_ids)) != len(user_ids):
        raise HTTPException(422, detail=error_detail(ErrorCode.DUPLICATE_SHARE_USER, "Duplicate user in participant_ids"))
    sorted_ids = sorted(user_ids, key=str)
    base, rest = divmod(amount_rappen, len(sorted_ids))
    return {uid: base + (1 if i < rest else 0) for i, uid in enumerate(sorted_ids)}


def validate_custom_shares(amount_rappen: int, shares: list[ExpenseShareInput]) -> None:
    """Wirft HTTPException 422 wenn Summe != amount, doppelte user_ids, oder leere Liste."""
    if not shares:
        raise HTTPException(422, detail=error_detail(ErrorCode.SHARES_EMPTY, "shares must not be empty"))
    seen: set[uuid.UUID] = set()
    for s in shares:
        if s.user_id in seen:
            raise HTTPException(422, detail=error_detail(ErrorCode.DUPLICATE_SHARE_USER, f"Duplicate user_id: {s.user_id}"))
        seen.add(s.user_id)
    total = sum(s.amount_rappen for s in shares)
    if total != amount_rappen:
        diff = total - amount_rappen
        raise HTTPException(422, detail=error_detail(ErrorCode.SHARES_SUM_MISMATCH, f"shares sum ({total}) != amount ({amount_rappen}), diff={diff}"))


def compute_settlements(saldi: dict[uuid.UUID, int]) -> list[dict]:
    """Greedy Settlement-Berechnung.

    Invarianten:
    - SUM(settlements pro User als from) - SUM(als to) == -saldo des Users
    - Nach Anwendung aller Settlements sind alle Salden 0 (sofern SUM(saldi) == 0)
    - Kein Settlement mit amount_rappen <= 0
    - Maximal (Anzahl beteiligter User - 1) Transaktionen

    Bei SUM(saldi) != 0 (z.B. wegen unassigned_rappen): gleicht aus was
    ausgleichbar ist, kein Fehler.
    """
    # Nur Einträge mit saldo != 0
    creditors = []  # (saldo, uid) — saldo > 0
    debtors = []    # (|saldo|, uid) — saldo < 0

    for uid, saldo in saldi.items():
        if saldo > 0:
            creditors.append([saldo, uid])
        elif saldo < 0:
            debtors.append([-saldo, uid])

    # Sortieren: absteigend nach Betrag, bei Gleichheit deterministisch nach UUID-String
    creditors.sort(key=lambda x: (-x[0], str(x[1])))
    debtors.sort(key=lambda x: (-x[0], str(x[1])))

    settlements = []
    ci, di = 0, 0
    while ci < len(creditors) and di < len(debtors):
        transfer = min(creditors[ci][0], debtors[di][0])
        if transfer > 0:
            settlements.append({
                "from_user_id": debtors[di][1],
                "to_user_id": creditors[ci][1],
                "amount_rappen": transfer,
            })
        creditors[ci][0] -= transfer
        debtors[di][0] -= transfer
        if creditors[ci][0] == 0:
            ci += 1
        if debtors[di][0] == 0:
            di += 1

    return settlements


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/expenses",
    tags=["expenses"],
)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=error_detail(ErrorCode.EXPENSE_NOT_FOUND, "Expense not found in this household"),
    )


def expense_response(
    expense: Expense, pairs: dict | None = None, db: Session | None = None
) -> ExpenseResponse:
    """Response inkl. ``before_last_settlement`` (pairs vorab laden oder db mitgeben)."""
    if pairs is None and db is not None:
        pairs = last_settlement_by_pair(db, expense.household_id)
    data = ExpenseResponse.model_validate(expense)
    data.before_last_settlement = expense.deleted_at is None and is_before_last_settlement(
        expense, pairs or {}
    )
    return data


def _emit_payload(expense: Expense, db: Session) -> dict:
    return expense_response(expense, db=db).model_dump(mode="json")


def _load_locked(db: Session, household_id: uuid.UUID, expense_id: uuid.UUID) -> Expense:
    """Ausgabe sperren (SELECT … FOR UPDATE) und frisch lesen — serialisiert parallele
    Änderungen derselben Ausgabe; ohne Sperre entstanden doppelte Anteile (CASA-01)."""
    expense = lock_row(db, Expense, expense_id)
    if expense is None or expense.household_id != household_id:
        raise _not_found()
    return expense


def _check_version(expense: Expense, if_match: str | None, db: Session) -> None:
    expected = parse_if_match(if_match)
    if expected is not None and expected != expense.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                **error_detail(
                    ErrorCode.EXPENSE_VERSION_CONFLICT,
                    "The expense was changed in the meantime",
                ),
                # Aktueller Stand, damit der Client ohne zweiten Request neu laden kann
                "current": expense_response(expense, db=db).model_dump(mode="json"),
            },
        )


def _touch(expense: Expense, user_id: uuid.UUID) -> None:
    """Version + Bearbeiter setzen (auch wenn sich nur Anteile geändert haben)."""
    expense.version = (expense.version or 1) + 1
    expense.updated_at = datetime.now(timezone.utc)
    expense.updated_by_user_id = user_id


# ---------------------------------------------------------------------------
# GET  /  — Liste der Ausgaben (seitenweise)
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[ExpenseResponse])
def list_expenses(
    household_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    month: date | None = Query(None, description="Nur Ausgaben dieses Monats (YYYY-MM-01)"),
    deleted: bool = Query(False, description="true: nur gelöschte Ausgaben (Verlauf)"),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    q = db.query(Expense).filter(Expense.household_id == household_id)
    if month is not None:
        validate_month(month, household_today(db, household_id))
        q = q.filter(Expense.expense_date >= month, Expense.expense_date < add_months(month, 1))
    if deleted:
        q = q.filter(Expense.deleted_at.isnot(None)).order_by(Expense.deleted_at.desc())
    else:
        q = q.filter(Expense.deleted_at.is_(None)).order_by(
            Expense.expense_date.desc(), Expense.created_at.desc(), Expense.id
        )
    rows = q.offset(offset).limit(limit).all()
    pairs = last_settlement_by_pair(db, household_id)
    return [expense_response(e, pairs) for e in rows]


# Kein separates balances_updated-Event: Das Frontend refetcht GET /balances
# wenn expense_created/updated/deleted eintrifft. Vermeidet doppelte Logik.

# ---------------------------------------------------------------------------
# GET  /balances  — Salden + Settlement-Vorschläge
# ---------------------------------------------------------------------------
@router.get("/balances", response_model=BalancesResponse)
def get_balances(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    from app.services.balance_service import compute_all_balances

    result = compute_all_balances(db, household_id)
    return BalancesResponse(**result)


# ---------------------------------------------------------------------------
# GET  /{expense_id}  — Einzelne Ausgabe (auch gelöscht; z. B. Neu laden nach 409)
# ---------------------------------------------------------------------------
@router.get("/{expense_id}", response_model=ExpenseResponse)
def get_expense(
    household_id: uuid.UUID,
    expense_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    expense = db.get(Expense, expense_id)
    if expense is None or expense.household_id != household_id:
        raise _not_found()
    return expense_response(expense, db=db)


# ---------------------------------------------------------------------------
# POST /  — Neue Ausgabe erstellen
# ---------------------------------------------------------------------------
@router.post("/", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
def create_expense(
    household_id: uuid.UUID,
    body: ExpenseCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # 0. Haushalt laden und Currency prüfen
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
    assert_date_in_range(body.expense_date, today, "expense_date")

    # 1. paid_by_user_id muss Mitglied sein
    assert_users_in_household(db, household_id, [body.paid_by_user_id])

    # 2. Shares berechnen
    if body.split_type == "even":
        if body.participant_ids:
            assert_users_in_household(db, household_id, body.participant_ids)
            user_ids = body.participant_ids
        else:
            # Alle Household-Mitglieder
            members = (
                db.query(HouseholdMember.user_id)
                .filter(HouseholdMember.household_id == household_id)
                .all()
            )
            user_ids = [m.user_id for m in members]
        if not user_ids:
            raise HTTPException(422, detail=error_detail(ErrorCode.NO_PARTICIPANTS, "No participants for even split"))
        share_map = split_evenly(body.amount_rappen, user_ids)
    else:
        share_user_ids = [s.user_id for s in body.shares]
        assert_users_in_household(db, household_id, share_user_ids)
        validate_custom_shares(body.amount_rappen, body.shares)
        share_map = {s.user_id: s.amount_rappen for s in body.shares}

    # 3. Expense + Shares in einer Transaktion
    expense = Expense(
        household_id=household_id,
        description=body.description,
        amount_rappen=body.amount_rappen,
        currency=household.currency,
        paid_by_user_id=body.paid_by_user_id,
        expense_date=body.expense_date or today,
        split_type=body.split_type,
        category=body.category,
        created_by_user_id=membership.user_id,
    )
    db.add(expense)
    db.flush()  # ID generieren

    for uid, rappen in share_map.items():
        share = ExpenseShare(
            expense_id=expense.id,
            household_id=household_id,
            user_id=uid,
            amount_rappen=rappen,
        )
        db.add(share)

    db.commit()
    db.refresh(expense)

    payload = _emit_payload(expense, db)
    emit_to_household_sync(household_id, "expense_created", payload)
    return payload


# ---------------------------------------------------------------------------
# PATCH /{expense_id}  — Ausgabe aktualisieren (partial update)
# ---------------------------------------------------------------------------
@router.patch("/{expense_id}", response_model=ExpenseResponse)
def update_expense(
    household_id: uuid.UUID,
    expense_id: uuid.UUID,
    body: ExpenseUpdate,
    if_match: str | None = Header(None, alias="If-Match"),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    expense = _load_locked(db, household_id, expense_id)
    if expense.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.EXPENSE_DELETED, "The expense has been deleted"),
        )
    _check_version(expense, if_match, db)

    update_data = body.model_dump(exclude_unset=True)

    # Currency-Check bei Update
    if body.currency is not None:
        household = db.get(Household, household_id)
        if body.currency != household.currency:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.CURRENCY_MISMATCH,
                    f"Currency {body.currency} does not match household currency {household.currency}",
                ),
            )
    if "expense_date" in update_data:
        assert_date_in_range(body.expense_date, household_today(db, household_id), "expense_date")

    # Personen, die schon auf der Ausgabe stehen, dürfen inzwischen Ex-Mitglieder sein —
    # sonst ließe sich eine alte Ausgabe nicht einmal mehr umbenennen
    on_record = {s.user_id for s in expense.shares}
    if expense.paid_by_user_id is not None:
        on_record.add(expense.paid_by_user_id)
    existing_share_user_ids = [s.user_id for s in expense.shares]

    # Einfache Felder aktualisieren (außer split-spezifische)
    simple_fields = {"description", "currency", "paid_by_user_id", "expense_date", "category"}
    for field in simple_fields:
        if field in update_data:
            if field == "paid_by_user_id":
                if update_data[field] is None:
                    raise HTTPException(422, detail=error_detail(ErrorCode.USERS_NOT_IN_HOUSEHOLD, "paid_by_user_id must not be null"))
                assert_users_allowed(db, household_id, [update_data[field]], on_record)
            setattr(expense, field, update_data[field])

    # amount_rappen ändern
    if "amount_rappen" in update_data:
        expense.amount_rappen = update_data["amount_rappen"]

    # split_type aktualisieren falls im Payload
    if "split_type" in update_data:
        expense.split_type = update_data["split_type"]

    # Effektiver split_type: aus Payload oder DB
    effective_split_type = update_data.get("split_type", expense.split_type)

    # Validierung: kein Input darf still ignoriert werden
    if "shares" in update_data and effective_split_type == "even":
        raise HTTPException(422, detail=error_detail(ErrorCode.SHARES_SUM_MISMATCH, "shares only allowed for split_type='custom'"))
    if "participant_ids" in update_data and effective_split_type == "custom":
        raise HTTPException(422, detail=error_detail(ErrorCode.SHARES_SUM_MISMATCH, "participant_ids only allowed for split_type='even'"))

    # Shares neu berechnen wenn split_type, shares, participant_ids oder amount_rappen geändert
    needs_reshare = any(
        k in update_data for k in ("split_type", "shares", "participant_ids", "amount_rappen")
    )

    if needs_reshare:
        amount = expense.amount_rappen

        if effective_split_type == "even":
            if body.participant_ids:
                assert_users_allowed(db, household_id, body.participant_ids, on_record)
                user_ids = body.participant_ids
            elif "participant_ids" not in update_data and "split_type" not in update_data and existing_share_user_ids:
                # Nur Betrag geändert: auf die bisherigen Teilnehmer verteilen,
                # nicht auf alle aktuellen Mitglieder
                user_ids = existing_share_user_ids
            else:
                members = (
                    db.query(HouseholdMember.user_id)
                    .filter(HouseholdMember.household_id == household_id)
                    .all()
                )
                user_ids = [m.user_id for m in members]
            if not user_ids:
                raise HTTPException(422, detail=error_detail(ErrorCode.NO_PARTICIPANTS, "No participants for even split"))
            share_map = split_evenly(amount, user_ids)
        else:
            # custom
            shares_input = body.shares
            if not shares_input:
                raise HTTPException(422, detail=error_detail(ErrorCode.SHARES_EMPTY, "custom split requires shares when changing amount"))
            share_user_ids = [s.user_id for s in shares_input]
            assert_users_allowed(db, household_id, share_user_ids, on_record)
            validate_custom_shares(amount, shares_input)
            share_map = {s.user_id: s.amount_rappen for s in shares_input}

        # Alte Shares löschen (unter der Zeilensperre: es sind sicher die aktuellen)
        expense.shares.clear()
        db.flush()

        # Neue Shares anlegen
        for uid, rappen in share_map.items():
            share = ExpenseShare(
                expense_id=expense.id,
                household_id=household_id,
                user_id=uid,
                amount_rappen=rappen,
            )
            db.add(share)

    _touch(expense, membership.user_id)
    db.commit()
    db.refresh(expense)

    payload = _emit_payload(expense, db)
    emit_to_household_sync(household_id, "expense_updated", payload)
    return payload


# ---------------------------------------------------------------------------
# DELETE /{expense_id}  — Ausgabe löschen (Soft Delete, wiederherstellbar)
# ---------------------------------------------------------------------------
@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    household_id: uuid.UUID,
    expense_id: uuid.UUID,
    if_match: str | None = Header(None, alias="If-Match"),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    expense = _load_locked(db, household_id, expense_id)
    if expense.deleted_at is not None:
        # Wiederholtes Löschen (Retry, zweites Gerät): bereits erledigt
        return
    _check_version(expense, if_match, db)

    # Anteile und Rechnungsbezug bleiben erhalten — nur so kann "Rückgängig" exakt
    # wiederherstellen (inkl. Ex-Mitgliedern und gebuchtem Monat, CASA-03)
    expense.deleted_at = datetime.now(timezone.utc)
    expense.deleted_by_user_id = membership.user_id
    _touch(expense, membership.user_id)
    db.commit()

    emit_to_household_sync(
        household_id,
        "expense_deleted",
        {
            "id": str(expense_id),
            "household_id": str(household_id),
            "deleted_by_user_id": str(membership.user_id),
            "version": expense.version,
        },
    )


# ---------------------------------------------------------------------------
# POST /{expense_id}/restore  — Gelöschte Ausgabe wiederherstellen (Undo, Verlauf)
# ---------------------------------------------------------------------------
@router.post("/{expense_id}/restore", response_model=ExpenseResponse)
def restore_expense(
    household_id: uuid.UUID,
    expense_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Stellt exakt den gelöschten Datensatz wieder her (Anteile, Ex-Mitglieder,
    recurring_bill_id/booked_month). Keine erneute Mitgliedschaftsprüfung.

    Rechnungsbuchungen: Eine gelöschte Buchung gibt ihren Monat frei. Wurde der Monat
    inzwischen neu gebucht, scheitert das Wiederherstellen mit 409 BILL_ALREADY_BOOKED —
    sonst wäre die Rechnung doppelt gebucht.
    """
    expense = _load_locked(db, household_id, expense_id)
    if expense.deleted_at is None:
        return expense_response(expense, db=db)  # idempotent

    if expense.recurring_bill_id is not None and expense.booked_month is not None:
        rebooked = (
            db.query(Expense.id)
            .filter(
                Expense.recurring_bill_id == expense.recurring_bill_id,
                Expense.booked_month == expense.booked_month,
                Expense.deleted_at.is_(None),
                Expense.id != expense.id,
            )
            .first()
        )
        if rebooked:
            raise _bill_month_taken()

    expense.deleted_at = None
    expense.deleted_by_user_id = None
    _touch(expense, membership.user_id)
    try:
        db.commit()
    except IntegrityError:
        # Paralleles Buchen desselben Monats (partieller Unique-Index)
        db.rollback()
        raise _bill_month_taken() from None
    db.refresh(expense)

    # Für alle Clients wie eine neue Ausgabe (Listen-Upsert, Salden/Budget neu laden)
    payload = _emit_payload(expense, db)
    emit_to_household_sync(household_id, "expense_created", payload)
    return payload


def _bill_month_taken() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=error_detail(
            ErrorCode.BILL_ALREADY_BOOKED,
            "The bill has been booked again for this month; the deleted booking cannot be restored",
        ),
    )
