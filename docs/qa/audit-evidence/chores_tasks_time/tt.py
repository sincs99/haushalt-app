"""Time travel helper: patches every 'today' source in the chores/tasks/dashboard/attention path."""
import sys
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H

NOW = [None]  # aware UTC datetime

def set_now(dt):
    NOW[0] = dt.astimezone(timezone.utc)

def install():
    import app.services.chore_scheduler as cs, app.routers.chores as rc, app.routers.dashboard as rd
    import app.services.attention as at, app.services.household_time as ht
    def today_in_tz(tz):
        return (NOW[0] or datetime.now(timezone.utc)).astimezone(ZoneInfo(tz)).date()
    cs.today_in_tz = today_in_tz; rc.today_in_tz = today_in_tz; rd.today_in_tz = today_in_tz
    at.household_today = lambda h: today_in_tz(h.timezone or "Europe/Zurich")
    ht._utc_now = lambda: NOW[0] or datetime.now(timezone.utc)
