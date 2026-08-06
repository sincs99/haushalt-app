"""
Chore-Scheduler – Lazy Materialisierung von ChoreAssignments.

Reine Funktionen für Datumsberechnung + eine DB-gebundene Funktion
für die Materialisierung.  Keine externen Pakete nötig (nur stdlib + SQLAlchemy).
"""

from __future__ import annotations

import calendar
import uuid as uuid_mod
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# 1) Zeitzone-Helper
# ---------------------------------------------------------------------------

def today_in_tz(tz_name: str) -> date:
    """Gibt das aktuelle Datum in der gegebenen Zeitzone zurück."""
    return datetime.now(ZoneInfo(tz_name)).date()


# ---------------------------------------------------------------------------
# 2) Fälligkeitstermine berechnen
# ---------------------------------------------------------------------------

def next_due_dates(chore, from_date: date, until_date: date) -> list[date]:
    """
    Berechnet alle fälligen Termine im Fenster ``[from_date, until_date]``
    (inklusive beider Grenzen).

    Unterstützte Recurrence-Werte:
    - ``"weekly"``   → jeder passende Wochentag im Fenster
    - ``"biweekly"`` → wie weekly, aber nur in geraden Wochen relativ zu anchor_date
    - ``"monthly"``  → der day_of_month pro Monat (geclampet auf Monatslänge)
    """
    if from_date > until_date:
        return []

    recurrence: str = chore.recurrence
    dates: list[date] = []

    if recurrence in ("weekly", "biweekly"):
        dates = _weekly_dates(chore, from_date, until_date, biweekly=(recurrence == "biweekly"))
    elif recurrence == "monthly":
        dates = _monthly_dates(chore, from_date, until_date)

    dates.sort()
    return dates


def _weekly_dates(
    chore,
    from_date: date,
    until_date: date,
    *,
    biweekly: bool,
) -> list[date]:
    """Alle passenden Wochentage im Fenster (optional biweekly-Filter)."""
    target_weekday: int = chore.weekday  # 0=Mo..6=So
    anchor: date = chore.anchor_date

    # Ersten passenden Wochentag im Fenster finden
    days_ahead = (target_weekday - from_date.weekday()) % 7
    cursor = from_date + timedelta(days=days_ahead)

    results: list[date] = []
    while cursor <= until_date:
        if biweekly:
            days_diff = (cursor - anchor).days
            week_diff = days_diff // 7
            if week_diff % 2 == 0:
                results.append(cursor)
        else:
            results.append(cursor)
        cursor += timedelta(days=7)

    return results


def _monthly_dates(chore, from_date: date, until_date: date) -> list[date]:
    """Pro Monat im Fenster den day_of_month (geclampet)."""
    dom: int = chore.day_of_month
    results: list[date] = []

    year, month = from_date.year, from_date.month
    while True:
        last_day = calendar.monthrange(year, month)[1]
        actual_day = min(dom, last_day)
        candidate = date(year, month, actual_day)

        if candidate > until_date:
            break
        if candidate >= from_date:
            results.append(candidate)

        # Nächsten Monat
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    return results


# ---------------------------------------------------------------------------
# 3) Rotation – nächsten zuständigen User bestimmen
# ---------------------------------------------------------------------------

def _resolve_next_assignee(
    chore,
    member_ids: set[str],
) -> uuid_mod.UUID | None:
    """
    Bestimmt den nächsten zugewiesenen User aus der Rotation.

    - Überspringe User, die keine Mitglieder mehr sind
      (Index rückt trotzdem weiter).
    - Bei leerer effektiver Rotation → ``None``.
    - Inkrementiert ``chore.next_rotation_index`` (wird beim Commit persistiert).
    """
    rotation: list[str] = chore.rotation_order
    if not rotation:
        return None

    max_attempts = len(rotation)
    assigned: uuid_mod.UUID | None = None

    for _ in range(max_attempts):
        idx = chore.next_rotation_index % len(rotation)
        chore.next_rotation_index += 1
        candidate = rotation[idx]
        if candidate in member_ids:
            assigned = uuid_mod.UUID(candidate)
            break

    return assigned


# ---------------------------------------------------------------------------
# 4) Lazy Materialisierung
# ---------------------------------------------------------------------------

def materialize_due_assignments(db: Session, household) -> list:
    """
    Erzeugt fällige ``ChoreAssignment``-Einträge für alle aktiven Chores
    eines Households per Lazy-Materialisierung (Vorschau: 7 Tage).

    Race-Conditions werden über ``begin_nested()``-Savepoints abgefangen:
    bei einem ``IntegrityError`` (Duplikat auf ``(chore_id, due_date)``)
    wird nur der Savepoint zurückgerollt, nicht die gesamte Transaktion.
    """
    from app.models import Chore, ChoreAssignment, HouseholdMember

    today = today_in_tz(household.timezone)
    horizon = today + timedelta(days=7)

    # Aktuelle Mitglieder-IDs des Households
    member_ids: set[str] = {
        str(m.user_id)
        for m in db.query(HouseholdMember.user_id)
        .filter(HouseholdMember.household_id == household.id)
        .all()
    }

    # Aktive Chores laden
    chores = (
        db.query(Chore)
        .filter(Chore.household_id == household.id, Chore.active == True)  # noqa: E712
        .with_for_update()
        .all()
    )

    new_assignments: list[ChoreAssignment] = []

    for chore in chores:
        # Letztes materialisiertes Datum (oder anchor_date als Startpunkt)
        last_assignment = (
            db.query(ChoreAssignment.due_date)
            .filter(ChoreAssignment.chore_id == chore.id)
            .order_by(ChoreAssignment.due_date.desc())
            .first()
        )

        if last_assignment:
            from_date = last_assignment.due_date + timedelta(days=1)
        else:
            from_date = chore.anchor_date

        # Backfill-Limit – maximal 14 Tage in die Vergangenheit
        backfill_limit = today - timedelta(days=14)
        from_date = max(from_date, backfill_limit)

        if from_date > horizon:
            continue

        due_dates = next_due_dates(chore, from_date, horizon)

        for dd in due_dates:
            assigned_user_id = _resolve_next_assignee(chore, member_ids)

            assignment = ChoreAssignment(
                household_id=household.id,
                chore_id=chore.id,
                assigned_user_id=assigned_user_id,
                due_date=dd,
            )

            # Savepoint für Race-Condition-Safety
            try:
                nested = db.begin_nested()  # noqa: F841
                db.add(assignment)
                db.flush()
                new_assignments.append(assignment)
            except IntegrityError:
                nested.rollback()
                # Duplikat (paralleler Request) → überspringen
                continue

    if new_assignments:
        db.commit()

    return new_assignments
