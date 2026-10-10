"""Menüplan auf PostgreSQL: parallele Schreibzugriffe auf denselben Tag (CASA-19c, CASA-24)."""

import uuid
from datetime import date

from app.models import EventPoll, MealPlanEntry
from tests.pg.harness import run_parallel, status_codes


def test_parallel_put_same_day_never_500(client, household, db):
    def put(i):
        return client.put(
            household.url("/meal-plan/2026-10-17"),
            json={"free_text": f"Essen {i}"},
            headers=household.headers(i % 2),
        )

    codes = status_codes(run_parallel(put, 6))
    assert 500 not in codes, codes
    assert set(codes) == {200}, codes
    assert db.query(MealPlanEntry).filter_by(household_id=household.id).count() == 1


def test_meal_decide_vs_put_same_day(client, make_household, db):
    """Entscheiden ‖ PUT auf denselben leeren Tag: nie 500, Abstimmung nie 'entschieden' ohne Eintrag."""
    for _ in range(5):
        hh = make_household(["Anna", "Ben"])
        poll = client.post(
            hh.url("/polls/"),
            json={"question": "?", "poll_type": "meal", "meal_date": "2026-10-17",
                  "options": [{"label": "Zopf"}, {"label": "Pasta"}]},
            headers=hh.headers(),
        ).json()

        def act(i, hh=hh, poll=poll):
            if i == 0:
                return client.post(
                    hh.url(f"/polls/{poll['id']}/meal-decide"),
                    json={"option_id": poll["options"][0]["id"]},
                    headers=hh.headers(0),
                )
            return client.put(hh.url("/meal-plan/2026-10-17"), json={"free_text": "Fondue"}, headers=hh.headers(1))

        codes = status_codes(run_parallel(act, 2))
        assert 500 not in codes, codes
        assert codes[1] == 200, codes
        db.expire_all()
        stored = db.get(EventPoll, uuid.UUID(poll["id"]))
        entries = db.query(MealPlanEntry).filter_by(household_id=hh.id, date=date(2026, 10, 17)).all()
        assert len(entries) == 1
        if codes[0] == 200:
            assert stored.status == "entschieden"
        else:
            assert codes[0] == 409, codes
            assert stored.status == "offen"
