"""Gemeinsame Regeln der Finanz-Endpunkte (Ausgaben, Ausgleiche, Budget, Rechnungen).

- Betrags- und Datumsgrenzen (CASA-36): Beträge bis 10^9 Rappen (Spalten sind int32),
  Daten höchstens ±10 Jahre um das Haushaltsdatum — 0001-01-01/9999-12-31 führten sonst
  zu 500ern (Monatsrechnung über das Jahr 9999 hinaus) oder zu unsinnigen Buchungen.
- Optimistic Locking per ``If-Match`` (PD-F7).
- "Vor dem letzten Ausgleich" (PD-F2): Eine Ausgabe, die auf oder vor dem letzten Ausgleich
  zwischen zwei ihrer Beteiligten datiert ist, verändert beim Bearbeiten/Löschen bereits
  ausgeglichene Salden nachträglich — die UI warnt dann.
"""

import uuid
from datetime import date
from itertools import combinations

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.error_codes import ErrorCode, error_detail
from app.models import Expense, Settlement

# int32-Spalten: 10^9 Rappen (10 Mio. CHF) lassen genug Abstand zu 2^31
MAX_AMOUNT_RAPPEN = 10**9
DATE_RANGE_YEARS = 10


def first_of_month(d: date) -> date:
    return date(d.year, d.month, 1)


def add_months(month: date, delta: int) -> date:
    """Erster des Monats ``month`` + ``delta`` Monate."""
    index = month.year * 12 + (month.month - 1) + delta
    return date(index // 12, index % 12 + 1, 1)


def _shift_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29. Februar
        return d.replace(year=d.year + years, day=28)


def date_bounds(today: date) -> tuple[date, date]:
    return _shift_years(today, -DATE_RANGE_YEARS), _shift_years(today, DATE_RANGE_YEARS)


def assert_date_in_range(value: date | None, today: date, field: str) -> None:
    """422 DATE_OUT_OF_RANGE, wenn ``value`` mehr als 10 Jahre von heute entfernt ist."""
    if value is None:
        return
    lower, upper = date_bounds(today)
    if not lower <= value <= upper:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.DATE_OUT_OF_RANGE,
                f"{field} must be between {lower.isoformat()} and {upper.isoformat()}",
            ),
        )


def validate_month(month: date, today: date) -> date:
    """Monatsparameter: Erster des Monats und innerhalb von ±10 Jahren (sonst 422 INVALID_MONTH)."""
    lower, upper = date_bounds(today)
    if month.day != 1 or not first_of_month(lower) <= month <= first_of_month(upper):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(
                ErrorCode.INVALID_MONTH,
                "month must be the first day of a month within ±10 years",
            ),
        )
    return month


def parse_if_match(value: str | None) -> int | None:
    """``If-Match: 3`` / ``"3"`` / ``W/"3"`` → 3; fehlender Header → None (keine Prüfung)."""
    if value is None or not value.strip():
        return None
    raw = value.strip()
    if raw.startswith("W/"):
        raw = raw[2:]
    raw = raw.strip('"')
    try:
        return int(raw)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_detail(ErrorCode.EXPENSE_VERSION_CONFLICT, "If-Match must be the entity version"),
        ) from None


# ---------------------------------------------------------------------------
# Letzter Ausgleich pro Personenpaar (PD-F2)
# ---------------------------------------------------------------------------

PairKey = frozenset[uuid.UUID]


def last_settlement_by_pair(db: Session, household_id: uuid.UUID) -> dict[PairKey, date]:
    """Datum des letzten (nicht gelöschten) Ausgleichs je Personenpaar (ungerichtet)."""
    rows = (
        db.query(Settlement.from_user_id, Settlement.to_user_id, func.max(Settlement.settled_date))
        .filter(Settlement.household_id == household_id, Settlement.deleted_at.is_(None))
        .group_by(Settlement.from_user_id, Settlement.to_user_id)
        .all()
    )
    out: dict[PairKey, date] = {}
    for a, b, last in rows:
        key = frozenset((a, b))
        if key not in out or last > out[key]:
            out[key] = last
    return out


def expense_people(expense: Expense) -> set[uuid.UUID]:
    people = {s.user_id for s in expense.shares}
    if expense.paid_by_user_id is not None:
        people.add(expense.paid_by_user_id)
    return people


def is_before_last_settlement(expense: Expense, pairs: dict[PairKey, date]) -> bool:
    """True, wenn zwei Beteiligte der Ausgabe sich am oder nach deren Datum ausgeglichen haben."""
    if not pairs:
        return False
    for a, b in combinations(sorted(expense_people(expense), key=str), 2):
        last = pairs.get(frozenset((a, b)))
        if last is not None and expense.expense_date <= last:
            return True
    return False
