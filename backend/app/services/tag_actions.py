"""Aktions-Registry für Tags (NFC-Chips / QR-Sticker).

Ein Tag zeigt auf ein Ziel (``target_type`` + ``target_id``) und löst eine
Aktion aus (``action``). Alles, was eine Aktion ausmacht, steht hier in einem
``TagAction``-Eintrag: welche Ziele es gibt (Dropdown beim Anlegen), wie das
Ziel geladen wird, was die Bestätigungsseite anzeigt und was beim Ausführen
passiert. Router (``app/routers/tags.py``) und Frontend kennen keine
einzelnen Aktionen.

Regeln für alle Aktionen:
- Ausgeführt wird nur im Namen des eingeloggten Mitglieds (``membership``);
  der Router hat Token, Haushalt und Mitgliedschaft bereits geprüft.
- Die Mutation läuft über die bestehenden Endpoint-Funktionen der Module
  (gleiche Validierung, gleiche Socket-Events) — keine eigene Logik hier.
- **Keine Lösch-Aktionen.** Ein Tag kann von jedem gelesen werden, der den
  Sticker in die Hand bekommt; er darf höchstens etwas abhaken oder loggen.

Neuen Zieltyp ergänzen (z. B. Pflanzen, ``plant.water``):

1. ``_plant_targets(db, household_id)`` schreiben: liefert ``TargetOption``\\s
   für das Dropdown (id + Anzeigename).
2. ``_load_plant(db, household_id, target_id)`` schreiben: Ziel laden oder
   ``None``, wenn es im Haushalt nicht (mehr) existiert.
3. ``_describe_plant_water(ctx)`` → ``TagDescription`` (Name, Details für die
   Bestätigungsseite, ``can_execute``/``reason``).
4. ``_execute_plant_water(ctx, params)`` → ``dict`` mit dem Ergebnis; ruft die
   Endpoint-Funktion aus ``app/routers/plants.py`` auf.
5. Eintrag in ``TAG_ACTIONS`` registrieren (unten). Für reine Navigation
   (``plant.open``) genügen ``navigate_to`` und ``execute=None``.
6. Frontend: i18n-Keys ``tags.targetTypes.<target_type>`` und
   ``tags.actions.<action>.{label,confirm,done}`` in ``de.json``/``en.json``;
   Detailzeilen der Bestätigungsseite optional in ``TagResolveView.vue``.

Keine Migration nötig: ``target_type``/``action`` sind Strings, ``target_id``
hat bewusst keinen Fremdschlüssel.
"""

from __future__ import annotations

import uuid
import zoneinfo
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode, error_detail
from app.models import (
    Chore,
    ChoreAssignment,
    FeedingLog,
    Household,
    HouseholdMember,
    Pet,
    PetCareTask,
    ShoppingList,
    Tag,
    Todo,
    User,
)

# ---------------------------------------------------------------------------
# Datentypen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetOption:
    """Eintrag im Ziel-Dropdown beim Anlegen eines Tags."""

    id: uuid.UUID
    name: str


@dataclass
class TagContext:
    """Alles, was describe/execute brauchen — vom Router befüllt."""

    db: Session
    tag: Tag
    membership: HouseholdMember
    household: Household
    target: Any  # geladenes Ziel (ORM-Objekt) oder None bei „alle“


@dataclass
class TagDescription:
    """Inhalt der Bestätigungsseite."""

    target_name: str | None
    # Englischer Fallback-Text; das Frontend baut den Text aus i18n-Keys
    description: str
    details: dict[str, Any] = field(default_factory=dict)
    # False → Bestätigungsseite zeigt den Grund statt des grossen Buttons
    can_execute: bool = True
    # Maschinenlesbarer Grund für can_execute=False (z. B. ALREADY_DONE)
    reason: str | None = None


@dataclass(frozen=True)
class TagAction:
    key: str
    target_type: str
    list_targets: Callable[[Session, uuid.UUID], list[TargetOption]]
    load_target: Callable[[Session, uuid.UUID, uuid.UUID], Any]
    describe: Callable[[TagContext], TagDescription]
    # None → reine Navigation (*.open), kein execute-Endpunkt
    execute: Callable[[TagContext, dict[str, Any]], dict[str, Any]] | None = None
    # Ziel darf leer sein (z. B. „alle Tiere füttern“, „Einkauf öffnen“)
    target_optional: bool = False
    # Frontend-Route für Navigations-Aktionen; erhält den Kontext
    navigate_to: Callable[[TagContext], str] | None = None

    @property
    def navigate_only(self) -> bool:
        return self.execute is None


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _get_scoped(db: Session, model, household_id: uuid.UUID, target_id: uuid.UUID):
    obj = db.get(model, target_id)
    if obj is None or obj.household_id != household_id:
        return None
    return obj


def _display_name(db: Session, user_id: uuid.UUID | None) -> str | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    return user.display_name if user else None


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _household_now(household: Household) -> datetime:
    return datetime.now(zoneinfo.ZoneInfo(household.timezone or "Europe/Zurich"))


# Ab dieser Stunde (Haushalts-Zeitzone) loggt ein Fütterungs-Tag die Abendfütterung
FEEDING_EVENING_FROM_HOUR = 14


def default_feeding_slot(household: Household) -> str:
    return "evening" if _household_now(household).hour >= FEEDING_EVENING_FROM_HOUR else "morning"


# ---------------------------------------------------------------------------
# pet.feed — Fütterung loggen (ein Tier oder alle Tiere)
# ---------------------------------------------------------------------------


def _pet_targets(db: Session, household_id: uuid.UUID) -> list[TargetOption]:
    pets = db.query(Pet).filter(Pet.household_id == household_id).order_by(Pet.name).all()
    return [TargetOption(p.id, p.name) for p in pets]


def _load_pet(db: Session, household_id: uuid.UUID, target_id: uuid.UUID):
    return _get_scoped(db, Pet, household_id, target_id)


def _feeding_slot(ctx: TagContext, params: dict[str, Any]) -> str:
    slot = params.get("slot")
    if slot is None:
        return default_feeding_slot(ctx.household)
    if slot not in ("morning", "evening"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.FEEDING_INVALID_SLOT, "slot must be 'morning' or 'evening'"),
        )
    return slot


def _describe_pet_feed(ctx: TagContext) -> TagDescription:
    from app.routers.pets import _get_household_today

    db, household_id = ctx.db, ctx.household.id
    today = _get_household_today(db, household_id)
    slot = default_feeding_slot(ctx.household)

    pet_query = db.query(Pet).filter(Pet.household_id == household_id)
    if ctx.target is not None:
        pet_query = pet_query.filter(Pet.id == ctx.target.id)
    pets = pet_query.order_by(Pet.name).all()

    feedings_today = {
        (f.pet_id, f.slot): f
        for f in db.query(FeedingLog)
        .filter(FeedingLog.household_id == household_id, FeedingLog.date == today)
        .all()
    }
    last_feeding_query = db.query(FeedingLog).filter(FeedingLog.household_id == household_id)
    if ctx.target is not None:
        last_feeding_query = last_feeding_query.filter(FeedingLog.pet_id == ctx.target.id)
    last = last_feeding_query.order_by(FeedingLog.fed_at.desc()).first()

    pet_rows = [
        {
            "id": str(p.id),
            "name": p.name,
            "morning_fed": (p.id, "morning") in feedings_today,
            "evening_fed": (p.id, "evening") in feedings_today,
        }
        for p in pets
    ]
    unfed = [row for row in pet_rows if not row[f"{slot}_fed"]]

    details = {
        "slot": slot,
        "pets": pet_rows,
        "last_fed_at": _iso(last.fed_at) if last else None,
        "last_fed_slot": last.slot if last else None,
        "last_fed_by": _display_name(db, last.fed_by_user_id) if last else None,
    }
    name = ctx.target.name if ctx.target is not None else None
    if not pets:
        return TagDescription(name, "No pets in this household", details, False, "NO_PETS")
    return TagDescription(
        target_name=name,
        description=f"Feed {name or 'all pets'} ({slot})",
        details=details,
        can_execute=bool(unfed),
        reason=None if unfed else "ALREADY_FED",
    )


def _execute_pet_feed(ctx: TagContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.routers.pets import (
        FeedAllCreate,
        FeedingCreate,
        FeedingLogResponse,
        create_feeding,
        feed_all,
    )

    slot = _feeding_slot(ctx, params)
    household_id = ctx.household.id
    if ctx.target is not None:
        feeding = create_feeding(
            household_id=household_id,
            pet_id=ctx.target.id,
            body=FeedingCreate(slot=slot),
            membership=ctx.membership,
            db=ctx.db,
        )
        created = [feeding]
    else:
        created = feed_all(
            household_id=household_id,
            body=FeedAllCreate(slot=slot),
            membership=ctx.membership,
            db=ctx.db,
        )
    return {
        "slot": slot,
        "changed": bool(created),
        "feedings": [FeedingLogResponse.model_validate(f).model_dump(mode="json") for f in created],
    }


# ---------------------------------------------------------------------------
# pet.care_task.done — Pflegeaufgabe eines Tiers erledigen
# ---------------------------------------------------------------------------


def _care_task_targets(db: Session, household_id: uuid.UUID) -> list[TargetOption]:
    rows = (
        db.query(PetCareTask, Pet.name)
        .join(Pet, PetCareTask.pet_id == Pet.id)
        .filter(PetCareTask.household_id == household_id)
        .order_by(Pet.name, PetCareTask.name)
        .all()
    )
    return [TargetOption(task.id, f"{pet_name} – {task.name}") for task, pet_name in rows]


def _load_care_task(db: Session, household_id: uuid.UUID, target_id: uuid.UUID):
    return _get_scoped(db, PetCareTask, household_id, target_id)


def _describe_care_task_done(ctx: TagContext) -> TagDescription:
    task: PetCareTask = ctx.target
    pet = ctx.db.get(Pet, task.pet_id)
    pet_name = pet.name if pet else None
    return TagDescription(
        target_name=task.name,
        description=f"Mark '{task.name}' as done" + (f" for {pet_name}" if pet_name else ""),
        details={
            "pet_id": str(task.pet_id),
            "pet_name": pet_name,
            "interval_days": task.interval_days,
            "next_due_at": _iso(task.next_due_at),
            "last_done_at": _iso(task.last_done_at),
        },
    )


def _execute_care_task_done(ctx: TagContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.routers.pets import CareTaskResponse, complete_care_task

    task = complete_care_task(
        household_id=ctx.household.id,
        pet_id=ctx.target.pet_id,
        task_id=ctx.target.id,
        membership=ctx.membership,
        db=ctx.db,
    )
    return {"changed": True, "care_task": CareTaskResponse.model_validate(task).model_dump(mode="json")}


# ---------------------------------------------------------------------------
# chore.assignment.done — aktuelle Putzplan-Zuweisung eines Ämtlis abhaken
# ---------------------------------------------------------------------------

# Wie weit im Voraus ein Ämtli per Tag erledigt werden darf
CHORE_EARLY_DAYS = 6


def _chore_targets(db: Session, household_id: uuid.UUID) -> list[TargetOption]:
    chores = (
        db.query(Chore)
        .filter(Chore.household_id == household_id, Chore.active.is_(True))
        .order_by(Chore.title)
        .all()
    )
    return [TargetOption(c.id, c.title) for c in chores]


def _load_chore(db: Session, household_id: uuid.UUID, target_id: uuid.UUID):
    return _get_scoped(db, Chore, household_id, target_id)


def current_chore_assignment(ctx: TagContext) -> ChoreAssignment | None:
    """Die Zuweisung, die ein Scan abhakt.

    Materialisiert zuerst fällige Zuweisungen (wie GET /chores/assignments,
    inkl. Socket-Events). „Aktuell“ ist die jüngste offene Zuweisung mit
    Fälligkeit bis heute (laufende Periode, auch wenn überfällig); gibt es
    keine, die nächste offene in den kommenden ``CHORE_EARLY_DAYS`` Tagen
    (vorzeitig erledigt). Ältere offene Zuweisungen bleiben unangetastet.
    """
    from app.routers.chores import list_assignments
    from app.services.chore_scheduler import today_in_tz

    household = ctx.household
    today = today_in_tz(household.timezone)
    # Fenster wie im Standard-Aufruf der Ansicht; materialisiert und emittiert
    list_assignments(
        household_id=household.id,
        from_date=today - timedelta(days=14),
        to_date=today + timedelta(days=CHORE_EARLY_DAYS),
        membership=ctx.membership,
        db=ctx.db,
    )
    base = ctx.db.query(ChoreAssignment).filter(
        ChoreAssignment.household_id == household.id,
        ChoreAssignment.chore_id == ctx.target.id,
        ChoreAssignment.completed_at.is_(None),
    )
    current = (
        base.filter(ChoreAssignment.due_date <= today)
        .order_by(ChoreAssignment.due_date.desc())
        .first()
    )
    if current is None:
        current = (
            base.filter(
                ChoreAssignment.due_date > today,
                ChoreAssignment.due_date <= today + timedelta(days=CHORE_EARLY_DAYS),
            )
            .order_by(ChoreAssignment.due_date.asc())
            .first()
        )
    return current


def _describe_chore_done(ctx: TagContext) -> TagDescription:
    chore: Chore = ctx.target
    assignment = current_chore_assignment(ctx)
    last_done = (
        ctx.db.query(ChoreAssignment)
        .filter(
            ChoreAssignment.chore_id == chore.id,
            ChoreAssignment.completed_at.is_not(None),
        )
        .order_by(ChoreAssignment.completed_at.desc())
        .first()
    )
    details: dict[str, Any] = {
        "assignment_id": str(assignment.id) if assignment else None,
        "due_date": _iso(assignment.due_date) if assignment else None,
        "assigned_user_id": str(assignment.assigned_user_id) if assignment and assignment.assigned_user_id else None,
        "assigned_user_name": _display_name(ctx.db, assignment.assigned_user_id) if assignment else None,
        "last_done_at": _iso(last_done.completed_at) if last_done else None,
        "last_done_by": _display_name(ctx.db, last_done.completed_by_user_id) if last_done else None,
    }
    if not chore.active:
        return TagDescription(chore.title, f"'{chore.title}' is paused", details, False, "CHORE_INACTIVE")
    if assignment is None:
        return TagDescription(chore.title, f"Nothing due for '{chore.title}'", details, False, "NOTHING_DUE")
    return TagDescription(chore.title, f"Mark '{chore.title}' as done", details)


def _execute_chore_done(ctx: TagContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.routers.chores import ChoreAssignmentResponse, complete_assignment

    if not ctx.target.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.TAG_NOTHING_TO_DO, "Chore is paused"),
        )
    assignment = current_chore_assignment(ctx)
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.TAG_NOTHING_TO_DO, "No open assignment for this chore"),
        )
    done = complete_assignment(
        household_id=ctx.household.id,
        assignment_id=assignment.id,
        membership=ctx.membership,
        db=ctx.db,
    )
    return {"changed": True, "assignment": ChoreAssignmentResponse.model_validate(done).model_dump(mode="json")}


# ---------------------------------------------------------------------------
# shopping_list.open — nur Navigation, keine Mutation
# ---------------------------------------------------------------------------


def _shopping_list_targets(db: Session, household_id: uuid.UUID) -> list[TargetOption]:
    lists = (
        db.query(ShoppingList)
        .filter(ShoppingList.household_id == household_id)
        .order_by(ShoppingList.position, ShoppingList.name)
        .all()
    )
    return [TargetOption(lst.id, lst.name) for lst in lists]


def _load_shopping_list(db: Session, household_id: uuid.UUID, target_id: uuid.UUID):
    return _get_scoped(db, ShoppingList, household_id, target_id)


def _describe_shopping_list_open(ctx: TagContext) -> TagDescription:
    name = ctx.target.name if ctx.target is not None else None
    return TagDescription(name, f"Open shopping list {name or ''}".strip())


def _navigate_shopping_list(ctx: TagContext) -> str:
    if ctx.target is not None:
        return f"/shopping?list={ctx.target.id}"
    return "/shopping"


# ---------------------------------------------------------------------------
# todo.done — Todo abhaken
# ---------------------------------------------------------------------------


def _todo_targets(db: Session, household_id: uuid.UUID) -> list[TargetOption]:
    todos = (
        db.query(Todo)
        .filter(Todo.household_id == household_id, Todo.is_done.is_(False))
        .order_by(Todo.title)
        .all()
    )
    return [TargetOption(t.id, t.title) for t in todos]


def _load_todo(db: Session, household_id: uuid.UUID, target_id: uuid.UUID):
    return _get_scoped(db, Todo, household_id, target_id)


def _describe_todo_done(ctx: TagContext) -> TagDescription:
    todo: Todo = ctx.target
    details = {
        "is_done": todo.is_done,
        "done_at": _iso(todo.done_at),
        "due_date": _iso(todo.due_date),
        "assigned_user_name": _display_name(ctx.db, todo.assigned_to_user_id),
    }
    if todo.is_done:
        return TagDescription(todo.title, f"'{todo.title}' is already done", details, False, "ALREADY_DONE")
    return TagDescription(todo.title, f"Mark '{todo.title}' as done", details)


def _execute_todo_done(ctx: TagContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.routers.todos import TodoUpdate, _todo_response, update_todo

    todo: Todo = ctx.target
    if todo.is_done:
        # Idempotent: zweiter Scan ändert nichts (done_at bleibt)
        return {"changed": False, "todo": _todo_response(todo)}
    updated = update_todo(
        household_id=ctx.household.id,
        todo_id=todo.id,
        body=TodoUpdate(is_done=True),
        membership=ctx.membership,
        db=ctx.db,
    )
    return {"changed": True, "todo": _todo_response(updated)}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TAG_ACTIONS: dict[str, TagAction] = {
    a.key: a
    for a in (
        TagAction(
            key="pet.feed",
            target_type="pet",
            list_targets=_pet_targets,
            load_target=_load_pet,
            describe=_describe_pet_feed,
            execute=_execute_pet_feed,
            target_optional=True,  # leer = alle Tiere (feed-all)
        ),
        TagAction(
            key="pet.care_task.done",
            target_type="pet_care_task",
            list_targets=_care_task_targets,
            load_target=_load_care_task,
            describe=_describe_care_task_done,
            execute=_execute_care_task_done,
        ),
        TagAction(
            key="chore.assignment.done",
            target_type="chore",
            list_targets=_chore_targets,
            load_target=_load_chore,
            describe=_describe_chore_done,
            execute=_execute_chore_done,
        ),
        TagAction(
            key="shopping_list.open",
            target_type="shopping_list",
            list_targets=_shopping_list_targets,
            load_target=_load_shopping_list,
            describe=_describe_shopping_list_open,
            target_optional=True,  # leer = Einkauf allgemein
            navigate_to=_navigate_shopping_list,
        ),
        TagAction(
            key="todo.done",
            target_type="todo",
            list_targets=_todo_targets,
            load_target=_load_todo,
            describe=_describe_todo_done,
            execute=_execute_todo_done,
        ),
    )
}


def get_action(key: str) -> TagAction | None:
    return TAG_ACTIONS.get(key)


def target_types() -> list[str]:
    """Alle Zieltypen in Registrierungsreihenfolge, ohne Duplikate."""
    return list(dict.fromkeys(a.target_type for a in TAG_ACTIONS.values()))
