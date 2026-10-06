"""„Heute“ aus Sicht eines Haushalts.

Der Server läuft in UTC; ein Haushalt lebt in seiner Zeitzone (``households.timezone``,
Default ``Europe/Zurich``). Alles, was ein Kalenderdatum ohne Uhrzeit ableitet
(Monat einer Buchung, Standard-Datum einer Ausgabe, Woche des Menüplans), muss das
Datum des Haushalts verwenden — sonst landet eine Buchung um 00:30 Uhr Schweizer Zeit
am 1. des Monats noch im Vormonat.

Tests patchen ``_utc_now``.
"""

from __future__ import annotations

import uuid
import zoneinfo
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models import Household

DEFAULT_TZ = "Europe/Zurich"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def today_in_timezone(tz_name: str | None) -> date:
    """Heutiges Datum in der gegebenen Zeitzone (None → Default)."""
    return _utc_now().astimezone(zoneinfo.ZoneInfo(tz_name or DEFAULT_TZ)).date()


def household_today(db: Session, household: Household | uuid.UUID) -> date:
    """Heutiges Datum in der Zeitzone des Haushalts (ID oder geladenes Objekt)."""
    if not isinstance(household, Household):
        household = db.get(Household, household)
    return today_in_timezone(household.timezone if household else None)


def first_of_month(day: date) -> date:
    return date(day.year, day.month, 1)
