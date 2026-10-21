import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.core.patch_schema import PatchModel
from app.database import get_db
from app.models import (
    HouseholdMember,
    MealPlanEntry,
    Recipe,
    ShoppingList,
)
from app.services.household_time import household_today
from app.services.locking import lock_household, lock_row
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas — Recipes
# ---------------------------------------------------------------------------


MAX_STEP_LENGTH = 1000
MAX_TAG_LENGTH = 30


def _validate_text_list(v: list[str], label: str, max_len: int) -> list[str]:
    for i, item in enumerate(v):
        if len(item) > max_len:
            raise ValueError(f"{label} at index {i} exceeds {max_len} characters")
        if not item.strip():
            raise ValueError(f"{label} at index {i} must not be blank")
    return v


class RecipeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    servings: int = Field(default=2, ge=1)
    cost_rappen: int | None = Field(None, ge=0)
    duration_min: int | None = Field(None, ge=1)
    ingredients: list[str] = Field(default_factory=list, max_length=100)
    steps: list[str] = Field(default_factory=list, max_length=30)
    tags: list[str] = Field(default_factory=list, max_length=10)
    is_favorite: bool = False

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: list[str]) -> list[str]:
        return _validate_text_list(v, "Step", MAX_STEP_LENGTH)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        return _validate_text_list(v, "Tag", MAX_TAG_LENGTH)

    @field_validator("ingredients")
    @classmethod
    def validate_ingredients(cls, v: list[str]) -> list[str]:
        for i, item in enumerate(v):
            if len(item) > 200:
                raise ValueError(f"Ingredient at index {i} exceeds 200 characters")
            if not item.strip():
                raise ValueError(f"Ingredient at index {i} must not be blank")
        return v


class RecipeUpdate(PatchModel):
    # null auf NOT-NULL-Spalten von Recipe → 422 (app/core/patch_schema.py)
    __orm_model__ = Recipe

    name: str | None = Field(None, min_length=1, max_length=150)
    servings: int | None = Field(None, ge=1)
    cost_rappen: int | None = Field(None, ge=0)
    duration_min: int | None = Field(None, ge=1)
    ingredients: list[str] | None = Field(None, max_length=100)
    steps: list[str] | None = Field(None, max_length=30)
    tags: list[str] | None = Field(None, max_length=10)
    is_favorite: bool | None = None

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: list[str] | None) -> list[str]:
        # null → leere Liste (Spalte ist NOT NULL)
        return _validate_text_list(v or [], "Step", MAX_STEP_LENGTH)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str] | None) -> list[str]:
        return _validate_text_list(v or [], "Tag", MAX_TAG_LENGTH)

    @field_validator("ingredients")
    @classmethod
    def validate_ingredients(cls, v: list[str] | None) -> list[str]:
        # null → leere Liste wie bei steps/tags (Spalte ist NOT NULL, CASA-04)
        if v is None:
            return []
        for i, item in enumerate(v):
            if len(item) > 200:
                raise ValueError(f"Ingredient at index {i} exceeds 200 characters")
            if not item.strip():
                raise ValueError(f"Ingredient at index {i} must not be blank")
        return v


class RecipeResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    servings: int
    cost_rappen: int | None
    duration_min: int | None
    ingredients: list[str]
    steps: list[str] = []
    tags: list[str] = []
    is_favorite: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Pydantic Schemas — MealPlan
# ---------------------------------------------------------------------------


class MealPlanAssign(BaseModel):
    recipe_id: uuid.UUID | None = None
    free_text: str | None = Field(None, max_length=150)


class MealPlanEntryResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    date: date
    recipe_id: uuid.UUID | None
    free_text: str | None
    recipe: RecipeResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class AddToShoppingRequest(BaseModel):
    # Zielliste (aktive Liste im Client); ohne → erste Liste des Haushalts
    list_id: uuid.UUID | None = None


class AddToShoppingResponse(BaseModel):
    added: list[str]
    skipped: list[str]
    list_id: uuid.UUID


# ---------------------------------------------------------------------------
# Router — Recipes
# ---------------------------------------------------------------------------

recipe_router = APIRouter(
    prefix="/api/households/{household_id}/recipes",
    tags=["food"],
)


# ---------------------------------------------------------------------------
# Router — MealPlan
# ---------------------------------------------------------------------------

meal_plan_router = APIRouter(
    prefix="/api/households/{household_id}/meal-plan",
    tags=["food"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_recipe_or_404(
    db: Session, recipe_id: uuid.UUID, household_id: uuid.UUID
) -> Recipe:
    """Holt ein Recipe oder wirft 404."""
    recipe = db.get(Recipe, recipe_id)
    if recipe is None or recipe.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.RECIPE_NOT_FOUND, "Recipe not found in this household"
            ),
        )
    return recipe


def _get_meal_plan_entry_or_404(
    db: Session, entry_id: uuid.UUID, household_id: uuid.UUID
) -> MealPlanEntry:
    """Holt einen MealPlanEntry oder wirft 404."""
    entry = db.get(MealPlanEntry, entry_id)
    if entry is None or entry.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.MEAL_PLAN_ENTRY_NOT_FOUND,
                "Meal plan entry not found in this household",
            ),
        )
    return entry


def upsert_meal_plan_entry(
    db: Session,
    household_id: uuid.UUID,
    entry_date: date,
    recipe_id: uuid.UUID | None,
    free_text: str | None,
    overwrite: bool = True,
) -> MealPlanEntry | None:
    """Menüplan-Eintrag atomar anlegen/ersetzen (``INSERT … ON CONFLICT``, CASA-19/24).

    Zwei gleichzeitige Schreiber auf denselben Tag liefen beim Check-then-Insert in
    den Unique-Constraint (500). ``overwrite=False`` legt nur an, wenn der Tag frei
    ist, und liefert sonst None (Entscheid einer Essens-Abstimmung, PD-M1).
    Committet NICHT.
    """
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    stmt = insert(MealPlanEntry).values(
        id=uuid.uuid4(),
        household_id=household_id,
        date=entry_date,
        recipe_id=recipe_id,
        free_text=free_text,
    )
    conflict = ["household_id", "date"]
    if overwrite:
        stmt = stmt.on_conflict_do_update(
            index_elements=conflict,
            set_={"recipe_id": recipe_id, "free_text": free_text},
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=conflict)
    if db.execute(stmt).rowcount != 1:
        return None
    return (
        db.query(MealPlanEntry)
        .filter(MealPlanEntry.household_id == household_id, MealPlanEntry.date == entry_date)
        .populate_existing()
        .one()
    )


def meal_plan_entry_payload(entry: MealPlanEntry) -> dict:
    """Vollständiger Eintrag für Socket-Events (meal_plan_updated)."""
    return MealPlanEntryResponse.model_validate(entry).model_dump(mode="json")


def _week_bounds(ref: date) -> tuple[date, date]:
    """Berechne Montag und Sonntag der Woche, die *ref* enthält."""
    monday = ref - timedelta(days=ref.weekday())  # weekday() 0=Mo
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _get_or_create_default_shopping_list(
    db: Session, household_id: uuid.UUID
) -> tuple[ShoppingList, bool]:
    """Gibt (liste, created_flag) zurück. Erstellt eine neue, falls keine existiert."""
    shopping_list = (
        db.query(ShoppingList)
        .filter(ShoppingList.household_id == household_id)
        .order_by(ShoppingList.position)
        .first()
    )
    if shopping_list is None:
        shopping_list = ShoppingList(
            household_id=household_id,
            name="Einkaufsliste",
            position=0,
        )
        db.add(shopping_list)
        db.flush()  # ID generieren, aber noch nicht committen
        return shopping_list, True
    return shopping_list, False


# ---------------------------------------------------------------------------
# Recipe Endpoints
# ---------------------------------------------------------------------------


# POST / — Rezept erstellen
@recipe_router.post("/", response_model=RecipeResponse, status_code=status.HTTP_201_CREATED)
def create_recipe(
    household_id: uuid.UUID,
    body: RecipeCreate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    recipe = Recipe(
        household_id=household_id,
        name=body.name,
        servings=body.servings,
        cost_rappen=body.cost_rappen,
        duration_min=body.duration_min,
        ingredients=body.ingredients,
        steps=body.steps,
        tags=body.tags,
        is_favorite=body.is_favorite,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)

    emit_to_household_sync(
        household_id,
        "recipe_created",
        RecipeResponse.model_validate(recipe).model_dump(mode="json"),
    )
    return recipe


# GET / — Alle Rezepte (optional nur Favoriten)
@recipe_router.get("/", response_model=list[RecipeResponse])
def list_recipes(
    household_id: uuid.UUID,
    favorites_only: bool = False,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    query = db.query(Recipe).filter(Recipe.household_id == household_id)
    if favorites_only:
        query = query.filter(Recipe.is_favorite == True)  # noqa: E712
    return query.order_by(Recipe.name).all()


# GET /{recipe_id} — Einzelnes Rezept
@recipe_router.get("/{recipe_id}", response_model=RecipeResponse)
def get_recipe(
    household_id: uuid.UUID,
    recipe_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    return _get_recipe_or_404(db, recipe_id, household_id)


# PATCH /{recipe_id} — Rezept updaten
@recipe_router.patch("/{recipe_id}", response_model=RecipeResponse)
def update_recipe(
    household_id: uuid.UUID,
    recipe_id: uuid.UUID,
    body: RecipeUpdate,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    recipe = _get_recipe_or_404(db, recipe_id, household_id)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(recipe, field, value)

    db.commit()
    db.refresh(recipe)

    emit_to_household_sync(
        household_id,
        "recipe_updated",
        RecipeResponse.model_validate(recipe).model_dump(mode="json"),
    )
    return recipe


# DELETE /{recipe_id} — Rezept löschen
@recipe_router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipe(
    household_id: uuid.UUID,
    recipe_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Gesperrt: ein parallel geplanter Eintrag wartet und scheitert danach am FK,
    # statt nach dem Löschen ohne Rezept und ohne Text dazustehen
    recipe = lock_row(db, Recipe, recipe_id)
    if recipe is None or recipe.household_id != household_id:
        _get_recipe_or_404(db, recipe_id, household_id)  # → 404

    # Geplante Mahlzeiten behalten den Rezeptnamen als Freitext (PD-M3, CASA-52)
    db.execute(
        update(MealPlanEntry)
        .where(MealPlanEntry.household_id == household_id, MealPlanEntry.recipe_id == recipe.id)
        .values(recipe_id=None, free_text=recipe.name[:150])
        .execution_options(synchronize_session=False)
    )
    db.delete(recipe)
    db.commit()
    db.expire_all()

    emit_to_household_sync(
        household_id,
        "recipe_deleted",
        {"id": str(recipe_id)},
    )


# ---------------------------------------------------------------------------
# MealPlan Endpoints
# ---------------------------------------------------------------------------


# GET / — Wochenplan (7 Tage MO–SO)
@meal_plan_router.get("/", response_model=list[MealPlanEntryResponse])
def get_week_plan(
    household_id: uuid.UUID,
    week: date | None = Query(None, description="Beliebiges Datum innerhalb der Zielwoche (YYYY-MM-DD)"),
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    ref = week if week is not None else household_today(db, household_id)
    monday, sunday = _week_bounds(ref)

    entries = (
        db.query(MealPlanEntry)
        .filter(
            MealPlanEntry.household_id == household_id,
            MealPlanEntry.date >= monday,
            MealPlanEntry.date <= sunday,
        )
        .order_by(MealPlanEntry.date)
        .all()
    )
    return entries


# PUT /{date} — Upsert: MealPlanEntry für ein Datum erstellen oder aktualisieren
@meal_plan_router.put("/{entry_date}", response_model=MealPlanEntryResponse)
def upsert_meal_plan(
    household_id: uuid.UUID,
    entry_date: date,
    body: MealPlanAssign,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    # Whitespace-only free_text normalisieren
    if body.free_text is not None:
        body.free_text = body.free_text.strip() or None

    # Mindestens recipe_id oder free_text muss gesetzt sein
    if body.recipe_id is None and not body.free_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(
                ErrorCode.MEAL_PLAN_NO_RECIPE,
                "Either recipe_id or free_text must be provided",
            ),
        )

    # Wenn recipe_id gesetzt → prüfen ob Rezept existiert und zum Haushalt gehört
    if body.recipe_id is not None:
        _get_recipe_or_404(db, body.recipe_id, household_id)

    # Upsert atomar (ON CONFLICT) — parallele PUTs auf denselben Tag ohne 500
    entry = upsert_meal_plan_entry(db, household_id, entry_date, body.recipe_id, body.free_text)
    db.commit()
    db.refresh(entry)

    emit_to_household_sync(household_id, "meal_plan_updated", meal_plan_entry_payload(entry))
    return entry


# DELETE /{date} — MealPlanEntry löschen
@meal_plan_router.delete("/{entry_date}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meal_plan(
    household_id: uuid.UUID,
    entry_date: date,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    entry = (
        db.query(MealPlanEntry)
        .filter(
            MealPlanEntry.household_id == household_id,
            MealPlanEntry.date == entry_date,
        )
        .first()
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=error_detail(
                ErrorCode.MEAL_PLAN_ENTRY_NOT_FOUND,
                "No meal plan entry for this date",
            ),
        )

    db.delete(entry)
    db.commit()

    emit_to_household_sync(
        household_id,
        "meal_plan_deleted",
        {"date": str(entry_date)},
    )


# POST /{entry_id}/add-missing-to-shopping — Zutaten in Einkaufsliste übernehmen
# Gleiche Logik wie POST /shopping-items/bulk-add (PD-M2): Ziel = vom Client
# übergebene (aktive) Liste, sonst die erste; Dedupe gegen offene Items aller Listen.
@meal_plan_router.post(
    "/{entry_id}/add-missing-to-shopping",
    response_model=AddToShoppingResponse,
)
def add_missing_to_shopping(
    household_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: AddToShoppingRequest | None = None,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
    from app.routers.shopping import (
        ShoppingListResponse,
        bulk_add_items,
        emit_items_created,
    )

    # 1. MealPlanEntry laden (scoped by household_id)
    entry = _get_meal_plan_entry_or_404(db, entry_id, household_id)

    # 2. recipe_id muss gesetzt sein
    if entry.recipe_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(
                ErrorCode.MEAL_PLAN_NO_RECIPE,
                "This meal plan entry has no recipe assigned",
            ),
        )

    # 3. Recipe laden
    recipe = _get_recipe_or_404(db, entry.recipe_id, household_id)

    # 4. Haushalt sperren (Dedupe über alle Listen, keine zwei Standard-Listen
    #    bei parallelen Aufrufen — CASA-53), dann Zielliste bestimmen
    lock_household(db, household_id)
    list_created = False
    if body is not None and body.list_id is not None:
        shopping_list = lock_row(db, ShoppingList, body.list_id)
        if shopping_list is None or shopping_list.household_id != household_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail(ErrorCode.SHOPPING_LIST_NOT_FOUND, "Shopping list not found"),
            )
    else:
        shopping_list, list_created = _get_or_create_default_shopping_list(db, household_id)

    # 5. Anlegen mit Dedupe
    added, skipped = bulk_add_items(
        db, household_id, shopping_list, recipe.ingredients or [], membership.user_id
    )
    db.commit()
    for item in added:
        db.refresh(item)

    # Socket-Event bei neu erstellter Einkaufsliste
    if list_created:
        db.refresh(shopping_list)
        response_data = ShoppingListResponse.model_validate(shopping_list).model_dump(mode="json")
        response_data["open_count"] = len(added)
        emit_to_household_sync(str(household_id), "shopping_list_created", response_data)
    emit_items_created(household_id, added)

    return AddToShoppingResponse(
        added=[item.name for item in added],
        skipped=skipped,
        list_id=shopping_list.id,
    )
