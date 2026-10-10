"""
Zeitbehandlung für Kalender-Termine.

Uhrzeiten gelten als Wanduhrzeit in der Zeitzone des Haushalts: "09:00" ist für
alle Mitglieder 09:00, unabhängig von der Zeitzone ihres Geräts. Gespeichert wird
UTC; ausgeliefert wird mit dem Offset des Haushalts (z.B. 2026-10-07T09:00:00+02:00),
damit das Frontend Datum und Uhrzeit direkt aus dem String lesen kann.

Sommerzeit (CASA-35, PD-K4): Eine Wanduhrzeit in der Lücke der Umstellung
(z.B. 29.03.2026 02:30 in Zürich) existiert nicht → ``wall_time_to_utc`` lehnt sie
mit 422 ``EVENT_TIME_NONEXISTENT`` ab, statt still eine Stunde zu verschieben.
Eine doppelte Wanduhrzeit (Rückstellung, 25.10.2026 02:30) wird bewusst als das
ERSTE Auftreten (noch Sommerzeit, fold=0) gelesen.
"""

import zoneinfo
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, func

from app.core.error_codes import ErrorCode, error_detail
from app.models import Event

DEFAULT_TZ = "Europe/Zurich"


def household_tz(tz_name: str | None) -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(tz_name or DEFAULT_TZ)


def to_utc(dt: datetime, tz: zoneinfo.ZoneInfo) -> datetime:
    """Eingabe → UTC. Ohne Offset wird die Zeit als Wanduhrzeit des Haushalts gelesen."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


def is_nonexistent_wall_time(dt: datetime, tz: zoneinfo.ZoneInfo) -> bool:
    """True, wenn die naive Wanduhrzeit in tz wegen Sommerzeit-Umstellung nicht existiert."""
    if dt.tzinfo is not None:
        return False
    round_trip = dt.replace(tzinfo=tz).astimezone(timezone.utc).astimezone(tz)
    return round_trip.replace(tzinfo=None) != dt


def wall_time_to_utc(dt: datetime, tz: zoneinfo.ZoneInfo) -> datetime:
    """Wie ``to_utc`` für Benutzereingaben: nicht existierende Wanduhrzeit → 422."""
    if is_nonexistent_wall_time(dt, tz):
        raise HTTPException(
            status_code=422,
            detail=error_detail(
                ErrorCode.EVENT_TIME_NONEXISTENT,
                f"{dt.isoformat()} does not exist in {tz.key} (daylight saving time change)",
            ),
        )
    return to_utc(dt, tz)


def to_household_time(dt: datetime | None, tz: zoneinfo.ZoneInfo) -> datetime | None:
    """Gespeicherter Wert → Haushaltszeit. Naive Werte (SQLite) sind UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def range_bounds(
    from_value: date | datetime, to_value: date | datetime, tz: zoneinfo.ZoneInfo
) -> tuple[datetime, datetime]:
    """Abfragebereich als [start, end) in UTC.

    Ein reines Datum als Ende zählt als ganzer Tag (bis Mitternacht des Folgetags),
    sonst fehlen Termine am letzten Tag des Bereichs.
    """
    if isinstance(from_value, datetime):
        start = to_utc(from_value, tz)
    else:
        start = to_utc(datetime.combine(from_value, time.min), tz)
    if isinstance(to_value, datetime):
        end = to_utc(to_value, tz)
    else:
        end = to_utc(datetime.combine(to_value + timedelta(days=1), time.min), tz)
    return start, end


def all_day_start_utc(day: date, tz: zoneinfo.ZoneInfo) -> datetime:
    """Beginn eines ganztägigen Termins (00:00 Haushaltszeit) in UTC."""
    return to_utc(datetime.combine(day, time.min), tz)


def overlaps_range(start: datetime, end: datetime):
    """SQL-Filter: Termin überschneidet [start, end) — auch mehrtägige, die vorher
    beginnen und hineinreichen. Gleiche Regel für Kalender, Dashboard und Widget (PD-K3)."""
    return and_(
        Event.starts_at < end,
        func.coalesce(Event.ends_at, Event.starts_at) >= start,
    )


def on_day(day: date, tz: zoneinfo.ZoneInfo):
    """SQL-Filter: Termin findet (auch teilweise) am Haushaltstag ``day`` statt."""
    return overlaps_range(*range_bounds(day, day, tz))


# Erinnerungen (PD-K1): Vorlauf bei Terminen mit Uhrzeit; ganztägige um 08:00
# Haushaltszeit am Tag selbst bzw. am Vortag (1d)
REMINDER_OFFSETS = {"15m": timedelta(minutes=15), "1h": timedelta(hours=1), "1d": timedelta(days=1)}
ALL_DAY_REMINDER_TIME = time(8, 0)


def event_remind_at(
    starts_at: datetime, all_day: bool, reminder: str, tz: zoneinfo.ZoneInfo
) -> datetime | None:
    """Zeitpunkt (UTC) der Erinnerung eines Termins; None = keine Erinnerung."""
    if reminder not in REMINDER_OFFSETS:
        return None
    if all_day:
        day = to_household_time(starts_at, tz).date()
        if reminder == "1d":
            day -= timedelta(days=1)
        return to_utc(datetime.combine(day, ALL_DAY_REMINDER_TIME), tz)
    return to_household_time(starts_at, timezone.utc) - REMINDER_OFFSETS[reminder]
