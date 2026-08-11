import uuid
import zoneinfo
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import FeedingLog, Household, HouseholdMember, Medication, MedicationLog, Pet, PetCareTask, StoredFile
from app.services.storage import LocalStorageService
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------


class HealthEntrySchema(BaseModel):
    """Validiertes Sub-Model für Pet-Gesundheitseinträge."""

    title: str = Field(..., min_length=1, max_length=100)
    subtitle: str = Field(default="", max_length=200)
    severity: str = Field(default="green")

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        if v not in ("green", "yellow", "red"):
            raise ValueError("severity must be 'green', 'yellow' or 'red'")
        return v


class PetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    species: str = Field(default="cat", max_length=30)
    breed: str | None = Field(None, max_length=80)
    birthdate: date | None = None
    weight_grams: int | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=1000)
    # Slice 3 Profil-Felder (optional bei Erstellung)
    chip_number: str | None = Field(None, max_length=50)
    insurance: str | None = Field(None, max_length=100)
    vet_name: str | None = Field(None, max_length=100)
    food_notes: str | None = Field(None, max_length=500)
    health_entries: list[HealthEntrySchema] | None = Field(None, max_length=50)


class PetUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    species: str | None = Field(None, max_length=30)
    breed: str | None = Field(None, max_length=80)
    birthdate: date | None = None
    weight_grams: int | None = Field(None, ge=0)
    notes: str | None = Field(None, max_length=1000)
    photo_file_id: uuid.UUID | None = None
    # Slice 3
    chip_number: str | None = Field(None, max_length=50)
    insurance: str | None = Field(None, max_length=100)
    vet_name: str | None = Field(None, max_length=100)
    food_notes: str | None = Field(None, max_length=500)
    health_entries: list[HealthEntrySchema] | None = Field(None, max_length=50)


class PetResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    species: str
    breed: str | None
    birthdate: date | None
    weight_grams: int | None
    photo_url: str | None
    photo_file_id: uuid.UUID | None
    notes: str | None
    # Slice 3 Profil-Felder
    chip_number: str | None
    insurance: str | None
    vet_name: str | None
    food_notes: str | None
    health_entries: list[HealthEntrySchema] | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FeedingCreate(BaseModel):
    slot: str = Field(...)

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, v: str) -> str:
        if v not in ("morning", "evening"):
            raise ValueError("slot must be 'morning' or 'evening'")
        return v


class FeedingLogResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    pet_id: uuid.UUID
    slot: str
    fed_at: datetime
    fed_by_user_id: uuid.UUID
    date: date

    model_config = ConfigDict(from_attributes=True)


class PetFeedingStatus(BaseModel):
    pet_id: uuid.UUID
    pet_name: str
    morning: FeedingLogResponse | None
    evening: FeedingLogResponse | None


class FeedAllCreate(BaseModel):
    slot: str = Field(...)

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, v: str) -> str:
        if v not in ("morning", "evening"):
            raise ValueError("slot must be 'morning' or 'evening'")
        return v


class CareTaskCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    interval_days: int = Field(..., ge=1, le=3650)
    next_due_at: date


class CareTaskUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    interval_days: int | None = Field(None, ge=1, le=3650)
    next_due_at: date | None = None


class CareTaskResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    pet_id: uuid.UUID
    name: str
    interval_days: int
    next_due_at: date
    last_done_at: date | None
    notified_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MedicationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    dosage: str | None = Field(None, max_length=50)
    schedule: str | None = Field(None, max_length=100)
    active: bool = True


class MedicationUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    dosage: str | None = Field(None, max_length=50)
    schedule: str | None = Field(None, max_length=100)
    active: bool | None = None


class MedicationResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    pet_id: uuid.UUID
    name: str
    dosage: str | None
    schedule: str | None
    active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MedicationLogResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    medication_id: uuid.UUID
    given_at: datetime
    given_by_user_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/households/{household_id}/pets",
    tags=["pets"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_household_today(db: Session, household_id: uuid.UUID) -> date:
    """Ermittelt das heutige Datum in der Household-Timezone."""
    household = db.get(Household, household_id)
    tz = zoneinfo.ZoneInfo(household.timezone if household else "Europe/Zurich")
    return datetime.now(tz).date()


def _get_medication_or_404(
    db: Session,
    medication_id: uuid.UUID,
    pet_id: uuid.UUID,
    household_id: uuid.UUID,
) -> Medication:
    """Holt ein Medication oder wirft 404."""
    med = db.get(Medication, medication_id)
    if med is None or med.pet_id != pet_id or med.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.MEDICATION_NOT_FOUND,
                "Medication not found for this pet in this household",
            ),
        )
    return med


def _get_care_task_or_404(
    db: Session,
    task_id: uuid.UUID,
    pet_id: uuid.UUID,
    household_id: uuid.UUID,
) -> PetCareTask:
    """Holt einen PetCareTask oder wirft 404."""
    task = db.get(PetCareTask, task_id)
    if task is None or task.pet_id != pet_id or task.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.PET_CARE_TASK_NOT_FOUND,
                "Care task not found for this pet in this household",
            ),
        )
    return task


def _get_pet_or_404(
    db: Session, pet_id: uuid.UUID, household_id: uuid.UUID
) -> Pet:
    """Holt ein Pet oder wirft 404."""
    pet = db.get(Pet, pet_id)
    if pet is None or pet.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.PET_NOT_FOUND, "Pet not found in this household"
            ),
        )
    return pet


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# POST / — Pet erstellen
@router.post("/", response_model=PetResponse, status_code=status.HTTP_201_CREATED)
def create_pet(
    household_id: uuid.UUID,
    body: PetCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    pet = Pet(
        household_id=household_id,
        name=body.name,
        species=body.species,
        breed=body.breed,
        birthdate=body.birthdate,
        weight_grams=body.weight_grams,
        notes=body.notes,
        # Slice 3
        chip_number=body.chip_number,
        insurance=body.insurance,
        vet_name=body.vet_name,
        food_notes=body.food_notes,
        health_entries=[e.model_dump() for e in body.health_entries] if body.health_entries else body.health_entries,
    )
    db.add(pet)
    db.commit()
    db.refresh(pet)

    emit_to_household_sync(
        household_id,
        "pet_created",
        PetResponse.model_validate(pet).model_dump(mode="json"),
    )
    return pet


# GET / — Alle Pets des Households
@router.get("/", response_model=list[PetResponse])
def list_pets(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return (
        db.query(Pet)
        .filter(Pet.household_id == household_id)
        .order_by(Pet.name)
        .all()
    )


# GET /feeding-status — Tagesstatus aller Pets
# WICHTIG: Muss VOR /{pet_id} definiert werden, sonst matched FastAPI "feeding-status" als pet_id
@router.get("/feeding-status", response_model=list[PetFeedingStatus])
def feeding_status(
    household_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    today = _get_household_today(db, household_id)

    pets = (
        db.query(Pet)
        .filter(Pet.household_id == household_id)
        .order_by(Pet.name)
        .all()
    )

    todays_feedings = (
        db.query(FeedingLog)
        .filter(
            FeedingLog.household_id == household_id,
            FeedingLog.date == today,
        )
        .all()
    )

    # Index: (pet_id, slot) → FeedingLog
    feeding_map: dict[tuple[uuid.UUID, str], FeedingLog] = {}
    for fl in todays_feedings:
        feeding_map[(fl.pet_id, fl.slot)] = fl

    result = []
    for pet in pets:
        morning_fl = feeding_map.get((pet.id, "morning"))
        evening_fl = feeding_map.get((pet.id, "evening"))
        result.append(
            PetFeedingStatus(
                pet_id=pet.id,
                pet_name=pet.name,
                morning=FeedingLogResponse.model_validate(morning_fl) if morning_fl else None,
                evening=FeedingLogResponse.model_validate(evening_fl) if evening_fl else None,
            )
        )
    return result


# POST /feed-all — Alle unfed Pets für einen Slot füttern
@router.post("/feed-all", response_model=list[FeedingLogResponse])
def feed_all(
    household_id: uuid.UUID,
    body: FeedAllCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    today = _get_household_today(db, household_id)

    pets = (
        db.query(Pet)
        .filter(Pet.household_id == household_id)
        .all()
    )

    # Bereits gefütterte Pets für heute+slot ermitteln
    already_fed_pet_ids = {
        row.pet_id
        for row in db.query(FeedingLog.pet_id)
        .filter(
            FeedingLog.household_id == household_id,
            FeedingLog.date == today,
            FeedingLog.slot == body.slot,
        )
        .all()
    }

    created = []
    for pet in pets:
        if pet.id in already_fed_pet_ids:
            continue

        feeding = FeedingLog(
            household_id=household_id,
            pet_id=pet.id,
            slot=body.slot,
            fed_at=datetime.now(timezone.utc),
            fed_by_user_id=membership.user_id,
            date=today,
        )
        db.add(feeding)
        created.append(feeding)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Bei Race-Condition: einfach leere Liste zurückgeben, Client refetcht
        return []

    for feeding in created:
        db.refresh(feeding)
        emit_to_household_sync(
            household_id,
            "feeding_created",
            FeedingLogResponse.model_validate(feeding).model_dump(mode="json"),
        )

    return created


# GET /{pet_id} — Einzelnes Pet
@router.get("/{pet_id}", response_model=PetResponse)
def get_pet(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return _get_pet_or_404(db, pet_id, household_id)


# PATCH /{pet_id} — Pet updaten
@router.patch("/{pet_id}", response_model=PetResponse)
def update_pet(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    body: PetUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    pet = _get_pet_or_404(db, pet_id, household_id)
    update_data = body.model_dump(exclude_unset=True)

    # photo_file_id Validierung
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

    for key, value in update_data.items():
        setattr(pet, key, value)

    db.commit()
    db.refresh(pet)

    emit_to_household_sync(
        household_id,
        "pet_updated",
        PetResponse.model_validate(pet).model_dump(mode="json"),
    )
    return pet


# DELETE /{pet_id} — Pet löschen
@router.delete("/{pet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pet(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    pet = _get_pet_or_404(db, pet_id, household_id)

    # StoredFile-Referenz merken für späteres physisches Löschen
    storage_path_to_delete = None
    if pet.photo_file_id:
        stored_file = db.query(StoredFile).filter(StoredFile.id == pet.photo_file_id).first()
        if stored_file:
            storage_path_to_delete = stored_file.storage_path
            db.delete(stored_file)

    db.delete(pet)
    db.commit()

    # Best-effort: Physische Datei nach erfolgreichem Commit entfernen
    if storage_path_to_delete:
        try:
            _pet_storage = LocalStorageService()
            _pet_storage.delete(storage_path_to_delete)
        except Exception:
            pass  # Best-effort cleanup

    emit_to_household_sync(
        household_id,
        "pet_deleted",
        {"id": str(pet_id), "household_id": str(household_id)},
    )


# POST /{pet_id}/feedings — Fütterung erfassen
@router.post(
    "/{pet_id}/feedings",
    response_model=FeedingLogResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_feeding(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    body: FeedingCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)

    today = _get_household_today(db, household_id)

    feeding = FeedingLog(
        household_id=household_id,
        pet_id=pet_id,
        slot=body.slot,
        fed_at=datetime.now(timezone.utc),
        fed_by_user_id=membership.user_id,
        date=today,
    )
    db.add(feeding)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                ErrorCode.FEEDING_DUPLICATE,
                f"Pet already fed for slot '{body.slot}' today",
            ),
        )

    db.refresh(feeding)

    emit_to_household_sync(
        household_id,
        "feeding_created",
        FeedingLogResponse.model_validate(feeding).model_dump(mode="json"),
    )
    return feeding


# DELETE /{pet_id}/feedings/{feeding_id} — Undo Fütterung
@router.delete(
    "/{pet_id}/feedings/{feeding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_feeding(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    feeding_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    feeding = db.get(FeedingLog, feeding_id)
    if (
        feeding is None
        or feeding.pet_id != pet_id
        or feeding.household_id != household_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.FEEDING_NOT_FOUND,
                "Feeding not found for this pet in this household",
            ),
        )

    db.delete(feeding)
    db.commit()

    emit_to_household_sync(
        household_id,
        "feeding_deleted",
        {
            "id": str(feeding_id),
            "pet_id": str(pet_id),
            "household_id": str(household_id),
        },
    )


# ---------------------------------------------------------------------------
# Medication Endpoints
# ---------------------------------------------------------------------------


# POST /{pet_id}/medications — Medikament anlegen
@router.post(
    "/{pet_id}/medications",
    response_model=MedicationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_medication(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    body: MedicationCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)

    med = Medication(
        household_id=household_id,
        pet_id=pet_id,
        name=body.name,
        dosage=body.dosage,
        schedule=body.schedule,
        active=body.active,
    )
    db.add(med)
    db.commit()
    db.refresh(med)

    emit_to_household_sync(
        household_id,
        "medication_created",
        MedicationResponse.model_validate(med).model_dump(mode="json"),
    )
    return med


# GET /{pet_id}/medications — Medikamente auflisten
@router.get("/{pet_id}/medications", response_model=list[MedicationResponse])
def list_medications(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    active: bool | None = None,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)

    query = db.query(Medication).filter(
        Medication.pet_id == pet_id,
        Medication.household_id == household_id,
    )
    if active is not None:
        query = query.filter(Medication.active == active)

    return query.order_by(Medication.name).all()


# PATCH /{pet_id}/medications/{medication_id} — Medikament aktualisieren
@router.patch(
    "/{pet_id}/medications/{medication_id}",
    response_model=MedicationResponse,
)
def update_medication(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    medication_id: uuid.UUID,
    body: MedicationUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)
    med = _get_medication_or_404(db, medication_id, pet_id, household_id)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(med, key, value)

    db.commit()
    db.refresh(med)

    emit_to_household_sync(
        household_id,
        "medication_updated",
        MedicationResponse.model_validate(med).model_dump(mode="json"),
    )
    return med


# DELETE /{pet_id}/medications/{medication_id} — Medikament löschen
@router.delete(
    "/{pet_id}/medications/{medication_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_medication(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    medication_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)
    med = _get_medication_or_404(db, medication_id, pet_id, household_id)

    db.delete(med)
    db.commit()

    emit_to_household_sync(
        household_id,
        "medication_deleted",
        {
            "id": str(medication_id),
            "pet_id": str(pet_id),
            "household_id": str(household_id),
        },
    )


# POST /{pet_id}/medications/{medication_id}/give — Medikament als gegeben markieren
@router.post(
    "/{pet_id}/medications/{medication_id}/give",
    response_model=MedicationLogResponse,
    status_code=status.HTTP_201_CREATED,
)
def give_medication(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    medication_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)
    _get_medication_or_404(db, medication_id, pet_id, household_id)

    log = MedicationLog(
        household_id=household_id,
        medication_id=medication_id,
        given_at=datetime.now(timezone.utc),
        given_by_user_id=membership.user_id,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    emit_to_household_sync(
        household_id,
        "medication_given",
        MedicationLogResponse.model_validate(log).model_dump(mode="json"),
    )
    return log


# GET /{pet_id}/medications/{medication_id}/log — Letzte Gaben
@router.get(
    "/{pet_id}/medications/{medication_id}/log",
    response_model=list[MedicationLogResponse],
)
def get_medication_log(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    medication_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)
    _get_medication_or_404(db, medication_id, pet_id, household_id)

    return (
        db.query(MedicationLog)
        .filter(
            MedicationLog.medication_id == medication_id,
            MedicationLog.household_id == household_id,
        )
        .order_by(MedicationLog.given_at.desc())
        .limit(10)
        .all()
    )


# ---------------------------------------------------------------------------
# Care Task Endpoints
# ---------------------------------------------------------------------------


# GET /{pet_id}/care-tasks/ — Pflegeaufgaben auflisten
@router.get("/{pet_id}/care-tasks/", response_model=list[CareTaskResponse])
def list_care_tasks(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)

    return (
        db.query(PetCareTask)
        .filter(
            PetCareTask.pet_id == pet_id,
            PetCareTask.household_id == household_id,
        )
        .order_by(PetCareTask.next_due_at.asc())
        .all()
    )


# POST /{pet_id}/care-tasks/ — Pflegeaufgabe erstellen
@router.post(
    "/{pet_id}/care-tasks/",
    response_model=CareTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_care_task(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    body: CareTaskCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)

    task = PetCareTask(
        household_id=household_id,
        pet_id=pet_id,
        name=body.name,
        interval_days=body.interval_days,
        next_due_at=body.next_due_at,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    emit_to_household_sync(
        household_id,
        "pet_care_task_created",
        CareTaskResponse.model_validate(task).model_dump(mode="json"),
    )
    return task


# PATCH /{pet_id}/care-tasks/{task_id} — Pflegeaufgabe aktualisieren
@router.patch(
    "/{pet_id}/care-tasks/{task_id}",
    response_model=CareTaskResponse,
)
def update_care_task(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    task_id: uuid.UUID,
    body: CareTaskUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)
    task = _get_care_task_or_404(db, task_id, pet_id, household_id)

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(task, key, value)

    db.commit()
    db.refresh(task)

    emit_to_household_sync(
        household_id,
        "pet_care_task_updated",
        CareTaskResponse.model_validate(task).model_dump(mode="json"),
    )
    return task


# POST /{pet_id}/care-tasks/{task_id}/complete — Pflegeaufgabe als erledigt markieren
@router.post(
    "/{pet_id}/care-tasks/{task_id}/complete",
    response_model=CareTaskResponse,
)
def complete_care_task(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    task_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)
    task = _get_care_task_or_404(db, task_id, pet_id, household_id)

    today = _get_household_today(db, household_id)
    task.last_done_at = today
    task.next_due_at = today + timedelta(days=task.interval_days)
    task.notified_at = None

    db.commit()
    db.refresh(task)

    emit_to_household_sync(
        household_id,
        "pet_care_task_updated",
        CareTaskResponse.model_validate(task).model_dump(mode="json"),
    )
    return task


# DELETE /{pet_id}/care-tasks/{task_id} — Pflegeaufgabe löschen
@router.delete(
    "/{pet_id}/care-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_care_task(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    task_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)
    task = _get_care_task_or_404(db, task_id, pet_id, household_id)

    db.delete(task)
    db.commit()

    emit_to_household_sync(
        household_id,
        "pet_care_task_deleted",
        {"id": str(task.id), "pet_id": str(task.pet_id)},
    )
