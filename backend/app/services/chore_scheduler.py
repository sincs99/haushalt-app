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

# Vorschau: so viele Tage im Voraus werden Zuweisungen angelegt
HORIZON_DAYS = 7
# Backfill: höchstens so viele Tage in die Vergangenheit nachholen
BACKFILL_DAYS = 14


def materialization_start(last_due: date | None, anchor: date, today: date) -> date:
    """Erster Tag, ab dem neue Termine materialisiert werden.

    Nie vor dem ``anchor_date`` (nach einer Zeitplanänderung liegt er ab heute —
    sonst entstünde ein sofort überfälliger Termin nach altem Muster, CASA-16),
    nie vor dem Backfill-Limit und immer nach dem letzten relevanten Termin.
    """
    start = max(anchor, today - timedelta(days=BACKFILL_DAYS))
    if last_due is not None:
        start = max(start, last_due + timedelta(days=1))
    return start


def materialize_due_assignments(db: Session, household) -> list:
    """
    Erzeugt fällige ``ChoreAssignment``-Einträge für alle aktiven Chores
    eines Households per Lazy-Materialisierung (Vorschau: 7 Tage).

    Fortgesetzt wird nach dem letzten Termin, der offen ist oder bis heute fällig
    war. Ein vorzeitig erledigter KÜNFTIGER Termin blockiert den Zeitplan nicht
    (CASA-51: nach einer Zeitplanänderung bliebe sonst eine Periode leer); bereits
    vorhandene Daten werden übersprungen, ohne einen Rotationsplatz zu verbrauchen.

    Race-Conditions: Die Chores werden ``FOR UPDATE`` gesperrt (PostgreSQL);
    zusätzlich fängt ein ``begin_nested()``-Savepoint einen ``IntegrityError``
    (Duplikat auf ``(chore_id, due_date)``) ab, ohne die Transaktion zu verlieren.
    """
    from sqlalchemy import or_

    from app.models import Chore, ChoreAssignment, HouseholdMember

    today = today_in_tz(household.timezone)
    horizon = today + timedelta(days=HORIZON_DAYS)

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
        # Letzter relevanter Termin: offen oder bis heute fällig (vorzeitig erledigte
        # künftige Termine zählen nicht, siehe Docstring)
        last_due = (
            db.query(ChoreAssignment.due_date)
            .filter(
                ChoreAssignment.chore_id == chore.id,
                or_(
                    ChoreAssignment.completed_at.is_(None),
                    ChoreAssignment.due_date <= today,
                ),
            )
            .order_by(ChoreAssignment.due_date.desc())
            .limit(1)
            .scalar()
        )
        from_date = materialization_start(last_due, chore.anchor_date, today)
        if from_date > horizon:
            continue

        due_dates = next_due_dates(chore, from_date, horizon)
        if not due_dates:
            continue

        # Schon vorhandene Termine (z. B. vorzeitig erledigt) nicht doppelt anlegen
        existing = {
            row.due_date
            for row in db.query(ChoreAssignment.due_date).filter(
                ChoreAssignment.chore_id == chore.id,
                ChoreAssignment.due_date >= due_dates[0],
                ChoreAssignment.due_date <= due_dates[-1],
            )
        }

        for dd in due_dates:
            if dd in existing:
                continue
            rotation_index_before = chore.next_rotation_index
            assigned_user_id = _resolve_next_assignee(chore, member_ids)

            assignment = ChoreAssignment(
                household_id=household.id,
                chore_id=chore.id,
                assigned_user_id=assigned_user_id,
                due_date=dd,
            )

            # Savepoint für Race-Condition-Safety
            nested = db.begin_nested()
            try:
                db.add(assignment)
                db.flush()
                nested.commit()
                new_assignments.append(assignment)
            except IntegrityError:
                nested.rollback()
                # Duplikat (paralleler Request) → überspringen, Rotationsplatz zurückgeben
                chore.next_rotation_index = rotation_index_before
                continue

    if new_assignments:
        db.commit()

    return new_assignments


def emit_assignments_created(household_id, assignments: list) -> None:
    """``chore_assignment_created`` für frisch materialisierte Zuweisungen (CASA-46).

    Gilt für jeden Materialisierungspfad (Putzplan, Tag-Scan, Push-Scheduler,
    Zeitplanänderung) — sonst sehen offene Clients neue Termine erst nach einem Reload.
    """
    if not assignments:
        return
    # Modul-Attribut statt Direktimport: Tests ersetzen emit_to_household_sync
    import app.socket_manager as socket_manager
    from app.routers.chores import ChoreAssignmentResponse

    for a in assignments:
        socket_manager.emit_to_household_sync(
            household_id,
            "chore_assignment_created",
            ChoreAssignmentResponse.model_validate(a).model_dump(mode="json"),
        )


def materialize_and_emit(db: Session, household) -> list:
    """Materialisieren + Socket-Events — der Standardweg für alle Aufrufer."""
    new_assignments = materialize_due_assignments(db, household)
    for a in new_assignments:
        db.refresh(a)
    emit_assignments_created(household.id, new_assignments)
    return new_assignments
