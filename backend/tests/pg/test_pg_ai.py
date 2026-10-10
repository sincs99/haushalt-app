"""KI-Tageslimit unter Parallelität (CASA-32, PD-A2).

Der Anthropic-Client ist gemockt; geprüft wird nur die Reservierung in ``ai_usage`` /
``ai_user_usage`` mit echten, gleichzeitigen Sessions.
"""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import AiUsage, AiUserUsage, Household
from app.services.ai import client as ai_client
from app.services.ai.schemas import LightRequirement, PetToxicity, PlantCareOutput
from tests.pg.harness import add_member, run_parallel, status_codes


def _plant_response():
    output = PlantCareOutput(
        recognized=True,
        plant_name="Ficus",
        botanical_name="Ficus benjamina",
        watering_interval_days=7,
        fertilizing_interval_days=14,
        repotting_interval_months=24,
        light=LightRequirement.bright_indirect,
        location_tip="Hell.",
        care_notes="Nicht umstellen.",
        pet_toxicity=PetToxicity.toxic,
        pet_toxicity_note="Giftig.",
    )
    return SimpleNamespace(
        stop_reason="end_turn",
        stop_details=None,
        parsed_output=output,
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
        model="claude-opus-5-5",
    )


@pytest.fixture()
def fake_ai(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(ai_client, "_slots", threading.BoundedSemaphore(50))
    fake = MagicMock()
    fake.beta.messages.parse.return_value = _plant_response()
    with patch.object(ai_client, "get_client", return_value=fake):
        yield fake


def _enable_ai(db, household_id):
    db.get(Household, household_id).ai_enabled = True
    db.commit()


def _calls(db, model, **filters):
    db.expire_all()
    row = db.execute(select(model).filter_by(**filters)).scalar_one_or_none()
    return row.calls if row else 0


def test_parallel_first_requests_below_limit_never_429(client, db, make_household, fake_ai, monkeypatch):
    """CASA-32: die ersten parallelen Anfragen des Tages bekamen 429, obwohl 5 von 50 belegt waren."""
    monkeypatch.setattr(settings, "ai_daily_limit_per_household", 50)
    monkeypatch.setattr(settings, "ai_daily_limit_per_user", 50)
    for _ in range(3):
        hh = make_household(["Anna", "Ben"])
        _enable_ai(db, hh.id)

        def call(i, hh=hh):
            return client.post(
                hh.url("/ai/plant-care"), json={"plant": "Ficus"}, headers=hh.headers(i % 2)
            )

        assert status_codes(run_parallel(call, 10)) == [200] * 10
        assert _calls(db, AiUsage, household_id=hh.id) == 10


def test_parallel_requests_never_exceed_household_limit(client, db, make_household, fake_ai, monkeypatch):
    monkeypatch.setattr(settings, "ai_daily_limit_per_household", 3)
    monkeypatch.setattr(settings, "ai_daily_limit_per_user", 50)
    hh = make_household(["Anna", "Ben"])
    _enable_ai(db, hh.id)

    def call(i):
        return client.post(hh.url("/ai/plant-care"), json={"plant": "Ficus"}, headers=hh.headers(i % 2))

    codes = status_codes(run_parallel(call, 10))
    assert sorted(codes) == [200] * 3 + [429] * 7
    assert _calls(db, AiUsage, household_id=hh.id) == 3
    assert fake_ai.beta.messages.parse.call_count == 3


def test_parallel_requests_never_exceed_user_limit(client, db, make_household, fake_ai, monkeypatch):
    """PD-A2: persönliches Limit hält auch parallel; abgelehnte Aufrufe belasten den Haushalt nicht."""
    monkeypatch.setattr(settings, "ai_daily_limit_per_household", 50)
    monkeypatch.setattr(settings, "ai_daily_limit_per_user", 2)
    hh = make_household(["Anna"])
    add_member(hh, "Ben")
    _enable_ai(db, hh.id)

    def call(i):
        return client.post(hh.url("/ai/plant-care"), json={"plant": "Ficus"}, headers=hh.headers(0))

    results = run_parallel(call, 8)
    assert sorted(status_codes(results)) == [200] * 2 + [429] * 6
    assert {r.json()["detail"]["code"] for r in results if r.status_code == 429} == {
        "AI_USER_DAILY_LIMIT_REACHED"
    }
    assert _calls(db, AiUserUsage, user_id=hh.user_ids[0]) == 2
    assert _calls(db, AiUsage, household_id=hh.id) == 2
