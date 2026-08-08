"""Combined tasks endpoint – Todos + ChoreAssignments in einer Liste."""

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.database import get_db
from app.models import Chore, ChoreAssignment, Household, HouseholdMember, Todo
from app.services.chore_scheduler import materialize_due_assignments

router = APIRouter(
    prefix="/api/households/{household_id}",
    tags=["tasks"],
)


class UnifiedTaskResponse(BaseModel):
    type: str           # "todo" | "chore"
    id: uuid.UUID
    title: str
    due_date: date | None        # immer date (kein datetime) für konsistentes Frontend-Format
    assigned_to_user_id: uuid.UUID | None
    tags: list[str]
    recurring: bool


@router.get("/tasks", response_model=list[UnifiedTaskResponse])
def list_unified_tasks(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # 1. Offene Todos
    todos = (
        db.query(Todo)
        .filter(Todo.household_id == household_id, Todo.is_done == False)  # noqa: E712
        .all()
    )

    # 2. ChoreAssignments materialisieren + offene laden
    household = db.get(Household, household_id)
    materialize_due_assignments(db, household)

    chore_assignments = (
        db.query(ChoreAssignment, Chore.title)
        .join(Chore, ChoreAssignment.chore_id == Chore.id)
        .filter(
            ChoreAssignment.household_id == household_id,
            ChoreAssignment.completed_at.is_(None),
        )
        .all()
    )

    # 3. Normalisieren
    result: list[UnifiedTaskResponse] = []

    for todo in todos:
        raw_due = todo.due_date
        result.append(UnifiedTaskResponse(
            type="todo",
            id=todo.id,
            title=todo.title,
            due_date=raw_due.date() if isinstance(raw_due, datetime) else raw_due,
            assigned_to_user_id=todo.assigned_to_user_id,
            tags=todo.tags or [],
            recurring=False,
        ))

    for assignment, chore_title in chore_assignments:
        result.append(UnifiedTaskResponse(
            type="chore",
            id=assignment.id,
            title=chore_title,
            due_date=assignment.due_date,
            assigned_to_user_id=assignment.assigned_user_id,
            tags=[],
            recurring=True,
        ))

    # Sortierung: due_date ASC, NULLS LAST
    # Alle due_date sind jetzt einheitlich date (oder None) → kein Typ-Mismatch
    def _sort_key(t: UnifiedTaskResponse) -> tuple[bool, date]:
        d = t.due_date
        if d is None:
            return (True, date.max)
        if isinstance(d, datetime):
            d = d.date()
        return (False, d)

    result.sort(key=_sort_key)

    return result
