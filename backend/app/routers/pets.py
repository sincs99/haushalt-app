import uuid
import zoneinfo
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.core.patch_schema import PatchModel
from app.database import get_db
from app.models import (
    FeedingLog,
    Household,
    HouseholdMember,
    Medication,
    MedicationLog,
    Pet,
    PetCareTask,
    StoredFile,
)
from app.routers.files import file_in_use, file_in_use_error, lock_files, remove_from_storage
from app.services.care_schedule import apply_care_task_update
from app.services.client_ids import commit_or_get_existing, get_existing_by_client_id
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


class PetUpdate(PatchModel):
    # null auf NOT-NULL-Spalten von Pet → 422 (app/core/patch_schema.py)
    __orm_model__ = Pet

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
    # Archiv (PD-P2): verstorben/abgegeben — Verlauf bleibt, Tier ist aus dem Alltag raus
    archived: bool
    archived_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PetHistoryResponse(BaseModel):
    """Umfang des Verlaufs, der beim endgültigen Löschen eines Tiers verloren geht."""

    feedings: int
    medications: int
    medication_logs: int
    care_tasks: int


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


class CareTaskUpdate(PatchModel):
    # null auf NOT-NULL-Spalten von PetCareTask → 422 (app/core/patch_schema.py)
    __orm_model__ = PetCareTask

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


class MedicationUpdate(PatchModel):
    # null auf NOT-NULL-Spalten von Medication → 422 (app/core/patch_schema.py)
    __orm_model__ = Medication

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


class MedicationGive(BaseModel):
    # Client-generierte ID der Gabe (Idempotenz bei Retry/Doppel-Tap, CASA-14)
    id: uuid.UUID | None = None


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


def _ensure_not_archived(pet: Pet) -> None:
    """Archivierte Tiere werden nicht mehr gefüttert (PD-P2/P3)."""
    if pet.archived:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.PET_ARCHIVED, "Pet is archived"),
        )


def _emit_pet_updated(household_id: uuid.UUID, pet: Pet) -> None:
    emit_to_household_sync(
        household_id,
        "pet_updated",
        PetResponse.model_validate(pet).model_dump(mode="json"),
    )


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

    # Archivierte Tiere werden nicht mehr gefüttert (PD-P2)
    pets = (
        db.query(Pet)
        .filter(Pet.household_id == household_id, Pet.archived.is_(False))
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

    # Feste Reihenfolge: parallele feed-all-Requests sperren die Unique-Einträge in
    # derselben Reihenfolge (kein Deadlock). Archivierte Tiere nicht (PD-P3).
    pets = (
        db.query(Pet)
        .filter(Pet.household_id == household_id, Pet.archived.is_(False))
        .order_by(Pet.id)
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

    # Savepoint pro Tier (CASA-13): Kollidiert eine parallele Einzelfütterung mit dem
    # Unique (pet, date, slot), fällt nur dieses Tier weg — die übrigen werden trotzdem
    # gefüttert. Zurückgegeben wird genau das, was dieser Request angelegt hat.
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
        savepoint = db.begin_nested()
        try:
            db.add(feeding)
            db.flush()
        except IntegrityError:
            savepoint.rollback()
            continue
        savepoint.commit()
        created.append(feeding)

    db.commit()

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
        # Datei bis zum Commit sperren: parallele Zuordnung derselben Datei (Dokument,
        # anderes Tier) wartet und sieht danach diese Referenz (CASA-28)
        locked = lock_files(db, [file_id])
        stored_file = locked[0] if locked else None
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
        # Datei darf nicht schon einem Dokument oder anderen Pet gehören,
        # sonst löscht delete_pet später deren Datei mit
        reference = file_in_use(db, [file_id], exclude_pet_id=pet_id)
        if reference is not None:
            raise file_in_use_error(reference)

    for key, value in update_data.items():
        setattr(pet, key, value)

    db.commit()
    db.refresh(pet)

    _emit_pet_updated(household_id, pet)
    return pet


# POST /{pet_id}/archive — Tier archivieren (verstorben/abgegeben), Verlauf bleibt
@router.post("/{pet_id}/archive", response_model=PetResponse)
def archive_pet(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    pet = _get_pet_or_404(db, pet_id, household_id)
    if not pet.archived:
        pet.archived = True
        pet.archived_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(pet)
        _emit_pet_updated(household_id, pet)
    return pet


# POST /{pet_id}/unarchive — Tier wieder aktivieren
@router.post("/{pet_id}/unarchive", response_model=PetResponse)
def unarchive_pet(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    pet = _get_pet_or_404(db, pet_id, household_id)
    if pet.archived:
        pet.archived = False
        pet.archived_at = None
        db.commit()
        db.refresh(pet)
        _emit_pet_updated(household_id, pet)
    return pet


# GET /{pet_id}/history — Umfang des Verlaufs (Warnung vor endgültigem Löschen)
@router.get("/{pet_id}/history", response_model=PetHistoryResponse)
def pet_history(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    _get_pet_or_404(db, pet_id, household_id)

    def count(query) -> int:
        return query.scalar() or 0

    return PetHistoryResponse(
        feedings=count(db.query(func.count(FeedingLog.id)).filter(FeedingLog.pet_id == pet_id)),
        medications=count(db.query(func.count(Medication.id)).filter(Medication.pet_id == pet_id)),
        medication_logs=count(
            db.query(func.count(MedicationLog.id))
            .join(Medication, MedicationLog.medication_id == Medication.id)
            .filter(Medication.pet_id == pet_id)
        ),
        care_tasks=count(db.query(func.count(PetCareTask.id)).filter(PetCareTask.pet_id == pet_id)),
    )


# DELETE /{pet_id} — Pet endgültig löschen (inkl. Verlauf). Die App bietet zuerst
# „Archivieren“ an und warnt mit den Zahlen aus GET /{pet_id}/history (PD-P2).
@router.delete("/{pet_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pet(
    household_id: uuid.UUID,
    pet_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    pet = _get_pet_or_404(db, pet_id, household_id)

    # StoredFile-Referenz merken für späteres physisches Löschen — nur wenn die
    # Datei von nichts anderem (Dokument, anderes Pet) referenziert wird
    storage_path_to_delete = None
    if pet.photo_file_id:
        stored_file = db.get(StoredFile, pet.photo_file_id)
        if stored_file and file_in_use(db, [stored_file.id], exclude_pet_id=pet.id) is None:
            storage_path_to_delete = stored_file.storage_path
            db.delete(stored_file)

    db.delete(pet)
    db.commit()

    # Best-effort: Physische Datei nach erfolgreichem Commit entfernen
    if storage_path_to_delete:
        remove_from_storage(storage_path_to_delete)

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
    _ensure_not_archived(_get_pet_or_404(db, pet_id, household_id))

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

    # Gaben-Verlauf nie still mitlöschen (PD-P2 / CASA-15): stattdessen deaktivieren
    has_history = (
        db.query(MedicationLog.id).filter(MedicationLog.medication_id == medication_id).first()
        is not None
    )
    if has_history:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=error_detail(
                ErrorCode.MEDICATION_HAS_HISTORY,
                "Medication has administration records; deactivate it instead",
            ),
        )

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
    response: Response,
    body: MedicationGive | None = None,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    """Gabe erfassen — immer möglich, auch mehrmals am Tag (PD-P1). Nie still
    zusammenführen oder verwerfen; die App warnt vor einer zweiten Gabe kurz nach
    der letzten. Nur dieselbe Gabe (gleiche Client-ID, z. B. Retry) wird nicht
    doppelt geschrieben (CASA-14)."""
    _get_pet_or_404(db, pet_id, household_id)
    med = _get_medication_or_404(db, medication_id, pet_id, household_id)
    client_id = body.id if body else None

    def existing_for_this_medication(existing: MedicationLog) -> MedicationLog:
        # Client-ID gehört zur Gabe eines anderen Medikaments → Konflikt
        if existing.medication_id != medication_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(ErrorCode.ENTITY_ID_CONFLICT, "Id is already in use"),
            )
        response.status_code = status.HTTP_200_OK
        return existing

    existing = get_existing_by_client_id(db, MedicationLog, client_id, household_id)
    if existing is not None:
        return existing_for_this_medication(existing)

    if not med.active:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.MEDICATION_INACTIVE, "Medication is inactive"),
        )

    log = MedicationLog(
        household_id=household_id,
        medication_id=medication_id,
        given_at=datetime.now(timezone.utc),
        given_by_user_id=membership.user_id,
    )
    if client_id is not None:
        log.id = client_id
    db.add(log)
    existing = commit_or_get_existing(db, MedicationLog, client_id, household_id)
    if existing is not None:
        return existing_for_this_medication(existing)
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

    # Neue Fälligkeit bzw. geändertes Intervall → Fälligkeit/Erinnerung neu (PD-P4 / E-2)
    apply_care_task_update(
        task, body.model_dump(exclude_unset=True), _get_household_today(db, household_id)
    )

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
