"""Feature 2: Pflegehinweise zu einer Pflanze.

Bewusst unabhängig von einem Plant-Modell: Das Pflanzen-Modul (eigener Branch)
kann ``PlantCareAdvice`` später als Vorbefüllung seiner Pflegeaufgaben nutzen
(Schema in ``docs/ai-assistant.md``).
"""

from __future__ import annotations

from pydantic import ValidationError

from app.services.ai.client import call_structured
from app.services.ai.errors import AiInvalidOutput, AiPlantNotRecognized, AiUsageInfo
from app.services.ai.prompts import PLANT_CARE_SYSTEM, plant_care_user_message
from app.services.ai.schemas import PlantCareAdvice, PlantCareOutput, PlantCareRequest
from app.services.ai.text import clip, clip_or_none, in_range

EFFORT = "low"
MAX_TOKENS = 4000


def to_advice(output: PlantCareOutput, fallback_name: str) -> PlantCareAdvice:
    watering = in_range(output.watering_interval_days, 1, 365)
    if watering is None:
        raise ValueError("Watering interval out of range")
    return PlantCareAdvice(
        plant_name=clip(output.plant_name, 100) or fallback_name[:100],
        botanical_name=clip_or_none(output.botanical_name, 100),
        watering_interval_days=watering,
        fertilizing_interval_days=in_range(output.fertilizing_interval_days, 1, 365),
        repotting_interval_months=in_range(output.repotting_interval_months, 1, 120),
        light=output.light,
        location_tip=clip(output.location_tip, 500),
        care_notes=clip(output.care_notes, 1500),
        pet_toxicity=output.pet_toxicity,
        pet_toxicity_note=clip_or_none(output.pet_toxicity_note, 500),
    )


def get_plant_care(request: PlantCareRequest) -> tuple[PlantCareAdvice, AiUsageInfo]:
    result = call_structured(
        system=PLANT_CARE_SYSTEM[request.locale],
        user_content=plant_care_user_message(request.locale, request.plant, request.location),
        output_model=PlantCareOutput,
        effort=EFFORT,
        max_tokens=MAX_TOKENS,
    )
    if not result.output.recognized:
        raise AiPlantNotRecognized("Input is not a plant", result.usage)
    try:
        advice = to_advice(result.output, request.plant)
    except (ValueError, ValidationError):
        raise AiInvalidOutput("Plant care output not usable", result.usage)
    return advice, result.usage
