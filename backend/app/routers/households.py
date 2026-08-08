import calendar
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, verify_household_access, verify_household_admin
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import Budget, Expense, Household, HouseholdMember, RecurringBill, User
from app.services.invite_code import generate_unique_invite_code
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class HouseholdMemberResponse(BaseModel):
    id: uuid.UUID
    display_name: str
    role: str
    model_config = ConfigDict(from_attributes=True)


class JoinRequest(BaseModel):
    invite_code: str


class JoinResponse(BaseModel):
    id: uuid.UUID
    name: str


class InviteCodeResponse(BaseModel):
    invite_code: str


class HouseholdCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class HouseholdCreateResponse(BaseModel):
    id: uuid.UUID
    name: str
    role: str
    currency: str


class HouseholdUpdateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class HouseholdUpdateResponse(BaseModel):
    id: uuid.UUID
    name: str


# ---------------------------------------------------------------------------
# Router 1: Household-spezifische Endpoints (mit household_id im Pfad)
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}",
    tags=["households"],
)


@router.get("/members", response_model=list[HouseholdMemberResponse])
def list_household_members(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    members = (
        db.query(HouseholdMember)
        .options(joinedload(HouseholdMember.user))
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )
    return [
        HouseholdMemberResponse(
            id=m.user.id,
            display_name=m.user.display_name,
            role=m.role,
        )
        for m in members
    ]


@router.get("/invite-code", response_model=InviteCodeResponse)
def get_invite_code(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail=error_detail(ErrorCode.HOUSEHOLD_NOT_FOUND, "Household not found"))
    return InviteCodeResponse(invite_code=household.invite_code)


@router.patch("", response_model=HouseholdUpdateResponse)
def rename_household(
    household_id: uuid.UUID,
    body: HouseholdUpdateRequest,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail=error_detail(ErrorCode.HOUSEHOLD_NOT_FOUND, "Household not found"))

    household.name = body.name.strip()
    db.commit()

    result = HouseholdUpdateResponse(id=household.id, name=household.name)
    emit_to_household_sync(household_id, "household_updated", {"id": str(household.id), "name": household.name})
    return result


@router.post("/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_household(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Haushalt verlassen. Immer erlaubt — auch mit offenen Salden.

    Geschäftsregeln:
    - Letztes Mitglied → Haushalt wird komplett gelöscht (CASCADE)
    - Einziger Admin, aber andere Mitglieder → dienstältestes Mitglied wird Admin
    - Expenses/Shares werden NICHT gelöscht (Ehemaliges-Mitglied-Muster)
    - rotation_order wird NICHT bereinigt (Scheduler überspringt)
    """
    user_id = membership.user_id

    # Alle Mitglieder dieses Haushalts zählen
    all_members = (
        db.query(HouseholdMember)
        .filter(HouseholdMember.household_id == household_id)
        .all()
    )

    if len(all_members) <= 1:
        # Letztes Mitglied → Haushalt löschen
        household = db.get(Household, household_id)
        if household:
            db.delete(household)  # CASCADE löscht members, expenses, etc.
        db.commit()
        return  # Kein Event nötig bei Löschung

    # Prüfe ob Admin-Promotion nötig
    is_admin = membership.role == "admin"
    remaining = [m for m in all_members if m.id != membership.id]

    if is_admin:
        # Gibt es andere Admins?
        other_admins = [m for m in remaining if m.role == "admin"]
        if not other_admins:
            # Kein anderer Admin → dienstältestes Mitglied promoten
            # Sortierung: joined_at ASC, dann user_id ASC (deterministic tiebreaker)
            promoted = sorted(remaining, key=lambda m: (m.joined_at, str(m.user_id)))[0]
            promoted.role = "admin"

    db.delete(membership)
    db.commit()

    # Socket-Event NACH Commit
    # Hinweis: Die Room-Mitgliedschaft des Verlassenden besteht bis zu dessen Disconnect.
    # REST ist ab sofort durch verify_household_access dicht.
    # Das Frontend des Betroffenen reagiert auf das Event mit Socket-Reconnect.
    emit_to_household_sync(
        household_id,
        "household_member_left",
        {"household_id": str(household_id), "user_id": str(user_id)},
    )


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    """Mitglied entfernen (nur Admin). Admins können nicht entfernt werden.

    Sich selbst entfernt man über POST /leave, nicht über diesen Endpoint.

    Hinweis: Die Socket-Room-Mitgliedschaft des Entfernten besteht bis zu dessen
    Disconnect weiter; REST ist ab sofort durch verify_household_access dicht.
    Das Frontend des Betroffenen reagiert auf household_member_removed mit
    Socket-Reconnect — damit ist auch der Room bereinigt.
    """
    # Sich selbst entfernen → 422 (Verlassen-Endpoint nutzen)
    if user_id == membership.user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.CANNOT_REMOVE_SELF, "Use /leave to remove yourself"),
        )

    # Ziel-Membership finden
    target = db.query(HouseholdMember).filter_by(
        household_id=household_id, user_id=user_id
    ).first()

    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.NOT_HOUSEHOLD_MEMBER, "User is not a member of this household"),
        )

    # Admin kann keine Admins entfernen
    if target.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(ErrorCode.CANNOT_REMOVE_ADMIN, "Cannot remove admin members"),
        )

    db.delete(target)
    db.commit()

    emit_to_household_sync(
        household_id,
        "household_member_removed",
        {"household_id": str(household_id), "user_id": str(user_id)},
    )


# ---------------------------------------------------------------------------
# Finance Summary Schemas
# ---------------------------------------------------------------------------


class CategorySummary(BaseModel):
    category: str | None
    total_rappen: int


class PendingBillInfo(BaseModel):
    id: uuid.UUID
    name: str
    amount_rappen: int
    day_of_month: int
    category: str | None
    is_booked_this_month: bool


class FinanceSummaryResponse(BaseModel):
    month: date
    budget_rappen: int | None
    total_spent_rappen: int
    remaining_rappen: int | None
    days_elapsed: int
    days_in_month: int
    by_category: list[CategorySummary]
    pending_bills: list[PendingBillInfo]


# ---------------------------------------------------------------------------
# GET /finance-summary  — Monatliche Finanzübersicht
# ---------------------------------------------------------------------------
@router.get("/finance-summary", response_model=FinanceSummaryResponse)
def get_finance_summary(
    household_id: uuid.UUID,
    month: date | None = Query(None, description="YYYY-MM-DD, must be 1st of month. Default: current month"),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # 1. Monat ermitteln
    today = date.today()
    if month is None:
        month = date(today.year, today.month, 1)
    elif month.day != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.INVALID_MONTH, "month must be the first day of a month"),
        )

    # Nächsten Monat berechnen
    if month.month == 12:
        first_of_next_month = date(month.year + 1, 1, 1)
    else:
        first_of_next_month = date(month.year, month.month + 1, 1)

    # 2. Budget laden
    budget = (
        db.query(Budget)
        .filter(Budget.household_id == household_id, Budget.month == month)
        .first()
    )
    budget_rappen = budget.amount_rappen if budget else None

    # 3. Expenses des Monats aggregieren
    total_spent_row = (
        db.query(func.coalesce(func.sum(Expense.amount_rappen), 0))
        .filter(
            Expense.household_id == household_id,
            Expense.expense_date >= month,
            Expense.expense_date < first_of_next_month,
        )
        .scalar()
    )
    total_spent_rappen = int(total_spent_row)

    # 4. Nach Kategorie gruppiert
    category_rows = (
        db.query(Expense.category, func.sum(Expense.amount_rappen))
        .filter(
            Expense.household_id == household_id,
            Expense.expense_date >= month,
            Expense.expense_date < first_of_next_month,
        )
        .group_by(Expense.category)
        .all()
    )
    by_category = [
        CategorySummary(category=cat, total_rappen=int(total))
        for cat, total in category_rows
    ]

    # 5. Tage im Monat + vergangene Tage
    _, days_in_month = calendar.monthrange(month.year, month.month)

    # Tage vergangen: nur wenn aktueller Monat
    if month.year == today.year and month.month == today.month:
        days_elapsed = min(today.day, days_in_month)
    else:
        # Vergangener Monat: alle Tage vergangen. Zukünftiger Monat: 0
        if month < date(today.year, today.month, 1):
            days_elapsed = days_in_month
        else:
            days_elapsed = 0

    # 6. Remaining
    remaining_rappen = (budget_rappen - total_spent_rappen) if budget_rappen is not None else None

    # 7. Aktive RecurringBills laden
    active_bills = (
        db.query(RecurringBill)
        .filter(
            RecurringBill.household_id == household_id,
            RecurringBill.active == True,  # noqa: E712
        )
        .all()
    )

    # 8. Alle gebuchten bill_ids für diesen Monat in einem Query
    booked_bill_ids_query = (
        db.query(Expense.recurring_bill_id)
        .filter(
            Expense.household_id == household_id,
            Expense.recurring_bill_id.isnot(None),
            Expense.expense_date >= month,
            Expense.expense_date < first_of_next_month,
        )
        .all()
    )
    booked_bill_ids = {row[0] for row in booked_bill_ids_query}

    pending_bills: list[PendingBillInfo] = []
    for bill in active_bills:
        pending_bills.append(
            PendingBillInfo(
                id=bill.id,
                name=bill.name,
                amount_rappen=bill.amount_rappen,
                day_of_month=bill.day_of_month,
                category=bill.category,
                is_booked_this_month=bill.id in booked_bill_ids,
            )
        )

    return FinanceSummaryResponse(
        month=month,
        budget_rappen=budget_rappen,
        total_spent_rappen=total_spent_rappen,
        remaining_rappen=remaining_rappen,
        days_elapsed=days_elapsed,
        days_in_month=days_in_month,
        by_category=by_category,
        pending_bills=pending_bills,
    )


# ---------------------------------------------------------------------------
# Router 2: Household-übergreifende Endpoints (ohne household_id im Pfad)
# ---------------------------------------------------------------------------

general_router = APIRouter(
    prefix="/api/households",
    tags=["households"],
)


@general_router.post("/", response_model=HouseholdCreateResponse, status_code=status.HTTP_201_CREATED)
def create_household(
    body: HouseholdCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    invite_code = generate_unique_invite_code(db)
    household = Household(name=body.name.strip(), invite_code=invite_code)
    db.add(household)
    db.flush()

    membership = HouseholdMember(
        household_id=household.id,
        user_id=current_user.id,
        role="admin",
    )
    db.add(membership)

    # Werte vor Commit sichern
    result = HouseholdCreateResponse(
        id=household.id, name=household.name, role="admin", currency=household.currency
    )
    db.commit()
    return result


@general_router.post("/join", response_model=JoinResponse)
def join_household(
    data: JoinRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Code normalisieren (case-insensitiv)
    code = data.invite_code.strip().upper()

    # Household suchen
    from sqlalchemy import func
    household = (
        db.query(Household)
        .filter(func.upper(Household.invite_code) == code)
        .first()
    )
    if household is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(ErrorCode.INVITE_CODE_NOT_FOUND, "Invite code not found"),
        )

    # Prüfen ob User bereits Mitglied ist
    existing = (
        db.query(HouseholdMember)
        .filter_by(household_id=household.id, user_id=current_user.id)
        .first()
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.ALREADY_MEMBER, "Already a member of this household"),
        )

    # Membership anlegen
    membership = HouseholdMember(
        household_id=household.id,
        user_id=current_user.id,
        role="member",
    )
    db.add(membership)

    # Werte vor dem Commit sichern (SQLAlchemy expired Objekte nach commit)
    household_id = household.id
    household_name = household.name
    user_id = current_user.id
    display_name = current_user.display_name

    db.commit()

    emit_to_household_sync(
        household_id,
        "household_member_joined",
        {
            "household_id": str(household_id),
            "user_id": str(user_id),
            "display_name": display_name,
            "role": "member",
        },
    )

    return JoinResponse(id=household_id, name=household_name)
