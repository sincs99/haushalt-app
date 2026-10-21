"""F0-2 auf PostgreSQL: Zeilensperren und globales DB-Konflikt-Mapping (CASA-24 Safety-Net)."""

import threading
import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.error_codes import ErrorCode
from app.database import SessionLocal
from app.models import Budget, Household
from app.services.locking import lock_household, lock_row
from tests.pg.harness import run_parallel, status_codes


def test_parallel_first_budget_put_never_500(client, household, db):
    """Konkurrierender erster PUT /budget lief in den Unique-Constraint → 500.

    Mit dem globalen Handler: ein Gewinner (201), die übrigen 200 oder 409 CONFLICT_RETRY.
    """

    def put(i):
        return client.put(
            household.url("/budget"),
            json={"month": "2026-03-01", "amount_rappen": 1000 + i},
            headers=household.headers(i % 2),
        )

    results = run_parallel(put, 8)
    codes = status_codes(results)
    assert 500 not in codes, codes
    assert codes.count(201) == 1, codes
    assert set(codes) <= {200, 201, 409}, codes
    for r in results:
        if r.status_code == 409:
            assert r.json()["detail"]["code"] == ErrorCode.CONFLICT_RETRY

    assert db.query(Budget).filter_by(household_id=household.id).count() == 1
    # Nach den Konflikten funktioniert die API normal weiter (Sessions sauber zurückgerollt)
    assert client.get(household.url("/budget?month=2026-03-01"), headers=household.headers()).status_code == 200


def test_lock_household_blocks_second_writer(household):
    """lock_household() hält die households-Zeile bis zum Commit (SELECT … FOR UPDATE)."""
    with SessionLocal() as a, SessionLocal() as b:
        locked = lock_household(a, household.id)
        assert isinstance(locked, Household)

        b.execute(text("SET LOCAL lock_timeout = '200ms'"))
        with pytest.raises(OperationalError) as exc_info:
            lock_household(b, household.id)
        assert exc_info.value.orig.pgcode == "55P03"  # lock_not_available
        b.rollback()

        a.commit()  # gibt die Sperre frei
        assert lock_household(b, household.id).id == household.id
        b.commit()


def test_lock_household_serializes_critical_sections(household):
    """Zwei Transaktionen mit lock_household laufen nacheinander, nicht verschränkt."""
    spans: list[tuple[float, float]] = []
    guard = threading.Lock()

    def work(_i):
        with SessionLocal() as s:
            lock_household(s, household.id)
            start = time.monotonic()
            time.sleep(0.2)
            end = time.monotonic()
            s.commit()
        with guard:
            spans.append((start, end))

    run_parallel(work, 3)
    spans.sort()
    for (_, end_prev), (start_next, _) in zip(spans, spans[1:], strict=False):
        assert start_next >= end_prev - 0.01


def test_lock_row_refreshes_stale_identity_map(household):
    """lock_row() liest die Zeile unter Sperre neu, auch wenn sie schon geladen war."""
    with SessionLocal() as a, SessionLocal() as b:
        h_a = a.get(Household, household.id)
        assert h_a.name.startswith("HH-")
        a.rollback()  # Snapshot beenden, Objekt bleibt in der Identity-Map

        b.get(Household, household.id).name = "Umbenannt"
        b.commit()

        h_a.name  # noqa: B018 — Attribute bewusst geladen lassen
        locked = lock_row(a, Household, household.id)
        assert locked is h_a
        assert locked.name == "Umbenannt"
        a.commit()
