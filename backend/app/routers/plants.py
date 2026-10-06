import uuid
import zoneinfo
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import (
    PLANT_CARE_TYPES,
    Household,
    HouseholdMember,
    Plant,
    PlantCareLog,
    PlantCareTask,
    StoredFile,
)
from app.routers.files import file_in_use, file_in_use_error, remove_from_storage
from app.socket_manager import emit_to_household_sync

# Standard-Intervalle (Tage) pro Pflegeart
DEFAULT_INTERVAL_DAYS = {
    "water": 7,
    "fertilize": 30,
    "repot": 365,
    "mist": 3,
    "other": 30,
}

CARE_LOG_LIMIT = 50

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


def _validate_care_type(v: str) -> str:
    if v not in PLANT_CARE_TYPES:
        raise ValueError(f"care_type must be one of {', '.join(PLANT_CARE_TYPES)}")
    return v


class PlantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    species: str | None = Field(None, max_length=80)
    location: str | None = Field(None, max_length=80)
    notes: str | None = Field(None, max_length=1000)
    care_notes: str | None = Field(None, max_length=2000)


class PlantUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    species: str | None = Field(None, max_length=80)
    location: str | None = Field(None, max_length=80)
    notes: str | None = Field(None, max_length=1000)
    care_notes: str | None = Field(None, max_length=2000)
    photo_file_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _name_not_null(self):
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name must not be null")
        return self


class PlantResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    species: str | None
    location: str | None
    notes: str | None
    care_notes: str | None
    photo_file_id: uuid.UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CareTaskCreate(BaseModel):
    care_type: str
    label: str | None = Field(None, max_length=100)
    interval_days: int | None = Field(None, ge=1, le=3650)
    next_due_at: date | None = None

    @field_validator("care_type")
    @classmethod
    def validate_care_type(cls, v: str) -> str:
        return _validate_care_type(v)


class CareTaskUpdate(BaseModel):
    label: str | None = Field(None, max_length=100)
    interval_days: int | None = Field(None, ge=1, le=3650)
    next_due_at: date | None = None

    @model_validator(mode="after")
    def _not_null(self):
        for key in ("interval_days", "next_due_at"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} must not be null")
        return self


class CareTaskResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    plant_id: uuid.UUID
    care_type: str
    label: str | None
    interval_days: int
    next_due_at: date
    last_done_at: date | None
    notified_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CareCompleteCreate(BaseModel):
    note: str | None = Field(None, max_length=500)


class CareLogResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    plant_id: uuid.UUID
    care_task_id: uuid.UUID | None
    care_type: str
    label: str | None
    done_at: datetime
    done_by_user_id: uuid.UUID | None
    note: str | None

    model_config = ConfigDict(from_attributes=True)


class CareCompleteResponse(BaseModel):
    task: CareTaskResponse
    log: CareLogResponse


class PlantCareStatusTask(BaseModel):
    task_id: uuid.UUID
    care_type: str
    label: str | None
    interval_days: int
    next_due_at: date
    last_done_at: date | None
    due_today: bool
    overdue: bool


class PlantCareStatus(BaseModel):
    plant_id: uuid.UUID
    plant_name: str
    species: str | None
    location: str | None
    photo_file_id: uuid.UUID | None
    tasks: list[PlantCareStatusTask]
    due_today: bool
    overdue: bool


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/plants",
    tags=["plants"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_household_today(db: Session, household_id: uuid.UUID) -> date:
    """Ermittelt das heutige Datum in der Household-Timezone."""
    household = db.get(Household, household_id)
    tz = zoneinfo.ZoneInfo(household.timezone if household else "Europe/Zurich")
    return datetime.now(tz).date()


def _get_plant_or_404(
    db: Session, plant_id: uuid.UUID, household_id: uuid.UUID
) -> Plant:
    plant = db.get(Plant, plant_id)
    if plant is None or plant.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.PLANT_NOT_FOUND, "Plant not found in this household"
            ),
        )
    return plant


def _get_care_task_or_404(
    db: Session,
    task_id: uuid.UUID,
    plant_id: uuid.UUID,
    household_id: uuid.UUID,
) -> PlantCareTask:
    task = db.get(PlantCareTask, task_id)
    if task is None or task.plant_id != plant_id or task.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.PLANT_CARE_TASK_NOT_FOUND,
                "Care task not found for this plant in this household",
            ),
        )
    return task


def _apply_completion(
    db: Session,
    task: PlantCareTask,
    today: date,
    user_id: uuid.UUID,
    note: str | None = None,
) -> PlantCareLog:
    """Setzt Fälligkeit aus dem Intervall neu und schreibt einen Log-Eintrag."""
    task.last_done_at = today
    task.next_due_at = today + timedelta(days=task.interval_days)
    task.notified_at = None
    log = PlantCareLog(
        household_id=task.household_id,
        plant_id=task.plant_id,
        care_task_id=task.id,
        care_type=task.care_type,
        label=task.label,
        done_at=datetime.now(timezone.utc),
        done_by_user_id=user_id,
        note=note,
    )
    db.add(log)
    return log


# ---------------------------------------------------------------------------
# Plant Endpoints
# ---------------------------------------------------------------------------


# POST / — Pflanze erstellen
@router.post("/", response_model=PlantResponse, status_code=status.HTTP_201_CREATED)
def create_plant(
    household_id: uuid.UUID,
    body: PlantCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    plant = Plant(household_id=household_id, **body.model_dump())
    db.add(plant)
    db.commit()
    db.refresh(plant)

    emit_to_household_sync(
        household_id,
        "plant_created",
        PlantResponse.model_validate(plant).model_dump(mode="json"),
    )
    return plant


# GET / — Alle Pflanzen des Households
@router.get("/", response_model=list[PlantResponse])
def list_plants(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return (
        db.query(Plant)
        .filter(Plant.household_id == household_id)
        .order_by(Plant.name)
        .all()
    )


# GET /care-status — Pflegestatus aller Pflanzen
# WICHTIG: Muss VOR /{plant_id} definiert werden, sonst matched FastAPI "care-status" als plant_id
@router.get("/care-status", response_model=list[PlantCareStatus])
def care_status(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    today = _get_household_today(db, household_id)

    plants = (
        db.query(Plant)
        .filter(Plant.household_id == household_id)
        .order_by(Plant.name)
        .all()
    )
    tasks = (
        db.query(PlantCareTask)
        .filter(PlantCareTask.household_id == household_id)
        .order_by(PlantCareTask.next_due_at.asc(), PlantCareTask.care_type.asc())
        .all()
    )
    tasks_by_plant: dict[uuid.UUID, list[PlantCareTask]] = {}
    for task in tasks:
        tasks_by_plant.setdefault(task.plant_id, []).append(task)

    result = []
    for plant in plants:
        items = [
            PlantCareStatusTask(
                task_id=t.id,
                care_type=t.care_type,
                label=t.label,
                interval_days=t.interval_days,
                next_due_at=t.next_due_at,
                last_done_at=t.last_done_at,
                due_today=t.next_due_at == today,
                overdue=t.next_due_at < today,
            )
            for t in tasks_by_plant.get(plant.id, [])
        ]
        result.append(
            PlantCareStatus(
                plant_id=plant.id,
                plant_name=plant.name,
                species=plant.species,
                location=plant.location,
                photo_file_id=plant.photo_file_id,
                tasks=items,
                due_today=any(i.due_today for i in items),
                overdue=any(i.overdue for i in items),
            )
        )
    return result


# POST /water-all — Alle fälligen Gießaufgaben erledigen
@router.post("/water-all", response_model=list[CareLogResponse])
def water_all(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    today = _get_household_today(db, household_id)

    due_tasks = (
        db.query(PlantCareTask)
        .filter(
            PlantCareTask.household_id == household_id,
            PlantCareTask.care_type == "water",
            PlantCareTask.next_due_at <= today,
        )
        .all()
    )

    logs = [_apply_completion(db, task, today, membership.user_id) for task in due_tasks]
    db.commit()

    for task in due_tasks:
        db.refresh(task)
        emit_to_household_sync(
            household_id,
            "plant_care_task_updated",
            CareTaskResponse.model_validate(task).model_dump(mode="json"),
        )
    for log in logs:
        db.refresh(log)
        emit_to_household_sync(
            household_id,
            "plant_care_logged",
            CareLogResponse.model_validate(log).model_dump(mode="json"),
        )
    return logs


# GET /{plant_id} — Einzelne Pflanze
@router.get("/{plant_id}", response_model=PlantResponse)
def get_plant(
    household_id: uuid.UUID,
    plant_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return _get_plant_or_404(db, plant_id, household_id)


# PATCH /{plant_id} — Pflanze updaten
@router.patch("/{plant_id}", response_model=PlantResponse)
def update_plant(
    household_id: uuid.UUID,
    plant_id: uuid.UUID,
    body: PlantUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    plant = _get_plant_or_404(db, plant_id, household_id)
    update_data = body.model_dump(exclude_unset=True)

    if "photo_file_id" in update_data and update_data["photo_file_id"] is not None:
        file_id = update_data["photo_file_id"]
        stored_file = db.get(StoredFile, file_id)
        if (
            stored_file is None
            or stored_file.household_id != household_id
            or not stored_file.mime_type.startswith("image/")
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_detail(
                    ErrorCode.FILE_MISMATCH,
                    "File not found, does not belong to this household, or is not an image",
                ),
            )
        # Datei darf nicht schon einem Dokument, Pet oder anderer Pflanze gehören,
        # sonst löscht delete_plant später deren Datei mit
        reference = file_in_use(db, [file_id], exclude_plant_id=plant_id)
        if reference is not None:
            raise file_in_use_error(reference)

    for key, value in update_data.items():
        setattr(plant, key, value)

    db.commit()
    db.refresh(plant)

    emit_to_household_sync(
        household_id,
        "plant_updated",
        PlantResponse.model_validate(plant).model_dump(mode="json"),
    )
    return plant


# DELETE /{plant_id} — Pflanze löschen
@router.delete("/{plant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plant(
    household_id: uuid.UUID,
    plant_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    plant = _get_plant_or_404(db, plant_id, household_id)

    storage_path_to_delete = None
    if plant.photo_file_id:
        stored_file = db.get(StoredFile, plant.photo_file_id)
        if stored_file and file_in_use(db, [stored_file.id], exclude_plant_id=plant.id) is None:
            storage_path_to_delete = stored_file.storage_path
            db.delete(stored_file)

    db.delete(plant)
    db.commit()

    # Best-effort: Physische Datei nach erfolgreichem Commit entfernen
    if storage_path_to_delete:
        remove_from_storage(storage_path_to_delete)

    emit_to_household_sync(
        household_id,
        "plant_deleted",
        {"id": str(plant_id), "household_id": str(household_id)},
    )


# ---------------------------------------------------------------------------
# Care Task Endpoints
# ---------------------------------------------------------------------------


# GET /{plant_id}/care-tasks/ — Pflegeaufgaben auflisten
@router.get("/{plant_id}/care-tasks/", response_model=list[CareTaskResponse])
def list_care_tasks(
    household_id: uuid.UUID,
    plant_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_plant_or_404(db, plant_id, household_id)

    return (
        db.query(PlantCareTask)
        .filter(
            PlantCareTask.plant_id == plant_id,
            PlantCareTask.household_id == household_id,
        )
        .order_by(PlantCareTask.next_due_at.asc())
        .all()
    )


# POST /{plant_id}/care-tasks/ — Pflegeaufgabe erstellen
@router.post(
    "/{plant_id}/care-tasks/",
    response_model=CareTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_care_task(
    household_id: uuid.UUID,
    plant_id: uuid.UUID,
    body: CareTaskCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_plant_or_404(db, plant_id, household_id)

    interval_days = body.interval_days or DEFAULT_INTERVAL_DAYS[body.care_type]
    next_due_at = body.next_due_at or (
        _get_household_today(db, household_id) + timedelta(days=interval_days)
    )
    task = PlantCareTask(
        household_id=household_id,
        plant_id=plant_id,
        care_type=body.care_type,
        label=body.label,
        interval_days=interval_days,
        next_due_at=next_due_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    emit_to_household_sync(
        household_id,
        "plant_care_task_created",
        CareTaskResponse.model_validate(task).model_dump(mode="json"),
    )
    return task


# PATCH /{plant_id}/care-tasks/{task_id} — Pflegeaufgabe aktualisieren
@router.patch(
    "/{plant_id}/care-tasks/{task_id}",
    response_model=CareTaskResponse,
)
def update_care_task(
    household_id: uuid.UUID,
    plant_id: uuid.UUID,
    task_id: uuid.UUID,
    body: CareTaskUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_plant_or_404(db, plant_id, household_id)
    task = _get_care_task_or_404(db, task_id, plant_id, household_id)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(task, key, value)
    if "next_due_at" in update_data:
        task.notified_at = None

    db.commit()
    db.refresh(task)

    emit_to_household_sync(
        household_id,
        "plant_care_task_updated",
        CareTaskResponse.model_validate(task).model_dump(mode="json"),
    )
    return task


# POST /{plant_id}/care-tasks/{task_id}/complete — Pflege erledigt (Log + neue Fälligkeit)
@router.post(
    "/{plant_id}/care-tasks/{task_id}/complete",
    response_model=CareCompleteResponse,
)
def complete_care_task(
    household_id: uuid.UUID,
    plant_id: uuid.UUID,
    task_id: uuid.UUID,
    body: CareCompleteCreate | None = None,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_plant_or_404(db, plant_id, household_id)
    task = _get_care_task_or_404(db, task_id, plant_id, household_id)

    today = _get_household_today(db, household_id)
    log = _apply_completion(
        db, task, today, membership.user_id, body.note if body else None
    )
    db.commit()
    db.refresh(task)
    db.refresh(log)

    task_data = CareTaskResponse.model_validate(task)
    log_data = CareLogResponse.model_validate(log)
    emit_to_household_sync(
        household_id, "plant_care_task_updated", task_data.model_dump(mode="json")
    )
    emit_to_household_sync(
        household_id, "plant_care_logged", log_data.model_dump(mode="json")
    )
    return CareCompleteResponse(task=task_data, log=log_data)


# DELETE /{plant_id}/care-tasks/{task_id} — Pflegeaufgabe löschen
@router.delete(
    "/{plant_id}/care-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_care_task(
    household_id: uuid.UUID,
    plant_id: uuid.UUID,
    task_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_plant_or_404(db, plant_id, household_id)
    task = _get_care_task_or_404(db, task_id, plant_id, household_id)

    db.delete(task)
    db.commit()

    emit_to_household_sync(
        household_id,
        "plant_care_task_deleted",
        {
            "id": str(task_id),
            "plant_id": str(plant_id),
            "household_id": str(household_id),
        },
    )


# GET /{plant_id}/care-log — Letzte Pflege-Einträge
@router.get("/{plant_id}/care-log", response_model=list[CareLogResponse])
def get_care_log(
    household_id: uuid.UUID,
    plant_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_plant_or_404(db, plant_id, household_id)

    return (
        db.query(PlantCareLog)
        .filter(
            PlantCareLog.plant_id == plant_id,
            PlantCareLog.household_id == household_id,
        )
        .order_by(PlantCareLog.done_at.desc())
        .limit(CARE_LOG_LIMIT)
        .all()
    )
