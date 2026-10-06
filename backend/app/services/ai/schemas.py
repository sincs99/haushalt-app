"""Schemas des KI-Assistenten.

Zwei Arten von Modellen:

- **Request-Modelle** validieren die Eingaben aus dem Frontend (Längen, Anzahl).
- **Output-Modelle** (``*Output``) gehen als JSON-Schema an die API
  (``output_config.format``) und beschreiben, was das Modell liefern muss. Sie sind
  bewusst ohne harte Längen-/Bereichsgrenzen gehalten (die Structured Outputs nicht
  alle durchsetzen); ``recipe.py`` / ``plant_care.py`` bringen das Ergebnis danach
  in die Grenzen der App-Schemas. Übernommen wird nur, was im Schema steht.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.routers.food import RecipeCreate

Locale = Literal["de", "en"]
RecipePreference = Literal["vegetarian", "quick", "kids", "leftovers"]


def _strip_items(values: list[str], max_len: int, label: str) -> list[str]:
    cleaned: list[str] = []
    for i, value in enumerate(values):
        item = value.strip()
        if not item:
            raise ValueError(f"{label} at index {i} must not be blank")
        if len(item) > max_len:
            raise ValueError(f"{label} at index {i} exceeds {max_len} characters")
        cleaned.append(item)
    return cleaned


# ---------------------------------------------------------------------------
# Rezept
# ---------------------------------------------------------------------------


class RecipeSuggestionRequest(BaseModel):
    ingredients: list[str] = Field(..., min_length=1, max_length=30)
    servings: int = Field(2, ge=1, le=20)
    preferences: list[RecipePreference] = Field(default_factory=list, max_length=4)
    note: str | None = Field(None, max_length=200)
    locale: Locale = "de"

    @field_validator("ingredients")
    @classmethod
    def clean_ingredients(cls, v: list[str]) -> list[str]:
        return _strip_items(v, 100, "Ingredient")

    @field_validator("preferences")
    @classmethod
    def unique_preferences(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))

    @field_validator("note")
    @classmethod
    def blank_note_to_none(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class IngredientOutput(BaseModel):
    name: str = Field(description="Ingredient name without quantity")
    quantity: str | None = Field(
        description="Quantity with metric unit for the requested servings, e.g. '200 g'; null for 'to taste'"
    )


class RecipeOutput(BaseModel):
    name: str = Field(description="Short recipe name")
    servings: int = Field(description="Number of servings")
    duration_min: int = Field(description="Total time in minutes (preparation + cooking)")
    ingredients: list[IngredientOutput] = Field(description="All ingredients of the recipe with quantities")
    steps: list[str] = Field(description="Preparation steps, one short sentence or paragraph each")
    tags: list[str] = Field(description="1-5 short tags")
    missing_ingredients: list[IngredientOutput] = Field(
        description="Recipe ingredients that are not in the household's list (excluding salt, pepper, oil, water)"
    )
    tip: str | None = Field(description="One short tip or null")


class ShoppingSuggestion(BaseModel):
    """Passt auf ``ShoppingItemCreate`` (name ≤ 200, quantity ≤ 50)."""

    name: str
    quantity: str | None = None


class RecipeSuggestionResponse(BaseModel):
    """Vorschlag zur Prüfung — wird NICHT gespeichert.

    ``recipe`` hat genau die Felder von ``RecipeCreate`` und kann unverändert an
    ``POST /api/households/{id}/recipes/`` geschickt werden.
    """

    recipe: RecipeCreate
    missing_ingredients: list[ShoppingSuggestion]
    tip: str | None = None


# ---------------------------------------------------------------------------
# Pflanzenpflege
# ---------------------------------------------------------------------------


class LightRequirement(StrEnum):
    low = "low"  # Schatten / wenig Licht
    medium = "medium"  # Halbschatten
    bright_indirect = "bright_indirect"  # hell, ohne direkte Mittagssonne
    full_sun = "full_sun"  # vollsonnig


class PetToxicity(StrEnum):
    unknown = "unknown"
    non_toxic = "non_toxic"
    toxic = "toxic"


class PlantCareRequest(BaseModel):
    plant: str = Field(..., min_length=1, max_length=100)
    location: str | None = Field(None, max_length=200)
    locale: Locale = "de"

    @field_validator("plant")
    @classmethod
    def strip_plant(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Plant must not be blank")
        return v.strip()

    @field_validator("location")
    @classmethod
    def blank_location_to_none(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class PlantCareOutput(BaseModel):
    recognized: bool = Field(description="false if the input does not name a plant")
    plant_name: str = Field(description="Common name of the plant")
    botanical_name: str | None = Field(description="Botanical name or null")
    watering_interval_days: int = Field(description="Typical watering interval in days during the growing season")
    fertilizing_interval_days: int | None = Field(
        description="Fertilizing interval in days during the growing season; null if no fertilizer is needed"
    )
    repotting_interval_months: int | None = Field(
        description="Repotting interval in months; null if repotting is unusual"
    )
    light: LightRequirement
    location_tip: str = Field(description="1-2 sentences about the location")
    care_notes: str = Field(description="2-4 sentences of care notes")
    pet_toxicity: PetToxicity = Field(
        description="Toxicity for cats and dogs; unknown if not certain"
    )
    pet_toxicity_note: str | None = Field(description="Short note on toxicity or null")


class PlantCareAdvice(BaseModel):
    """Antwort von ``POST /ai/plant-care`` — Vorlage für Pflegeaufgaben im Pflanzen-Modul."""

    plant_name: str = Field(..., max_length=100)
    botanical_name: str | None = Field(None, max_length=100)
    watering_interval_days: int = Field(..., ge=1, le=365)
    fertilizing_interval_days: int | None = Field(None, ge=1, le=365)
    repotting_interval_months: int | None = Field(None, ge=1, le=120)
    light: LightRequirement
    location_tip: str = Field(..., max_length=500)
    care_notes: str = Field(..., max_length=1500)
    pet_toxicity: PetToxicity
    pet_toxicity_note: str | None = Field(None, max_length=500)
