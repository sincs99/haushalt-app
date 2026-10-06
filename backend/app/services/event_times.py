"""
Zeitbehandlung für Kalender-Termine.

Uhrzeiten gelten als Wanduhrzeit in der Zeitzone des Haushalts: "09:00" ist für
alle Mitglieder 09:00, unabhängig von der Zeitzone ihres Geräts. Gespeichert wird
UTC; ausgeliefert wird mit dem Offset des Haushalts (z.B. 2026-10-07T09:00:00+02:00),
damit das Frontend Datum und Uhrzeit direkt aus dem String lesen kann.
"""

import zoneinfo
from datetime import date, datetime, time, timedelta, timezone

DEFAULT_TZ = "Europe/Zurich"


def household_tz(tz_name: str | None) -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(tz_name or DEFAULT_TZ)


def to_utc(dt: datetime, tz: zoneinfo.ZoneInfo) -> datetime:
    """Eingabe → UTC. Ohne Offset wird die Zeit als Wanduhrzeit des Haushalts gelesen."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(timezone.utc)


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
