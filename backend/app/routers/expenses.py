import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Expense, ExpenseShare, Household, HouseholdMember, Settlement
from app.services.household_checks import assert_users_in_household
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class ExpenseShareInput(BaseModel):
    user_id: uuid.UUID
    amount_rappen: int = Field(..., ge=0)


class ExpenseCreate(BaseModel):
    description: str = Field(..., min_length=1, max_length=200)
    amount_rappen: int = Field(..., gt=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    paid_by_user_id: uuid.UUID
    expense_date: date | None = None  # Default: heute (server-seitig)
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


class ExpenseUpdate(BaseModel):
    description: str | None = Field(None, min_length=1, max_length=200)
    amount_rappen: int | None = Field(None, gt=0)
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    paid_by_user_id: uuid.UUID | None = None
    expense_date: date | None = None
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
    created_at: datetime
    updated_at: datetime
    shares: list[ExpenseShareResponse]

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
    """
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


# ---------------------------------------------------------------------------
# GET  /  — Liste aller Ausgaben
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[ExpenseResponse])
def list_expenses(
    household_id: uuid.UUID,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return (
        db.query(Expense)
        .filter(Expense.household_id == household_id)
        .order_by(Expense.expense_date.desc(), Expense.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


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
    from sqlalchemy import func

    # 1. paid: Summe pro Payer (nur wo paid_by_user_id NOT NULL)
    paid_rows = (
        db.query(Expense.paid_by_user_id, func.sum(Expense.amount_rappen))
        .filter(
            Expense.household_id == household_id,
            Expense.paid_by_user_id.isnot(None),
        )
        .group_by(Expense.paid_by_user_id)
        .all()
    )
    paid_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in paid_rows}

    # 2. owed: Summe pro Share-Inhaber
    owed_rows = (
        db.query(ExpenseShare.user_id, func.sum(ExpenseShare.amount_rappen))
        .filter(ExpenseShare.household_id == household_id)
        .group_by(ExpenseShare.user_id)
        .all()
    )
    owed_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in owed_rows}

    # 3. unassigned: Expenses ohne Payer
    unassigned_result = (
        db.query(func.coalesce(func.sum(Expense.amount_rappen), 0))
        .filter(
            Expense.household_id == household_id,
            Expense.paid_by_user_id.is_(None),
        )
        .scalar()
    )
    unassigned_rappen = int(unassigned_result)

    # 4a. Settlement-Aggregationen
    # settled_out: Summe pro from_user_id (Schuldner hat gezahlt → verbessert seinen Saldo)
    settled_out_rows = (
        db.query(Settlement.from_user_id, func.sum(Settlement.amount_rappen))
        .filter(Settlement.household_id == household_id)
        .group_by(Settlement.from_user_id)
        .all()
    )
    settled_out_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in settled_out_rows}

    # settled_in: Summe pro to_user_id (Empfänger hat empfangen → reduziert sein Guthaben)
    settled_in_rows = (
        db.query(Settlement.to_user_id, func.sum(Settlement.amount_rappen))
        .filter(Settlement.household_id == household_id)
        .group_by(Settlement.to_user_id)
        .all()
    )
    settled_in_map: dict[uuid.UUID, int] = {row[0]: row[1] for row in settled_in_rows}

    # 4b. User-Menge: VEREINIGUNG aus aktuellen Mitgliedern + Payern + Share-Inhabern + Settlement-Beteiligte
    member_rows = (
        db.query(HouseholdMember.user_id)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    all_user_ids = (
        {m.user_id for m in member_rows}
        | set(paid_map.keys())
        | set(owed_map.keys())
        | set(settled_out_map.keys())
        | set(settled_in_map.keys())
    )

    # 5. BalanceEntries berechnen
    balances = []
    saldi: dict[uuid.UUID, int] = {}
    for uid in sorted(all_user_ids, key=str):  # deterministisch
        paid = paid_map.get(uid, 0)
        owed = owed_map.get(uid, 0)
        s_out = settled_out_map.get(uid, 0)
        s_in = settled_in_map.get(uid, 0)
        saldo = paid - owed + s_out - s_in
        saldi[uid] = saldo
        balances.append(BalanceEntry(
            user_id=uid,
            paid_rappen=paid,
            owed_rappen=owed,
            settled_out_rappen=s_out,
            settled_in_rappen=s_in,
            saldo_rappen=saldo,
        ))

    # 6. Settlements berechnen
    settlements_raw = compute_settlements(saldi)
    settlements = [SettlementEntry(**s) for s in settlements_raw]

    return BalancesResponse(
        balances=balances,
        settlements=settlements,
        unassigned_rappen=unassigned_rappen,
    )


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
        expense_date=body.expense_date or date.today(),
        split_type=body.split_type,
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

    emit_to_household_sync(
        household_id,
        "expense_created",
        ExpenseResponse.model_validate(expense).model_dump(mode="json"),
    )
    return expense


# ---------------------------------------------------------------------------
# PATCH /{expense_id}  — Ausgabe aktualisieren (partial update)
# ---------------------------------------------------------------------------
@router.patch("/{expense_id}", response_model=ExpenseResponse)
def update_expense(
    household_id: uuid.UUID,
    expense_id: uuid.UUID,
    body: ExpenseUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    expense = db.get(Expense, expense_id)
    if expense is None or expense.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.EXPENSE_NOT_FOUND, "Expense not found in this household"),
        )

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

    # Einfache Felder aktualisieren (außer split-spezifische)
    simple_fields = {"description", "currency", "paid_by_user_id", "expense_date"}
    for field in simple_fields:
        if field in update_data:
            if field == "paid_by_user_id":
                assert_users_in_household(db, household_id, [update_data[field]])
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
                assert_users_in_household(db, household_id, body.participant_ids)
                user_ids = body.participant_ids
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
            assert_users_in_household(db, household_id, share_user_ids)
            validate_custom_shares(amount, shares_input)
            share_map = {s.user_id: s.amount_rappen for s in shares_input}

        # Alte Shares löschen
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

    db.commit()
    db.refresh(expense)

    emit_to_household_sync(
        household_id,
        "expense_updated",
        ExpenseResponse.model_validate(expense).model_dump(mode="json"),
    )
    return expense


# ---------------------------------------------------------------------------
# DELETE /{expense_id}  — Ausgabe löschen
# ---------------------------------------------------------------------------
@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    household_id: uuid.UUID,
    expense_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    expense = db.get(Expense, expense_id)
    if expense is None or expense.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.EXPENSE_NOT_FOUND, "Expense not found in this household"),
        )

    db.delete(expense)
    db.commit()

    emit_to_household_sync(
        household_id,
        "expense_deleted",
        {"id": str(expense_id), "household_id": str(household_id)},
    )
