"""Property-Tests für die reinen Funktionen des Chore-Schedulers (Hypothesis).

Portiert aus ``docs/qa/audit-evidence/chores_tasks_time/prop_scheduler.py``:

- Schrittweise Materialisierung (``from = letzter Termin + 1``) ergibt dieselben
  Termine wie ein einziges grosses Fenster.
- Form der Terminfolge (Abstand, Wochentag, Monatstag geclampet, keine Duplikate,
  erster Termin = anchor_date).
- Rotation: nur Mitglieder, zyklisch in der Reihenfolge der aktiven Personen.
- Startpunkt der Materialisierung nach einer Zeitplanänderung liegt nie vor dem
  neuen anchor_date (CASA-16) und nie vor heute (keine sofort überfälligen Termine).
"""

import calendar
from datetime import date, timedelta
from types import SimpleNamespace as NS

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.routers.chores import _compute_anchor_date
from app.services.chore_scheduler import (
    BACKFILL_DAYS,
    _resolve_next_assignee,
    materialization_start,
    next_due_dates,
)

dates = st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 12, 31))
recurrences = st.sampled_from(["weekly", "biweekly", "monthly"])


def _chore(rec: str, wd: int, dom: int, today: date) -> NS:
    weekday = wd if rec != "monthly" else None
    day_of_month = dom if rec == "monthly" else None
    anchor = _compute_anchor_date(rec, weekday, day_of_month, today)
    return NS(recurrence=rec, weekday=weekday, day_of_month=day_of_month, anchor_date=anchor)


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    rec=recurrences,
    wd=st.integers(0, 6),
    dom=st.integers(1, 31),
    today=dates,
    span=st.integers(0, 400),
    cuts=st.lists(st.integers(1, 60), max_size=10),
)
def test_incremental_equals_oneshot(rec, wd, dom, today, span, cuts):
    """Tageweise/fensterweise materialisieren == ein Fenster (keine Lücken, keine Duplikate)."""
    ch = _chore(rec, wd, dom, today)
    start, end = ch.anchor_date, ch.anchor_date + timedelta(days=span)
    whole = next_due_dates(ch, start, end)

    got: list[date] = []
    horizon = start - timedelta(days=1)
    for c in [*cuts, 10**4]:
        horizon = min(end, horizon + timedelta(days=c))
        from_date = got[-1] + timedelta(days=1) if got else start
        got += next_due_dates(ch, from_date, horizon)
        if horizon >= end:
            break
    assert got == whole

    for a, b in zip(whole, whole[1:], strict=False):
        if rec == "weekly":
            assert (b - a).days == 7
        elif rec == "biweekly":
            assert (b - a).days == 14
        else:
            assert (b.year * 12 + b.month) - (a.year * 12 + a.month) == 1
    for d in whole:
        if rec == "monthly":
            assert d.day == min(dom, calendar.monthrange(d.year, d.month)[1])
        else:
            assert d.weekday() == wd
    assert len(set(whole)) == len(whole)
    if whole:
        assert whole[0] == ch.anchor_date  # anchor ist der erste Termin


@settings(max_examples=400, deadline=None)
@given(
    rot=st.lists(st.uuids().map(str), min_size=1, max_size=6, unique=True),
    members_mask=st.lists(st.booleans(), min_size=6, max_size=6),
    idx=st.integers(0, 50),
    n=st.integers(1, 30),
)
def test_rotation_round_robin(rot, members_mask, idx, n):
    members = {u for u, m in zip(rot, members_mask, strict=False) if m}
    ch = NS(rotation_order=rot, next_rotation_index=idx)
    seq = [_resolve_next_assignee(ch, members) for _ in range(n)]
    active = [u for u in rot if u in members]
    if not active:
        assert all(s is None for s in seq)
        return
    strs = [str(s) for s in seq]
    assert all(s in members for s in strs)
    for a, b in zip(strs, strs[1:], strict=False):
        assert b == active[(active.index(a) + 1) % len(active)]


@settings(max_examples=400, deadline=None)
@given(
    rec=recurrences,
    wd=st.integers(0, 6),
    dom=st.integers(1, 31),
    today=dates,
    last_offset=st.one_of(st.none(), st.integers(-200, 30)),
)
def test_start_after_schedule_change_never_before_anchor_or_today(rec, wd, dom, today, last_offset):
    """Nach einer Änderung (anchor ab heute neu berechnet) entsteht kein überfälliger Termin."""
    ch = _chore(rec, wd, dom, today)
    last = today + timedelta(days=last_offset) if last_offset is not None else None
    start = materialization_start(last, ch.anchor_date, today)
    assert start >= ch.anchor_date >= today
    assert start >= today - timedelta(days=BACKFILL_DAYS)
    if last is not None:
        assert start > last
    produced = next_due_dates(ch, start, today + timedelta(days=7))
    assert all(d >= today for d in produced)


@settings(max_examples=300, deadline=None)
@given(anchor=dates, today=dates, last=st.one_of(st.none(), dates))
def test_start_respects_backfill_limit(anchor, today, last):
    start = materialization_start(last, anchor, today)
    assert start >= today - timedelta(days=BACKFILL_DAYS)
    assert start >= anchor
    if last is not None:
        assert start > last
