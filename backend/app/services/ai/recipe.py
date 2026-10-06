"""Feature 1: Rezept aus vorhandenen Zutaten vorschlagen.

Der Vorschlag wird nicht gespeichert. ``RecipeSuggestionResponse.recipe`` hat die
Felder von ``RecipeCreate``; das Frontend schickt ihn nach Prüfung an den
bestehenden Rezept-Endpunkt.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.routers.food import MAX_STEP_LENGTH, MAX_TAG_LENGTH, RecipeCreate
from app.services.ai.client import call_structured
from app.services.ai.errors import AiInvalidOutput, AiUsageInfo
from app.services.ai.prompts import RECIPE_SYSTEM, recipe_user_message
from app.services.ai.schemas import (
    IngredientOutput,
    RecipeOutput,
    RecipeSuggestionRequest,
    RecipeSuggestionResponse,
    ShoppingSuggestion,
)
from app.services.ai.text import clip, clip_or_none, in_range

EFFORT = "medium"
# Denken zählt bei Opus 5.5 zu max_tokens — Luft lassen, abgerechnet wird nur Genutztes
MAX_TOKENS = 8000


def _ingredient_line(item: IngredientOutput) -> str:
    quantity = clip(item.quantity, 50)
    name = clip(item.name, 150)
    return clip(f"{quantity} {name}" if quantity else name, 200)


def to_suggestion(output: RecipeOutput, requested_servings: int) -> RecipeSuggestionResponse:
    """Modell-Ausgabe → App-Schema. Wirft ``ValueError``/``ValidationError`` bei Unbrauchbarem."""
    ingredients = [_ingredient_line(i) for i in output.ingredients if clip(i.name, 150)][:100]
    steps = [clip(s, MAX_STEP_LENGTH) for s in output.steps if clip(s, MAX_STEP_LENGTH)][:30]
    if not ingredients or not steps:
        raise ValueError("Recipe without ingredients or steps")

    tags = list(dict.fromkeys(t for t in (clip(t, MAX_TAG_LENGTH) for t in output.tags) if t))[:10]
    missing = [
        ShoppingSuggestion(name=clip(m.name, 200), quantity=clip_or_none(m.quantity, 50))
        for m in output.missing_ingredients
        if clip(m.name, 200)
    ][:30]

    recipe = RecipeCreate(
        name=clip(output.name, 150),
        servings=in_range(output.servings, 1, 50) or requested_servings,
        duration_min=in_range(output.duration_min, 1, 1440),
        ingredients=ingredients,
        steps=steps,
        tags=tags,
    )
    return RecipeSuggestionResponse(
        recipe=recipe,
        missing_ingredients=missing,
        tip=clip_or_none(output.tip, 300),
    )


def generate_recipe(request: RecipeSuggestionRequest) -> tuple[RecipeSuggestionResponse, AiUsageInfo]:
    result = call_structured(
        system=RECIPE_SYSTEM[request.locale],
        user_content=recipe_user_message(
            request.locale,
            request.ingredients,
            request.servings,
            request.preferences,
            request.note,
        ),
        output_model=RecipeOutput,
        effort=EFFORT,
        max_tokens=MAX_TOKENS,
    )
    try:
        suggestion = to_suggestion(result.output, request.servings)
    except (ValueError, ValidationError):
        raise AiInvalidOutput("Recipe output not usable", result.usage)
    return suggestion, result.usage
