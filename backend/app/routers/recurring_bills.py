import uuid
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Expense, ExpenseShare, Household, HouseholdMember, RecurringBill
from app.routers.expenses import ExpenseResponse, split_evenly
from app.services.household_checks import assert_users_in_household
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class RecurringBillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    amount_rappen: int = Field(..., gt=0)
    day_of_month: int = Field(..., ge=1, le=28)
    category: str | None = Field(None, max_length=50)
    split_type: Literal["even", "custom"] = "even"
    active: bool = True
    paid_by_user_id: uuid.UUID | None = None


class RecurringBillUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    amount_rappen: int | None = Field(None, gt=0)
    day_of_month: int | None = Field(None, ge=1, le=28)
    category: str | None = Field(None, max_length=50)
    split_type: Literal["even", "custom"] | None = None
    active: bool | None = None
    paid_by_user_id: uuid.UUID | None = None


class BookBillRequest(BaseModel):
    # Zahler dieser Buchung; ohne Angabe gilt der Standard-Zahler der Rechnung
    paid_by_user_id: uuid.UUID | None = None


class RecurringBillResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    amount_rappen: int
    day_of_month: int
    category: str | None
    split_type: str
    active: bool
    paid_by_user_id: uuid.UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


def _already_booked() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=error_detail(ErrorCode.BILL_ALREADY_BOOKED, "This bill has already been booked for the current month"),
    )


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/recurring-bills",
    tags=["recurring-bills"],
)


# ---------------------------------------------------------------------------
# GET /  — Liste aller Bills
# ---------------------------------------------------------------------------
@router.get("/", response_model=list[RecurringBillResponse])
def list_recurring_bills(
    household_id: uuid.UUID,
    include_inactive: bool = Query(False),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    q = db.query(RecurringBill).filter(RecurringBill.household_id == household_id)

    if not include_inactive:
        q = q.filter(RecurringBill.active == True)  # noqa: E712

    return q.order_by(RecurringBill.day_of_month, RecurringBill.name).all()


# ---------------------------------------------------------------------------
# POST /  — Bill erstellen
# ---------------------------------------------------------------------------
@router.post("/", response_model=RecurringBillResponse, status_code=status.HTTP_201_CREATED)
def create_recurring_bill(
    household_id: uuid.UUID,
    body: RecurringBillCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    if body.paid_by_user_id is not None:
        assert_users_in_household(db, household_id, [body.paid_by_user_id])

    bill = RecurringBill(
        household_id=household_id,
        paid_by_user_id=body.paid_by_user_id,
        name=body.name,
        amount_rappen=body.amount_rappen,
        day_of_month=body.day_of_month,
        category=body.category,
        split_type=body.split_type,
        active=body.active,
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)

    emit_to_household_sync(
        household_id,
        "recurring_bill_created",
        RecurringBillResponse.model_validate(bill).model_dump(mode="json"),
    )
    return bill


# ---------------------------------------------------------------------------
# PATCH /{bill_id}  — Bill aktualisieren
# ---------------------------------------------------------------------------
@router.patch("/{bill_id}", response_model=RecurringBillResponse)
def update_recurring_bill(
    household_id: uuid.UUID,
    bill_id: uuid.UUID,
    body: RecurringBillUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    bill = db.get(RecurringBill, bill_id)
    if bill is None or bill.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.RECURRING_BILL_NOT_FOUND, "Recurring bill not found in this household"),
        )

    update_data = body.model_dump(exclude_unset=True)
    new_payer = update_data.get("paid_by_user_id")
    if new_payer is not None and new_payer != bill.paid_by_user_id:
        assert_users_in_household(db, household_id, [new_payer])
    for field, value in update_data.items():
        setattr(bill, field, value)

    db.commit()
    db.refresh(bill)

    emit_to_household_sync(
        household_id,
        "recurring_bill_updated",
        RecurringBillResponse.model_validate(bill).model_dump(mode="json"),
    )
    return bill


# ---------------------------------------------------------------------------
# DELETE /{bill_id}  — Bill löschen
# ---------------------------------------------------------------------------
@router.delete("/{bill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurring_bill(
    household_id: uuid.UUID,
    bill_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    bill = db.get(RecurringBill, bill_id)
    if bill is None or bill.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.RECURRING_BILL_NOT_FOUND, "Recurring bill not found in this household"),
        )

    db.delete(bill)
    db.commit()

    emit_to_household_sync(
        household_id,
        "recurring_bill_deleted",
        {"id": str(bill_id), "household_id": str(household_id)},
    )


# ---------------------------------------------------------------------------
# POST /{bill_id}/book  — Expense für aktuellen Monat erzeugen (idempotent)
# ---------------------------------------------------------------------------
@router.post("/{bill_id}/book", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
def book_recurring_bill(
    household_id: uuid.UUID,
    bill_id: uuid.UUID,
    body: BookBillRequest | None = Body(None),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # 1. Bill laden
    bill = db.get(RecurringBill, bill_id)
    if bill is None or bill.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.RECURRING_BILL_NOT_FOUND, "Recurring bill not found in this household"),
        )

    # 2. Prüfen ob aktiv
    if not bill.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.BILL_INACTIVE, "Recurring bill is inactive"),
        )

    # 3. Zahler: aus der Anfrage, sonst Standard-Zahler der Rechnung. Ohne Zahler
    #    würde allen eine Schuld ohne Gläubiger entstehen (Salden ergäben nicht 0).
    payer_id = (body.paid_by_user_id if body else None) or bill.paid_by_user_id
    if payer_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.BILL_PAYER_REQUIRED, "A payer is required to book this bill"),
        )
    assert_users_in_household(db, household_id, [payer_id])

    # 3b. Aktuellen Monat ermitteln
    today = date.today()
    first_of_month = date(today.year, today.month, 1)

    # 4. Idempotenz: Prüfen ob bereits gebucht (über booked_month, nicht expense_date —
    #    sonst erlaubt ein verschobenes Datum eine zweite Buchung)
    already_booked = (
        db.query(Expense.id)
        .filter(
            Expense.recurring_bill_id == bill.id,
            Expense.booked_month == first_of_month,
        )
        .first()
    )
    if already_booked:
        raise _already_booked()

    # 5. Expense erstellen
    expense_date = date(today.year, today.month, min(bill.day_of_month, 28))

    # Alle Household-Mitglieder für even-split
    members = (
        db.query(HouseholdMember.user_id)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    user_ids = [m.user_id for m in members]

    share_map = split_evenly(bill.amount_rappen, user_ids)

    # Household laden für Currency
    household = db.get(Household, household_id)

    expense = Expense(
        household_id=household_id,
        description=bill.name,
        amount_rappen=bill.amount_rappen,
        currency=household.currency,
        category=bill.category,
        split_type=bill.split_type,
        recurring_bill_id=bill.id,
        booked_month=first_of_month,
        expense_date=expense_date,
        paid_by_user_id=payer_id,
    )
    # Gleichzeitiger zweiter Klick: Unique-Constraint (recurring_bill_id, booked_month)
    # greift schon beim ersten Flush
    try:
        db.add(expense)
        db.flush()

        for uid, rappen in share_map.items():
            share = ExpenseShare(
                expense_id=expense.id,
                household_id=household_id,
                user_id=uid,
                amount_rappen=rappen,
            )
            db.add(share)

        db.commit()
    except IntegrityError:
        db.rollback()
        raise _already_booked()
    db.refresh(expense)

    # 6. Socket-Events
    expense_data = ExpenseResponse.model_validate(expense).model_dump(mode="json")

    emit_to_household_sync(household_id, "expense_created", expense_data)
    emit_to_household_sync(
        household_id,
        "recurring_bill_booked",
        {"bill_id": str(bill.id), "expense_id": str(expense.id), "household_id": str(household_id)},
    )

    return expense
