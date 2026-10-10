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
- **Idempotent pro Haushaltstag** (PD-T1): Ist das Ziel heute schon erledigt,
  liefert execute ``changed=False`` mit ``reason="ALREADY_DONE"`` statt etwas
  anderes (z. B. einen älteren Rückstand) abzuhaken. Parallele Scans werden über
  Zeilensperren serialisiert (``services/locking.py``).
- **Bestätigung angeheftet** (CASA-18): Aktionen mit ``requires_confirm`` liefern
  bei resolve ein ``confirm``-Objekt (z. B. die angezeigte Zuweisung), das execute
  mitschicken muss. Hat sich das Ziel seither geändert → 409
  ``TAG_CONFIRMATION_STALE``; fehlt es → 422 ``TAG_CONFIRMATION_REQUIRED``.

Neuen Zieltyp ergänzen (Beispiel: Pflanzen, ``plant.water``):

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
   Detailzeilen der Bestätigungsseite optional in ``TagScanView.vue``
   (``utils/tagScan.ts``). Anzeigenamen nicht hier übersetzen, sondern einen
   stabilen Schlüssel mitliefern (wie ``care_type``, CASA-59).

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
    Plant,
    PlantCareTask,
    ShoppingList,
    Tag,
    Todo,
    User,
)
from app.services.locking import lock_row

# ---------------------------------------------------------------------------
# Datentypen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetOption:
    """Eintrag im Ziel-Dropdown beim Anlegen eines Tags."""

    id: uuid.UUID
    name: str
    # Pflegeart ohne eigene Bezeichnung (CASA-59): Frontend übersetzt, ``name`` ist Fallback
    care_type: str | None = None
    plant_name: str | None = None


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
    # Was execute zurückschicken muss (requires_confirm), z. B. {"assignment_id": …}
    confirm: dict[str, Any] | None = None
    # Stabiler Schlüssel statt deutschem Namen (CASA-59), siehe ``target_care_type``
    target_care_type: str | None = None


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
    # execute verlangt das ``confirm``-Objekt aus resolve (CASA-18)
    requires_confirm: bool = False

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


def _already_done(**result: Any) -> dict[str, Any]:
    """Ergebnis eines wiederholten Scans: nichts geändert (PD-T1)."""
    return {"changed": False, "reason": "ALREADY_DONE", **result}


def _confirm_ids(params: dict[str, Any], key: str) -> list[uuid.UUID]:
    """IDs aus dem ``confirm``-Objekt von resolve; fehlt es → 422."""
    confirm = params.get("confirm") or {}
    raw = confirm.get(key) if isinstance(confirm, dict) else None
    values = raw if isinstance(raw, list) else [raw]
    try:
        if raw is None:
            raise ValueError
        return [uuid.UUID(str(v)) for v in values]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.TAG_CONFIRMATION_REQUIRED,
                f"confirm.{key} from resolve is required",
            ),
        )


def _stale() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=error_detail(
            ErrorCode.TAG_CONFIRMATION_STALE,
            "The target changed since the tag was scanned; scan again",
        ),
    )


# Ab dieser Stunde (Haushalts-Zeitzone) loggt ein Fütterungs-Tag die Abendfütterung
FEEDING_EVENING_FROM_HOUR = 14


def default_feeding_slot(household: Household) -> str:
    return "evening" if _household_now(household).hour >= FEEDING_EVENING_FROM_HOUR else "morning"


# ---------------------------------------------------------------------------
# pet.feed — Fütterung loggen (ein Tier oder alle Tiere)
# ---------------------------------------------------------------------------


def _pet_targets(db: Session, household_id: uuid.UUID) -> list[TargetOption]:
    # Archivierte Tiere sind keine Tag-Ziele mehr (PD-P2)
    pets = (
        db.query(Pet)
        .filter(Pet.household_id == household_id, Pet.archived.is_(False))
        .order_by(Pet.name)
        .all()
    )
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

    pet_query = db.query(Pet).filter(Pet.household_id == household_id, Pet.archived.is_(False))
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
    # Jede noch offene Mahlzeit ist erlaubt (PD-T2): Vorschlag nach Tageszeit,
    # sonst die andere, falls dort noch ein Tier ungefüttert ist
    unfed_slots = [s for s in ("morning", "evening") if any(not r[f"{s}_fed"] for r in pet_rows)]
    if slot not in unfed_slots and unfed_slots:
        slot = unfed_slots[0]
    unfed = [row for row in pet_rows if not row[f"{slot}_fed"]]

    details = {
        "slot": slot,
        "unfed_slots": unfed_slots,
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
        .filter(PetCareTask.household_id == household_id, Pet.archived.is_(False))
        .order_by(Pet.name, PetCareTask.name)
        .all()
    )
    return [TargetOption(task.id, f"{pet_name} – {task.name}") for task, pet_name in rows]


def _load_care_task(db: Session, household_id: uuid.UUID, target_id: uuid.UUID):
    return _get_scoped(db, PetCareTask, household_id, target_id)


def _pet_today(ctx: TagContext) -> date:
    from app.routers.pets import _get_household_today

    return _get_household_today(ctx.db, ctx.household.id)


def _describe_care_task_done(ctx: TagContext) -> TagDescription:
    task: PetCareTask = ctx.target
    pet = ctx.db.get(Pet, task.pet_id)
    pet_name = pet.name if pet else None
    details = {
        "pet_id": str(task.pet_id),
        "pet_name": pet_name,
        "interval_days": task.interval_days,
        "next_due_at": _iso(task.next_due_at),
        "last_done_at": _iso(task.last_done_at),
    }
    if task.last_done_at == _pet_today(ctx):
        return TagDescription(task.name, f"'{task.name}' was already done today", details, False, "ALREADY_DONE")
    return TagDescription(
        target_name=task.name,
        description=f"Mark '{task.name}' as done" + (f" for {pet_name}" if pet_name else ""),
        details=details,
    )


def _execute_care_task_done(ctx: TagContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.routers.pets import CareTaskResponse, complete_care_task

    # Sperre: parallele Scans laufen nacheinander, der zweite sieht „heute erledigt“
    locked = lock_row(ctx.db, PetCareTask, ctx.target.id)
    if locked is not None and locked.last_done_at == _pet_today(ctx):
        return _already_done(care_task=CareTaskResponse.model_validate(locked).model_dump(mode="json"))
    task = complete_care_task(
        household_id=ctx.household.id,
        pet_id=ctx.target.pet_id,
        task_id=ctx.target.id,
        membership=ctx.membership,
        db=ctx.db,
    )
    return {"changed": True, "care_task": CareTaskResponse.model_validate(task).model_dump(mode="json")}


# ---------------------------------------------------------------------------
# plant.water — Gießen loggen (eine Pflanze oder alle fälligen)
# ---------------------------------------------------------------------------

# Deutsche Fallback-Namen der Pflegearten (ältere Clients). Aktuelle Clients übersetzen
# über ``care_type`` / ``target_care_type`` (plants.careTypes.<key>, CASA-59).
PLANT_CARE_TYPE_NAMES = {
    "water": "Gießen",
    "fertilize": "Düngen",
    "repot": "Umtopfen",
    "mist": "Besprühen",
    "other": "Sonstiges",
}


def _plant_task_name(task: PlantCareTask) -> str:
    return (task.label or "").strip() or PLANT_CARE_TYPE_NAMES.get(task.care_type, task.care_type)


def target_care_type(target: Any) -> str | None:
    """Pflegeart, wenn der Anzeigename nur der Standardname ist (sonst None: eigene Bezeichnung)."""
    if isinstance(target, PlantCareTask) and not (target.label or "").strip():
        return target.care_type
    return None


def target_display_name(target: Any) -> str | None:
    """Anzeigename eines geladenen Ziels (Tag-Liste, execute)."""
    if isinstance(target, PlantCareTask):
        return _plant_task_name(target)
    return getattr(target, "name", None) or getattr(target, "title", None)


def _plant_targets(db: Session, household_id: uuid.UUID) -> list[TargetOption]:
    plants = db.query(Plant).filter(Plant.household_id == household_id).order_by(Plant.name).all()
    return [TargetOption(p.id, p.name) for p in plants]


def _load_plant(db: Session, household_id: uuid.UUID, target_id: uuid.UUID):
    return _get_scoped(db, Plant, household_id, target_id)


def _plant_care_status(ctx: TagContext) -> list:
    """Pflegestatus aller Pflanzen — dieselben Daten wie ``GET …/plants/care-status``."""
    from app.routers.plants import care_status

    return care_status(household_id=ctx.household.id, membership=ctx.membership, db=ctx.db)


def _status_row(item) -> dict[str, Any]:
    water = [t for t in item.tasks if t.care_type == "water"]
    last_done = [t.last_done_at for t in water if t.last_done_at is not None]
    return {
        "id": str(item.plant_id),
        "name": item.plant_name,
        "has_water_task": bool(water),
        "last_watered_at": _iso(max(last_done)) if last_done else None,
        "next_due_at": _iso(min(t.next_due_at for t in water)) if water else None,
        "due": any(t.due_today or t.overdue for t in water),
    }


def _plant_today(ctx: TagContext) -> date:
    from app.routers.plants import _get_household_today

    return _get_household_today(ctx.db, ctx.household.id)


def _water_tasks_to_do(ctx: TagContext) -> tuple[list[PlantCareTask], bool]:
    """Gießaufgaben, die ein Scan erledigen würde (PD-T1), und ob heute schon gegossen wurde.

    Mit Ziel: die fälligen/überfälligen Gießaufgaben der Pflanze; ist keine fällig,
    die früheste — ausser es wurde heute schon gegossen. Ohne Ziel: alle fälligen
    Gießaufgaben des Haushalts.
    """
    today = _plant_today(ctx)
    query = ctx.db.query(PlantCareTask).filter(
        PlantCareTask.household_id == ctx.household.id,
        PlantCareTask.care_type == "water",
    )
    if ctx.target is not None:
        query = query.filter(PlantCareTask.plant_id == ctx.target.id)
    tasks = query.order_by(PlantCareTask.next_due_at.asc(), PlantCareTask.id.asc()).all()
    done_today = any(t.last_done_at == today for t in tasks)
    due = [t for t in tasks if t.next_due_at <= today and t.last_done_at != today]
    if due or ctx.target is None:
        return due, done_today
    if tasks and not done_today:
        return [tasks[0]], done_today
    return [], done_today


def _describe_plant_water(ctx: TagContext) -> TagDescription:
    rows = [_status_row(item) for item in _plant_care_status(ctx)]
    to_do, _ = _water_tasks_to_do(ctx)
    confirm = {"task_ids": [str(t.id) for t in to_do]}
    if ctx.target is not None:
        row = next((r for r in rows if r["id"] == str(ctx.target.id)), None)
        details = {
            "plant_id": str(ctx.target.id),
            "plants": [row] if row else [],
            "last_watered_at": row["last_watered_at"] if row else None,
            "next_due_at": row["next_due_at"] if row else None,
        }
        name = ctx.target.name
        if row is None or not row["has_water_task"]:
            return TagDescription(name, f"'{name}' has no watering task", details, False, "NO_WATER_TASK")
        if not to_do:
            return TagDescription(name, f"'{name}' was already watered today", details, False, "ALREADY_DONE")
        return TagDescription(name, f"Water {name}", details, confirm=confirm)

    due = [r for r in rows if r["due"]]
    details = {"plants": rows, "due_count": len(due)}
    if not rows:
        return TagDescription(None, "No plants in this household", details, False, "NO_PLANTS")
    if not to_do:
        return TagDescription(None, "No plant needs water today", details, False, "NOTHING_DUE")
    return TagDescription(None, "Water all plants that are due", details, confirm=confirm)


def _execute_plant_water(ctx: TagContext, params: dict[str, Any]) -> dict[str, Any]:
    """Gießt genau die bei resolve angezeigten Aufgaben (CASA-18), jede höchstens einmal pro Tag."""
    from app.routers.plants import CareLogResponse, complete_care_task

    household_id = ctx.household.id
    if ctx.target is not None:
        has_water_task = (
            ctx.db.query(PlantCareTask.id)
            .filter(
                PlantCareTask.household_id == household_id,
                PlantCareTask.plant_id == ctx.target.id,
                PlantCareTask.care_type == "water",
            )
            .first()
        )
        if has_water_task is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(ErrorCode.TAG_NOTHING_TO_DO, "Plant has no watering task"),
            )

    today = _plant_today(ctx)
    logs = []
    # Feste Reihenfolge der Sperren → keine Deadlocks zwischen parallelen Scans
    for task_id in sorted(set(_confirm_ids(params, "task_ids")), key=str):
        task = lock_row(ctx.db, PlantCareTask, task_id)
        if (
            task is None
            or task.household_id != household_id
            or task.care_type != "water"
            or (ctx.target is not None and task.plant_id != ctx.target.id)
        ):
            continue
        if task.last_done_at == today:
            continue  # schon gegossen (anderer Scan, App) → nicht doppelt loggen
        done = complete_care_task(
            household_id=household_id,
            plant_id=task.plant_id,
            task_id=task.id,
            body=None,
            membership=ctx.membership,
            db=ctx.db,
        )
        # log None = inzwischen heute schon erledigt (Router, CASA-29) → kein Eintrag
        if done.log is not None:
            logs.append(done.log)
    result = {"logs": [CareLogResponse.model_validate(log).model_dump(mode="json") for log in logs]}
    if not logs:
        return _already_done(**result)
    return {"changed": True, **result}


# ---------------------------------------------------------------------------
# plant.care_task.done — Pflegeaufgabe einer Pflanze erledigen
# ---------------------------------------------------------------------------


def _plant_care_task_targets(db: Session, household_id: uuid.UUID) -> list[TargetOption]:
    rows = (
        db.query(PlantCareTask, Plant.name)
        .join(Plant, PlantCareTask.plant_id == Plant.id)
        .filter(PlantCareTask.household_id == household_id)
        .order_by(Plant.name, PlantCareTask.care_type, PlantCareTask.label)
        .all()
    )
    return [
        TargetOption(
            task.id,
            f"{plant_name} – {_plant_task_name(task)}",
            care_type=target_care_type(task),
            plant_name=plant_name if target_care_type(task) else None,
        )
        for task, plant_name in rows
    ]


def _load_plant_care_task(db: Session, household_id: uuid.UUID, target_id: uuid.UUID):
    return _get_scoped(db, PlantCareTask, household_id, target_id)


def _describe_plant_care_task_done(ctx: TagContext) -> TagDescription:
    task: PlantCareTask = ctx.target
    plant = ctx.db.get(Plant, task.plant_id)
    plant_name = plant.name if plant else None
    name = _plant_task_name(task)
    details = {
        "plant_id": str(task.plant_id),
        "plant_name": plant_name,
        "care_type": task.care_type,
        "label": (task.label or "").strip() or None,
        "interval_days": task.interval_days,
        "next_due_at": _iso(task.next_due_at),
        "last_done_at": _iso(task.last_done_at),
    }
    care_type = target_care_type(task)
    if task.last_done_at == _plant_today(ctx):
        return TagDescription(
            name, f"'{name}' was already done today", details, False, "ALREADY_DONE",
            target_care_type=care_type,
        )
    return TagDescription(
        target_name=name,
        description=f"Mark '{name}' as done" + (f" for {plant_name}" if plant_name else ""),
        details=details,
        target_care_type=care_type,
    )


def _execute_plant_care_task_done(ctx: TagContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.routers.plants import CareLogResponse, CareTaskResponse, complete_care_task

    # Sperre: parallele Scans laufen nacheinander, der zweite sieht „heute erledigt“
    locked = lock_row(ctx.db, PlantCareTask, ctx.target.id)
    if locked is not None and locked.last_done_at == _plant_today(ctx):
        return _already_done(care_task=CareTaskResponse.model_validate(locked).model_dump(mode="json"))
    done = complete_care_task(
        household_id=ctx.household.id,
        plant_id=ctx.target.plant_id,
        task_id=ctx.target.id,
        body=None,
        membership=ctx.membership,
        db=ctx.db,
    )
    return {
        # changed False = heute schon erledigt (CASA-29, plants-Router)
        "changed": done.changed,
        "care_task": CareTaskResponse.model_validate(done.task).model_dump(mode="json"),
        "log": CareLogResponse.model_validate(done.log).model_dump(mode="json") if done.log else None,
    }


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


def _materialize_chore_assignments(ctx: TagContext) -> None:
    """Fällige Zuweisungen anlegen (wie GET /chores/assignments, inkl. Socket-Events)."""
    from app.routers.chores import list_assignments
    from app.services.chore_scheduler import today_in_tz

    today = today_in_tz(ctx.household.timezone)
    list_assignments(
        household_id=ctx.household.id,
        from_date=today - timedelta(days=14),
        to_date=today + timedelta(days=CHORE_EARLY_DAYS),
        membership=ctx.membership,
        db=ctx.db,
    )


def current_chore_assignment(ctx: TagContext, *, materialize: bool = True) -> ChoreAssignment | None:
    """Die Zuweisung der laufenden Periode — erledigt oder nicht (CASA-05).

    „Aktuell“ ist die jüngste Zuweisung mit Fälligkeit bis heute (auch wenn
    überfällig oder schon erledigt); gibt es keine, die nächste in den kommenden
    ``CHORE_EARLY_DAYS`` Tagen (vorzeitig erledigen). Ist sie erledigt, meldet der
    Scan „schon erledigt“ — ältere offene Zuweisungen bleiben unangetastet, und
    die nächste Periode wird nicht vorzeitig abgehakt. Zuweisungen vor dem
    ``anchor_date`` (alter Zeitplan, vor einer Pause) zählen nicht.
    """
    from app.services.chore_scheduler import today_in_tz

    if materialize:
        _materialize_chore_assignments(ctx)
    today = today_in_tz(ctx.household.timezone)
    base = (
        ctx.db.query(ChoreAssignment)
        .filter(
            ChoreAssignment.household_id == ctx.household.id,
            ChoreAssignment.chore_id == ctx.target.id,
            ChoreAssignment.due_date >= ctx.target.anchor_date,
        )
        .execution_options(populate_existing=True)
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
    if assignment.completed_at is not None:
        return TagDescription(chore.title, f"'{chore.title}' is already done", details, False, "ALREADY_DONE")
    return TagDescription(
        chore.title,
        f"Mark '{chore.title}' as done",
        details,
        confirm={"assignment_id": str(assignment.id)},
    )


def _execute_chore_done(ctx: TagContext, params: dict[str, Any]) -> dict[str, Any]:
    from app.routers.chores import ChoreAssignmentResponse, complete_assignment

    if not ctx.target.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.TAG_NOTHING_TO_DO, "Chore is paused"),
        )
    confirmed_id = _confirm_ids(params, "assignment_id")[0]

    # Erst materialisieren (sperrt/committet selbst), dann Ämtli und bestätigte
    # Zuweisung sperren: parallele Scans laufen nacheinander (CASA-05)
    _materialize_chore_assignments(ctx)
    chore = lock_row(ctx.db, Chore, ctx.target.id)
    if chore is None or not chore.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(ErrorCode.TAG_NOTHING_TO_DO, "Chore is paused"),
        )
    ctx.target = chore
    confirmed = lock_row(ctx.db, ChoreAssignment, confirmed_id)
    if confirmed is None or confirmed.chore_id != chore.id:
        raise _stale()
    if confirmed.completed_at is not None:
        # Wiederholter oder paralleler Scan: nichts anderes abhaken
        return _already_done(assignment=ChoreAssignmentResponse.model_validate(confirmed).model_dump(mode="json"))

    current = current_chore_assignment(ctx, materialize=False)
    if current is None or current.id != confirmed.id:
        # Angezeigt war eine andere Periode (z. B. Mitternacht, Zeitplan geändert)
        raise _stale()

    done = complete_assignment(
        household_id=ctx.household.id,
        assignment_id=confirmed.id,
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

    # Sperre: parallele Scans laufen nacheinander, der zweite sieht is_done (CASA-29)
    todo = lock_row(ctx.db, Todo, ctx.target.id) or ctx.target
    if todo.is_done:
        # Idempotent: zweiter Scan ändert nichts (done_at bleibt, kein weiteres Event)
        return _already_done(todo=_todo_response(todo))
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
            key="plant.water",
            target_type="plant",
            list_targets=_plant_targets,
            load_target=_load_plant,
            describe=_describe_plant_water,
            execute=_execute_plant_water,
            target_optional=True,  # leer = alle fälligen Gießaufgaben (water-all)
            requires_confirm=True,  # Gießaufgaben aus resolve (CASA-18)
        ),
        TagAction(
            key="plant.care_task.done",
            target_type="plant_care_task",
            list_targets=_plant_care_task_targets,
            load_target=_load_plant_care_task,
            describe=_describe_plant_care_task_done,
            execute=_execute_plant_care_task_done,
        ),
        TagAction(
            key="chore.assignment.done",
            target_type="chore",
            list_targets=_chore_targets,
            load_target=_load_chore,
            describe=_describe_chore_done,
            execute=_execute_chore_done,
            requires_confirm=True,  # angezeigte Zuweisung (CASA-18)
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
