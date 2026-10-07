"""Was heute für eine Person ansteht: Zahl am App-Icon (Badging API) und Liste
für das Homescreen-Widget.

Gezählt wird, was bis heute (Zeitzone des Haushalts) fällig und offen ist:

- Aufgaben (Todos), die der Person zugewiesen oder niemandem zugewiesen sind
- Ämtli (Putzplan), die der Person zugewiesen oder niemandem zugewiesen sind
- Tier- und Pflanzenpflege (gehört dem ganzen Haushalt)

Bewusst nicht gezählt: Einkaufsliste (kein Termin), Termine (keine Aufgabe),
Dokumente (Ablauf ist ein Hinweis, keine offene Arbeit).
"""

import uuid
import zoneinfo
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    Chore,
    ChoreAssignment,
    Household,
    Pet,
    PetCareTask,
    Plant,
    PlantCareTask,
    Todo,
)

# Ämtli, die länger offen sind, zählen nicht mehr (der Putzplan zeigt
# ohnehin nur die letzten 14 Tage).
CHORE_LOOKBACK = timedelta(days=14)

PLANT_CARE_LABELS = {
    "de": {"water": "Giessen", "fertilize": "Düngen", "repot": "Umtopfen", "mist": "Besprühen", "other": "Pflege"},
    "en": {"water": "Water", "fertilize": "Fertilize", "repot": "Repot", "mist": "Mist", "other": "Care"},
}


@dataclass
class DueItem:
    kind: str  # "todo" | "chore" | "pet" | "plant"
    title: str
    overdue: bool
    mine: bool  # der Person zugewiesen (False = niemandem / ganzer Haushalt)


def _tz(household: Household) -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(household.timezone or "Europe/Zurich")


def household_today(household: Household) -> date:
    return datetime.now(timezone.utc).astimezone(_tz(household)).date()


def _as_utc(dt: datetime) -> datetime:
    # SQLite liefert naive Datetimes zurück
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def due_items(db: Session, household: Household, user_id: uuid.UUID, locale: str = "de") -> list[DueItem]:
    """Alle heute anstehenden Dinge, Überfälliges zuerst."""
    tz = _tz(household)
    today = household_today(household)
    start_of_today = datetime.combine(today, time.min, tzinfo=tz).astimezone(timezone.utc)
    end_of_today = datetime.combine(today, time.max, tzinfo=tz).astimezone(timezone.utc)
    items: list[DueItem] = []

    todos = (
        db.query(Todo)
        .filter(
            Todo.household_id == household.id,
            Todo.is_done == False,  # noqa: E712
            Todo.due_date.isnot(None),
            Todo.due_date <= end_of_today,
            or_(Todo.assigned_to_user_id == user_id, Todo.assigned_to_user_id.is_(None)),
        )
        .order_by(Todo.due_date.asc())
        .all()
    )
    items += [
        DueItem("todo", t.title, _as_utc(t.due_date) < start_of_today, t.assigned_to_user_id == user_id)
        for t in todos
    ]

    chores = (
        db.query(ChoreAssignment, Chore.title)
        .join(Chore, ChoreAssignment.chore_id == Chore.id)
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
        .order_by(ChoreAssignment.due_date.asc())
        .all()
    )
    items += [
        DueItem("chore", title, a.due_date < today, a.assigned_user_id == user_id)
        for a, title in chores
    ]

    pet_care = (
        db.query(PetCareTask, Pet.name)
        .join(Pet, PetCareTask.pet_id == Pet.id)
        .filter(PetCareTask.household_id == household.id, PetCareTask.next_due_at <= today)
        .order_by(PetCareTask.next_due_at.asc())
        .all()
    )
    items += [DueItem("pet", f"{name}: {t.name}", t.next_due_at < today, False) for t, name in pet_care]

    labels = PLANT_CARE_LABELS.get(locale, PLANT_CARE_LABELS["de"])
    plant_care = (
        db.query(PlantCareTask, Plant.name)
        .join(Plant, PlantCareTask.plant_id == Plant.id)
        .filter(PlantCareTask.household_id == household.id, PlantCareTask.next_due_at <= today)
        .order_by(PlantCareTask.next_due_at.asc())
        .all()
    )
    items += [
        DueItem("plant", f"{name}: {t.label or labels.get(t.care_type, labels['other'])}", t.next_due_at < today, False)
        for t, name in plant_care
    ]

    # Stabil sortiert: Überfälliges zuerst, sonst Reihenfolge Aufgaben → Ämtli → Tiere → Pflanzen
    return sorted(items, key=lambda i: not i.overdue)


def attention_count(db: Session, household: Household, user_id: uuid.UUID) -> int:
    return len(due_items(db, household, user_id))
