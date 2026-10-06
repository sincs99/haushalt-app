"""Zahl am App-Icon (Badging API): was heute für eine Person ansteht.

Gezählt wird, was bis heute (Zeitzone des Haushalts) fällig und offen ist:

- Aufgaben (Todos), die der Person zugewiesen oder niemandem zugewiesen sind
- Ämtli (Putzplan), die der Person zugewiesen oder niemandem zugewiesen sind
- Tier- und Pflanzenpflege (gehört dem ganzen Haushalt)

Bewusst nicht gezählt: Einkaufsliste (kein Termin), Termine (keine Aufgabe),
Dokumente (Ablauf ist ein Hinweis, keine offene Arbeit).
"""

import uuid
import zoneinfo
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    ChoreAssignment,
    Household,
    PetCareTask,
    PlantCareTask,
    Todo,
)

# Ämtli, die länger offen sind, zählen nicht mehr (der Putzplan zeigt
# ohnehin nur die letzten 14 Tage).
CHORE_LOOKBACK = timedelta(days=14)


def household_today(household: Household) -> date:
    tz = zoneinfo.ZoneInfo(household.timezone or "Europe/Zurich")
    return datetime.now(timezone.utc).astimezone(tz).date()


def attention_count(db: Session, household: Household, user_id: uuid.UUID) -> int:
    today = household_today(household)
    tz = zoneinfo.ZoneInfo(household.timezone or "Europe/Zurich")
    end_of_today = datetime.combine(today, time.max, tzinfo=tz).astimezone(timezone.utc)

    todos = (
        db.query(Todo)
        .filter(
            Todo.household_id == household.id,
            Todo.is_done == False,  # noqa: E712
            Todo.due_date.isnot(None),
            Todo.due_date <= end_of_today,
            or_(Todo.assigned_to_user_id == user_id, Todo.assigned_to_user_id.is_(None)),
        )
        .count()
    )

    chores = (
        db.query(ChoreAssignment)
        .filter(
            ChoreAssignment.household_id == household.id,
            ChoreAssignment.completed_at.is_(None),
            ChoreAssignment.due_date <= today,
            ChoreAssignment.due_date >= today - CHORE_LOOKBACK,
            or_(
                ChoreAssignment.assigned_user_id == user_id,
                ChoreAssignment.assigned_user_id.is_(None),
            ),
        )
        .count()
    )

    pet_care = (
        db.query(PetCareTask)
        .filter(PetCareTask.household_id == household.id, PetCareTask.next_due_at <= today)
        .count()
    )

    plant_care = (
        db.query(PlantCareTask)
        .filter(PlantCareTask.household_id == household.id, PlantCareTask.next_due_at <= today)
        .count()
    )

    return todos + chores + pet_care + plant_care
