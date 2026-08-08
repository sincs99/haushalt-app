import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import verify_household_access
from app.core.error_codes import ErrorCode, error_detail
from app.database import get_db
from app.models import (
    HouseholdMember,
    MealPlanEntry,
    Recipe,
    ShoppingItem,
    ShoppingList,
)
from app.socket_manager import emit_to_household_sync

# ---------------------------------------------------------------------------
# Pydantic Schemas — Recipes
# ---------------------------------------------------------------------------


class RecipeCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=150)
    servings: int = Field(default=2, ge=1)
    cost_rappen: int | None = Field(None, ge=0)
    duration_min: int | None = Field(None, ge=1)
    ingredients: list[str] = Field(default_factory=list, max_length=100)
    is_favorite: bool = False

    @field_validator("ingredients")
    @classmethod
    def validate_ingredients(cls, v: list[str]) -> list[str]:
        for i, item in enumerate(v):
            if len(item) > 200:
                raise ValueError(f"Ingredient at index {i} exceeds 200 characters")
            if not item.strip():
                raise ValueError(f"Ingredient at index {i} must not be blank")
        return v


class RecipeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=150)
    servings: int | None = Field(None, ge=1)
    cost_rappen: int | None = Field(None, ge=0)
    duration_min: int | None = Field(None, ge=1)
    ingredients: list[str] | None = Field(None, max_length=100)
    is_favorite: bool | None = None

    @field_validator("ingredients")
    @classmethod
    def validate_ingredients(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
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
    recipe = _get_recipe_or_404(db, recipe_id, household_id)
    db.delete(recipe)
    db.commit()

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
    ref = week if week is not None else date.today()
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

    # Upsert: existierenden Eintrag suchen
    entry = (
        db.query(MealPlanEntry)
        .filter(
            MealPlanEntry.household_id == household_id,
            MealPlanEntry.date == entry_date,
        )
        .first()
    )

    if entry is not None:
        # Update
        entry.recipe_id = body.recipe_id
        entry.free_text = body.free_text
    else:
        # Create
        entry = MealPlanEntry(
            household_id=household_id,
            date=entry_date,
            recipe_id=body.recipe_id,
            free_text=body.free_text,
        )
        db.add(entry)

    db.commit()
    db.refresh(entry)

    emit_to_household_sync(
        household_id,
        "meal_plan_updated",
        MealPlanEntryResponse.model_validate(entry).model_dump(mode="json"),
    )
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
@meal_plan_router.post(
    "/{entry_id}/add-missing-to-shopping",
    response_model=AddToShoppingResponse,
)
def add_missing_to_shopping(
    household_id: uuid.UUID,
    entry_id: uuid.UUID,
    membership: HouseholdMember = Depends(verify_household_access),
    db: Session = Depends(get_db),
):
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
    ingredients: list[str] = recipe.ingredients or []

    # 4. Standard-Einkaufsliste holen oder erstellen
    shopping_list, list_created = _get_or_create_default_shopping_list(db, household_id)

    added: list[str] = []
    skipped: list[str] = []

    # 5. Für jede Zutat prüfen ob bereits vorhanden (Whitespace strippen)
    for raw_ingredient in ingredients:
        ingredient = raw_ingredient.strip()
        if not ingredient:
            continue  # leere Zutaten überspringen

        exists = (
            db.query(ShoppingItem)
            .filter(
                ShoppingItem.list_id == shopping_list.id,
                func.lower(ShoppingItem.name) == ingredient.lower(),
                ShoppingItem.is_checked == False,  # noqa: E712
            )
            .first()
        )

        if exists:
            skipped.append(ingredient)
        else:
            item_name = ingredient[:200]  # Defense-in-depth: truncate
            item = ShoppingItem(
                household_id=household_id,
                list_id=shopping_list.id,
                name=item_name,
                added_by_user_id=membership.user_id,
            )
            db.add(item)
            db.flush()  # ID generieren

            added.append(ingredient)

    db.commit()

    # Socket-Event bei neu erstellter Einkaufsliste
    if list_created:
        from app.routers.shopping import ShoppingListResponse

        response_data = ShoppingListResponse.model_validate(shopping_list).model_dump(mode="json")
        response_data["open_count"] = len(added)
        emit_to_household_sync(str(household_id), "shopping_list_created", response_data)

    # Socket-Events für jedes neue Item emittieren
    # Wir müssen die Items nach dem Commit nochmal laden für korrekte Daten
    if added:
        new_items = (
            db.query(ShoppingItem)
            .filter(
                ShoppingItem.list_id == shopping_list.id,
                ShoppingItem.household_id == household_id,
                func.lower(ShoppingItem.name).in_([a.lower() for a in added]),
                ShoppingItem.is_checked == False,  # noqa: E712
            )
            .all()
        )
        for item in new_items:
            from app.routers.shopping import ShoppingItemResponse

            emit_to_household_sync(
                household_id,
                "shopping_item_created",
                ShoppingItemResponse.model_validate(item).model_dump(mode="json"),
            )

    return AddToShoppingResponse(
        added=added,
        skipped=skipped,
        list_id=shopping_list.id,
    )
