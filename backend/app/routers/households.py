import calendar
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.deps import get_current_user, verify_household_access, verify_household_admin
from app.core.error_codes import ErrorCode, error_detail
from app.core.rate_limit import limiter
from app.database import get_db
from app.models import Budget, Calendar, Expense, Household, HouseholdMember, RecurringBill, User
from app.services.finance_rules import add_months, validate_month
from app.services.household_time import household_today
from app.services.invite_code import (
    generate_unique_invite_code,
    is_invite_code_expired,
    new_invite_code_expiry,
    rotate_household_invite_code,
)
from app.services.locking import lock_household
from app.services.membership import (
    ensure_admin,
    join_by_invite_code,
    locked_membership,
    member_count,
    release_departing_member,
)
from app.services.storage import LocalStorageService
from app.socket_manager import emit_to_household_sync

_storage = LocalStorageService()

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
    expires_at: datetime | None = None
    expired: bool = False


def _invite_code_response(household: Household) -> InviteCodeResponse:
    return InviteCodeResponse(
        invite_code=household.invite_code,
        expires_at=household.invite_code_expires_at,
        expired=is_invite_code_expired(household),
    )


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
    return _invite_code_response(household)


@router.post("/invite-code/rotate", response_model=InviteCodeResponse)
def rotate_invite_code(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_admin),
    db: Session = Depends(get_db),
):
    """Neuen Einladungscode erzeugen (nur Admin). Der alte Code wird ungültig."""
    household = db.get(Household, household_id)
    if household is None:
        raise HTTPException(status_code=404, detail=error_detail(ErrorCode.HOUSEHOLD_NOT_FOUND, "Household not found"))
    rotate_household_invite_code(db, household)
    db.commit()
    return _invite_code_response(household)


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


def _not_member() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=error_detail(ErrorCode.NOT_HOUSEHOLD_MEMBER, "Not a member of this household"),
    )


def _delete_household_files(household_id: uuid.UUID) -> None:
    """Hochgeladene Dateien (Dokumente, Fotos) eines gelöschten Haushalts entfernen.

    Die DB-Einträge verschwinden per CASCADE, die Dateien auf der Platte sonst nie.
    Best-effort: schlägt es fehl, räumt der periodische Cleanup
    (services/file_cleanup.py) verwaiste Haushaltsordner später auf.
    """
    try:
        _storage.delete_household(str(household_id))
    except Exception:
        pass


@router.post("/leave", status_code=status.HTTP_204_NO_CONTENT)
def leave_household(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Haushalt verlassen. Immer erlaubt — auch mit offenen Salden.

    Geschäftsregeln (docs/PROJECT-STATUS.md, "Haushalt verlassen"):
    - Haushaltszeile wird gesperrt (CASA-10): parallele Austritte/Beitritte laufen nacheinander
    - Letztes Mitglied → Haushalt wird komplett gelöscht (CASCADE) inkl. Dateien
    - Bleiben Mitglieder ohne Admin → dienstältestes Mitglied wird Admin (PD-H3)
    - Offene Zuständigkeiten werden freigegeben (PD-H1, release_departing_member)
    - Expenses/Shares werden NICHT gelöscht (Ehemaliges-Mitglied-Muster)
    """
    user_id = membership.user_id

    household = lock_household(db, household_id)
    if household is None:
        # Parallel gelöscht (letztes anderes Mitglied ist gerade gegangen)
        raise _not_member()
    # Unter der Sperre neu lesen: parallel entfernt oder befördert?
    own = locked_membership(db, household_id, user_id)
    if own is None:
        raise _not_member()

    db.delete(own)
    db.flush()

    # Nach dem Löschen neu zählen (nicht vorher), dann Invarianten herstellen
    if member_count(db, household_id) == 0:
        db.delete(household)  # CASCADE löscht members, expenses, etc.
        db.commit()
        _delete_household_files(household_id)
        return  # Kein Event nötig bei Löschung

    # Offene Zuständigkeiten freigeben (PD-H1) — im selben Commit wie der Austritt
    released = release_departing_member(db, household_id, user_id)
    ensure_admin(db, household_id)
    db.commit()

    # Socket-Event NACH Commit; danach verlassen alle Verbindungen des Users
    # serverseitig den Room (REST ist bereits durch verify_household_access dicht).
    # ``released`` nennt die Bereiche, die andere Clients neu laden müssen.
    emit_to_household_sync(
        household_id,
        "household_member_left",
        {"household_id": str(household_id), "user_id": str(user_id), "released": released.areas()},
        evict_user_id=user_id,
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

    Offene Zuständigkeiten werden wie beim Verlassen freigegeben (PD-H1).
    Der Einladungscode wird dabei erneuert, sonst könnte das entfernte Mitglied
    mit dem bekannten Code sofort wieder beitreten. Seine Socket-Verbindungen
    verlassen serverseitig den Room des Haushalts.
    """
    # Sich selbst entfernen → 422 (Verlassen-Endpoint nutzen)
    if user_id == membership.user_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.CANNOT_REMOVE_SELF, "Use /leave to remove yourself"),
        )

    household = lock_household(db, household_id)
    if household is None:
        raise _not_member()
    # Unter der Sperre prüfen, ob der Aufrufer noch (Admin-)Mitglied ist
    caller = locked_membership(db, household_id, membership.user_id)
    if caller is None:
        raise _not_member()
    if caller.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=error_detail(ErrorCode.ADMIN_REQUIRED, "Admin role required"),
        )

    # Ziel-Membership finden
    target = locked_membership(db, household_id, user_id)
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
    db.flush()
    # Offene Zuständigkeiten freigeben (PD-H1) — im selben Commit wie die Entfernung
    released = release_departing_member(db, household_id, user_id)
    rotate_household_invite_code(db, household)
    # Reparatur: Haushalt ohne Admin (Altbestand) bekommt hier wieder einen
    ensure_admin(db, household_id)
    db.commit()

    emit_to_household_sync(
        household_id,
        "household_member_removed",
        {"household_id": str(household_id), "user_id": str(user_id), "released": released.areas()},
        evict_user_id=user_id,
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
    paid_by_user_id: uuid.UUID | None = None


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
    today = household_today(db, household_id)
    if month is None:
        month = date(today.year, today.month, 1)
    else:
        # Erster des Monats, höchstens ±10 Jahre (9999-12-01 → sonst 500, CASA-36)
        validate_month(month, today)

    # Nächsten Monat berechnen
    first_of_next_month = add_months(month, 1)

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
            Expense.deleted_at.is_(None),
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
            Expense.deleted_at.is_(None),
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
            Expense.booked_month == month,
            Expense.deleted_at.is_(None),
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
                paid_by_user_id=bill.paid_by_user_id,
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
    household = Household(
        name=body.name.strip(),
        invite_code=invite_code,
        invite_code_expires_at=new_invite_code_expiry(),
    )
    db.add(household)
    db.flush()

    membership = HouseholdMember(
        household_id=household.id,
        user_id=current_user.id,
        role="admin",
    )
    db.add(membership)

    # Default-Kalender "Allgemein" anlegen, damit Events sofort möglich sind
    default_calendar = Calendar(
        household_id=household.id,
        name="Allgemein",
        color="#5B8DEF",
        position=0,
    )
    db.add(default_calendar)

    # Werte vor Commit sichern
    result = HouseholdCreateResponse(
        id=household.id, name=household.name, role="admin", currency=household.currency
    )
    db.commit()
    return result


@general_router.post("/join", response_model=JoinResponse)
@limiter.limit("5/minute;20/hour")
def join_household(
    request: Request,
    data: JoinRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    household, membership = join_by_invite_code(db, data.invite_code, current_user.id)
    role = membership.role

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
            "role": role,
        },
    )

    return JoinResponse(id=household_id, name=household_name)
