"""Budget ownership and rollback regressions, no provider requests."""

from datetime import date

import pytest

from app.core.config import settings
from app.models import AiBudgetCounter, AiCallReservation, AiUsage
from app.services.ai import usage
from app.services.ai.errors import AiDailyLimitReached, AiUsageInfo


def _count(db, key):
    db.expire_all()
    row = db.query(AiBudgetCounter).filter_by(scope_key=key).one_or_none()
    return row.calls if row else 0


def test_account_budget_spans_households(db, household_a, household_b, user_a, monkeypatch):
    monkeypatch.setattr(settings, "ai_daily_limit_per_user", 1)
    household_a_id, household_b_id, user_id = household_a.id, household_b.id, user_a.id
    usage.reserve_call(db, household_a_id, user_id)
    with pytest.raises(AiDailyLimitReached):
        usage.reserve_call(db, household_b_id, user_id)
    assert _count(db, "global") == 1
    assert _count(db, f"user:{user_id}") == 1
    assert db.query(AiUsage).filter_by(household_id=household_b_id).count() == 0
    assert db.query(AiCallReservation).count() == 1


def test_global_budget_spans_accounts(db, household_a, household_b, user_a, user_b, monkeypatch):
    monkeypatch.setattr(settings, "ai_daily_limit_global", 1)
    usage.reserve_call(db, household_a.id, user_a.id)
    with pytest.raises(AiDailyLimitReached):
        usage.reserve_call(db, household_b.id, user_b.id)
    assert _count(db, "global") == 1
    assert db.query(AiCallReservation).count() == 1


def test_household_limit_failure_rolls_back_aggregate_reservations(
    db, household_a, user_a, monkeypatch,
):
    monkeypatch.setattr(settings, "ai_daily_limit_per_household", 1)
    household_id, user_id = household_a.id, user_a.id
    usage.reserve_call(db, household_id, user_id)
    with pytest.raises(AiDailyLimitReached):
        usage.reserve_call(db, household_id, user_id)
    assert _count(db, "global") == 1
    assert _count(db, f"user:{user_id}") == 1


def test_refund_owned_once_and_original_utc_day(db, household_a, user_a, monkeypatch):
    household_id, user_id = household_a.id, user_a.id
    monkeypatch.setattr(usage, "today_utc", lambda: date(2026, 10, 21))
    first = usage.reserve_call(db, household_id, user_id)
    second = usage.reserve_call(db, household_id, user_id)
    monkeypatch.setattr(usage, "today_utc", lambda: date(2026, 10, 22))
    usage.release_call(db, first)
    usage.release_call(db, first)
    assert _count(db, "global") == 1
    assert _count(db, f"user:{user_id}") == 1
    row = db.query(AiUsage).one()
    assert row.day == date(2026, 10, 21) and row.calls == 1
    assert db.get(AiCallReservation, second).state == "reserved"


def test_completed_call_cannot_be_refunded_or_recorded_twice(db, household_a, user_a):
    reservation = usage.reserve_call(db, household_a.id, user_a.id)
    info = AiUsageInfo(input_tokens=10, output_tokens=20, model="fixture")
    usage.record_tokens(db, reservation, info)
    usage.record_tokens(db, reservation, info)
    usage.release_call(db, reservation)
    assert _count(db, "global") == 1
    row = db.query(AiUsage).one()
    assert (row.calls, row.input_tokens, row.output_tokens) == (1, 10, 20)


@pytest.mark.parametrize("setting", ["ai_daily_limit_global", "ai_daily_limit_per_user"])
def test_disabled_aggregate_budget_cannot_dispatch(db, household_a, user_a, monkeypatch, setting):
    monkeypatch.setattr(settings, setting, 0)
    with pytest.raises(AiDailyLimitReached):
        usage.reserve_call(db, household_a.id, user_a.id)
    assert _count(db, "global") == 0
    assert db.query(AiCallReservation).count() == 0
