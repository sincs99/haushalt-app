"""
Dashboard-Endpoint – Read-only Aggregation aller Household-Sektionen.

Liefert eine kompakte Übersicht mit Todos, Chores, Shopping, Finance und Events
für die Dashboard-View im Frontend.
"""

import uuid
import zoneinfo
from datetime import date, datetime, timezone
from datetime import time as dt_time

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.database import get_db
from app.models import (
    Chore,
    ChoreAssignment,
    Event,
    Household,
    HouseholdMember,
    Pet,
    PetCareTask,
    Plant,
    PlantCareTask,
    ShoppingItem,
    Todo,
    TodoReminder,
)
from app.services.attention import attention_count
from app.services.balance_service import compute_user_saldo
from app.services.chore_scheduler import today_in_tz
from app.services.event_times import to_household_time


def _as_utc(dt: datetime) -> datetime:
    """SQLite liefert naive Werte (gespeichert als UTC), PostgreSQL aware."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class DashboardTodoItem(BaseModel):
    id: uuid.UUID
    title: str
    due_date: datetime | None
    is_overdue: bool
    type: str  # "todo" oder "chore"


class DashboardTodoSection(BaseModel):
    open_count: int
    overdue_count: int
    items: list[DashboardTodoItem]  # max 3


class DashboardChoreItem(BaseModel):
    id: uuid.UUID
    title: str
    assigned_user_id: uuid.UUID | None


class DashboardChoreSection(BaseModel):
    items: list[DashboardChoreItem]  # max 3, fällig heute


class DashboardShoppingSection(BaseModel):
    open_count: int
    top_items: list[str]  # max 3 Namen


class DashboardFinanceSection(BaseModel):
    saldo_rappen: int
    currency: str


class DashboardEventItem(BaseModel):
    id: uuid.UUID
    title: str
    starts_at: datetime
    all_day: bool
    calendar_id: uuid.UUID


class DashboardEventSection(BaseModel):
    items: list[DashboardEventItem]  # max 5 Events von heute


class DashboardPetCareItem(BaseModel):
    id: uuid.UUID
    name: str            # Task-Name (z.B. "Wurmkur")
    pet_name: str        # Name des Tieres (von Pet.name)
    pet_id: uuid.UUID
    next_due_at: date    # Fälligkeitsdatum
    is_overdue: bool


class DashboardPlantItem(BaseModel):
    id: uuid.UUID        # Task-ID
    plant_id: uuid.UUID
    plant_name: str
    next_due_at: date    # Fälligkeit der Gießaufgabe
    is_overdue: bool


class DashboardPlantSection(BaseModel):
    due_count: int       # Anzahl Pflanzen, die heute oder überfällig gegossen werden müssen
    items: list[DashboardPlantItem]  # max 5, Überfällige zuerst


class DashboardReminderItem(BaseModel):
    id: uuid.UUID
    todo_id: uuid.UUID
    todo_title: str
    remind_at: datetime


class DashboardResponse(BaseModel):
    todos: DashboardTodoSection
    chores: DashboardChoreSection
    shopping: DashboardShoppingSection
    finance: DashboardFinanceSection
    events: DashboardEventSection
    pet_care_due: list[DashboardPetCareItem] = []
    plants_water: DashboardPlantSection = DashboardPlantSection(due_count=0, items=[])
    upcoming_reminders: list[DashboardReminderItem] = []


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/dashboard",
    tags=["dashboard"],
)


# ---------------------------------------------------------------------------
# GET / — Dashboard-Aggregation
# ---------------------------------------------------------------------------
@router.get("", response_model=DashboardResponse)
def get_dashboard(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    household = db.get(Household, household_id)
    tz = zoneinfo.ZoneInfo(household.timezone or "Europe/Zurich")
    today = today_in_tz(household.timezone)
    # Tagesgrenzen in Haushaltszeit, explizit nach UTC (Termine und Fälligkeiten sind
    # in UTC gespeichert; SQLite würde den Offset beim Vergleich sonst verwerfen)
    today_start = datetime.combine(today, dt_time.min, tzinfo=tz).astimezone(timezone.utc)
    today_end = datetime.combine(today, dt_time.max, tzinfo=tz).astimezone(timezone.utc)

    # ------------------------------------------------------------------
    # 1. Todos
    # ------------------------------------------------------------------
    open_todos_query = db.query(Todo).filter(
        Todo.household_id == household_id,
        Todo.is_done == False,  # noqa: E712
    )

    open_count = open_todos_query.count()

    # Überfällig ist ein Todo erst, wenn sein Fälligkeitstag vorbei ist. Die UI
    # speichert die Fälligkeit als Datum (00:00 UTC); ein Vergleich mit now() würde
    # ein heute fälliges Todo ab 00:00 UTC als überfällig zählen — anders als die
    # Aufgabenliste, die mit der lokalen Mitternacht vergleicht.
    overdue_count = (
        open_todos_query.filter(
            Todo.due_date.isnot(None),
            Todo.due_date < today_start,
        ).count()
    )

    # Top 3: Überfällige zuerst, dann due_date ASC NULLS LAST, dann created_at ASC
    is_overdue_expr = case(
        (
            (Todo.due_date.isnot(None)) & (Todo.due_date < today_start),
            1,
        ),
        else_=0,
    )
    top_todos = (
        open_todos_query.order_by(
            is_overdue_expr.desc(),
            case((Todo.due_date.is_(None), 1), else_=0),  # NULLS LAST
            Todo.due_date.asc(),
            Todo.created_at.asc(),
        )
        .limit(3)
        .all()
    )

    todo_items = [
        DashboardTodoItem(
            id=t.id,
            title=t.title,
            due_date=t.due_date,
            is_overdue=t.due_date is not None and _as_utc(t.due_date) < today_start,
            type="todo",
        )
        for t in top_todos
    ]

    # ------------------------------------------------------------------
    # 2. Chores (fällig heute)
    # ------------------------------------------------------------------
    chore_assignments = (
        db.query(ChoreAssignment, Chore.title)
        .join(Chore, ChoreAssignment.chore_id == Chore.id)
        .filter(
            ChoreAssignment.household_id == household_id,
            ChoreAssignment.due_date == today,
            ChoreAssignment.completed_at.is_(None),
        )
        .limit(3)
        .all()
    )

    chore_items = [
        DashboardChoreItem(
            id=assignment.id,
            title=title,
            assigned_user_id=assignment.assigned_user_id,
        )
        for assignment, title in chore_assignments
    ]

    # ------------------------------------------------------------------
    # 3. Shopping
    # ------------------------------------------------------------------
    open_shopping_query = db.query(ShoppingItem).filter(
        ShoppingItem.household_id == household_id,
        ShoppingItem.is_checked == False,  # noqa: E712
    )

    shopping_open_count = open_shopping_query.count()

    top_shopping = (
        open_shopping_query.order_by(ShoppingItem.created_at.asc())
        .limit(3)
        .all()
    )
    top_item_names = [item.name for item in top_shopping]

    # ------------------------------------------------------------------
    # 4. Finance
    # ------------------------------------------------------------------
    saldo = compute_user_saldo(db, household_id, membership.user_id)

    # ------------------------------------------------------------------
    # 5. Events (heute)
    # ------------------------------------------------------------------
    today_events = (
        db.query(Event)
        .filter(
            Event.household_id == household_id,
            Event.starts_at >= today_start,
            Event.starts_at <= today_end,
        )
        .order_by(Event.starts_at.asc())
        .limit(5)
        .all()
    )

    event_section = DashboardEventSection(
        items=[
            DashboardEventItem(
                id=ev.id,
                title=ev.title,
                starts_at=to_household_time(ev.starts_at, tz),
                all_day=ev.all_day,
                calendar_id=ev.calendar_id,
            )
            for ev in today_events
        ]
    )

    # ------------------------------------------------------------------
    # 6. Pet Care (nächste 5 Termine)
    # ------------------------------------------------------------------
    care_tasks = (
        db.query(PetCareTask, Pet.name.label("pet_name"))
        .join(Pet, PetCareTask.pet_id == Pet.id)
        .filter(PetCareTask.household_id == household_id)
        .order_by(
            case((PetCareTask.next_due_at < today, 0), else_=1),  # Überfällige zuerst
            PetCareTask.next_due_at.asc(),
        )
        .limit(5)
        .all()
    )

    pet_care_items = [
        DashboardPetCareItem(
            id=task.id,
            name=task.name,
            pet_name=pet_name,
            pet_id=task.pet_id,
            next_due_at=task.next_due_at,
            is_overdue=task.next_due_at < today,
        )
        for task, pet_name in care_tasks
    ]

    # ------------------------------------------------------------------
    # 7. Pflanzen, die gegossen werden müssen (heute fällig oder überfällig)
    # ------------------------------------------------------------------
    water_due_filter = (
        PlantCareTask.household_id == household_id,
        PlantCareTask.care_type == "water",
        PlantCareTask.next_due_at <= today,
    )
    plants_due_count = (
        db.query(func.count(func.distinct(PlantCareTask.plant_id)))
        .filter(*water_due_filter)
        .scalar()
        or 0
    )
    water_tasks = (
        db.query(PlantCareTask, Plant.name.label("plant_name"))
        .join(Plant, PlantCareTask.plant_id == Plant.id)
        .filter(*water_due_filter)
        .order_by(PlantCareTask.next_due_at.asc(), Plant.name.asc())
        .limit(5)
        .all()
    )
    plant_items = [
        DashboardPlantItem(
            id=task.id,
            plant_id=task.plant_id,
            plant_name=plant_name,
            next_due_at=task.next_due_at,
            is_overdue=task.next_due_at < today,
        )
        for task, plant_name in water_tasks
    ]

    # ------------------------------------------------------------------
    # 8. Upcoming Reminders (nächste 5 Erinnerungen)
    # ------------------------------------------------------------------
    upcoming_reminders_query = (
        db.query(TodoReminder, Todo.title.label("todo_title"))
        .join(Todo, TodoReminder.todo_id == Todo.id)
        .filter(
            TodoReminder.household_id == household_id,
            TodoReminder.remind_at > now,
            TodoReminder.notified_at.is_(None),
            Todo.is_done == False,  # F-03 Fix: Keine Reminders für erledigte Todos  # noqa: E712
        )
        .order_by(TodoReminder.remind_at.asc())
        .limit(5)
        .all()
    )

    reminder_items = [
        DashboardReminderItem(
            id=reminder.id,
            todo_id=reminder.todo_id,
            todo_title=todo_title,
            remind_at=reminder.remind_at,
        )
        for reminder, todo_title in upcoming_reminders_query
    ]

    return DashboardResponse(
        todos=DashboardTodoSection(
            open_count=open_count,
            overdue_count=overdue_count,
            items=todo_items,
        ),
        chores=DashboardChoreSection(items=chore_items),
        shopping=DashboardShoppingSection(
            open_count=shopping_open_count,
            top_items=top_item_names,
        ),
        finance=DashboardFinanceSection(
            saldo_rappen=saldo,
            currency=household.currency,
        ),
        events=event_section,
        pet_care_due=pet_care_items,
        plants_water=DashboardPlantSection(due_count=plants_due_count, items=plant_items),
        upcoming_reminders=reminder_items,
    )


# ---------------------------------------------------------------------------
# GET /badge — Zahl am App-Icon (Badging API)
# ---------------------------------------------------------------------------


class BadgeResponse(BaseModel):
    count: int


@router.get("/badge", response_model=BadgeResponse)
def get_badge(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Was heute für die aufrufende Person ansteht (siehe services/attention.py)."""
    household = db.get(Household, household_id)
    return BadgeResponse(count=attention_count(db, household, membership.user_id))
