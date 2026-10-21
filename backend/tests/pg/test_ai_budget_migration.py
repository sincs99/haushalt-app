"""Global-budget migration preserves existing plan/account usage history."""

import uuid
from datetime import date

from sqlalchemy import create_engine, text

from tests.pg.harness import fresh_database, run_alembic


def test_global_budget_backfill_preserves_account_history_and_does_not_double_count(pg_admin_url):
    with fresh_database(pg_admin_url, upgrade_to="mas1a2b3c4d5") as url:
        engine = create_engine(url)
        try:
            household_id, user_id = uuid.uuid4(), uuid.uuid4()
            days = [date(2026, 10, day) for day in (19, 20, 21)]
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO households (id, name, invite_code, created_at) "
                    "VALUES (:id, 'Fixture', :invite, now())"
                ), {"id": household_id, "invite": uuid.uuid4().hex[:12]})
                connection.execute(text(
                    "INSERT INTO users (id, email, password_hash, display_name, created_at) "
                    "VALUES (:id, 'fixture@example.invalid', 'fixture', 'Fixture', now())"
                ), {"id": user_id})
                for day, calls in zip(days[:2], (3, 9), strict=True):
                    connection.execute(text(
                        "INSERT INTO ai_usage (id, household_id, day, calls) VALUES (:id, :hh, :day, :calls)"
                    ), {"id": uuid.uuid4(), "hh": household_id, "day": day, "calls": calls})
                for day, calls in zip(days, (7, 4, 2), strict=True):
                    connection.execute(text(
                        "INSERT INTO ai_user_usage (id, user_id, day, calls) VALUES (:id, :user, :day, :calls)"
                    ), {"id": uuid.uuid4(), "user": user_id, "day": day, "calls": calls})

            for _ in range(2):
                run_alembic(url, "upgrade", "b4c5d6e7f8a9")
                with engine.connect() as connection:
                    global_calls = connection.execute(text(
                        "SELECT day, calls FROM ai_budget_counters WHERE scope_key = 'global' ORDER BY day"
                    )).all()
                    account_calls = connection.execute(text(
                        "SELECT day, calls FROM ai_user_usage WHERE user_id = :user ORDER BY day"
                    ), {"user": user_id}).all()
                assert global_calls == list(zip(days, (7, 9, 2), strict=True))
                assert account_calls == list(zip(days, (7, 4, 2), strict=True))
                run_alembic(url, "downgrade", "mas1a2b3c4d5")
        finally:
            engine.dispose()
