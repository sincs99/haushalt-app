"""Property tests against the real chore_scheduler pure functions (no DB)."""
import sys; sys.path.insert(0, "/home/user/haushalt-app/backend")
from datetime import date, timedelta
from types import SimpleNamespace as NS
import calendar
from hypothesis import given, settings, strategies as st, HealthCheck
from app.services.chore_scheduler import next_due_dates, _resolve_next_assignee
from app.routers.chores import _compute_anchor_date

dates = st.dates(min_value=date(2020,1,1), max_value=date(2035,12,31))

def mk(rec, wd=None, dom=None, today=None):
    anchor = _compute_anchor_date(rec, wd, dom, today)
    return NS(recurrence=rec, weekday=wd, day_of_month=dom, anchor_date=anchor)

@settings(max_examples=3000, suppress_health_check=[HealthCheck.too_slow])
@given(rec=st.sampled_from(["weekly","biweekly","monthly"]), wd=st.integers(0,6), dom=st.integers(1,31),
       today=dates, span=st.integers(0,400), cuts=st.lists(st.integers(1,60), max_size=10))
def test_incremental_equals_oneshot(rec, wd, dom, today, span, cuts):
    """Materialising day-by-day (from=last+1) must yield the same dates as one window."""
    ch = mk(rec, wd, dom, today)
    start, end = ch.anchor_date, ch.anchor_date + timedelta(days=span)
    whole = next_due_dates(ch, start, end)
    got, cur = [], start
    for c in cuts + [10**6]:
        stop = min(end, cur + timedelta(days=c))
        got += next_due_dates(ch, cur, stop)
        cur = (got[-1] + timedelta(days=1)) if got else cur
        cur = max(cur, stop + timedelta(days=1)) if not got or got[-1] < stop else cur
        if cur > end: break
    assert got == whole, (got, whole)
    # shape properties
    for a, b in zip(whole, whole[1:]):
        if rec == "weekly": assert (b-a).days == 7
        if rec == "biweekly": assert (b-a).days == 14
        if rec == "monthly": assert (b.year*12+b.month) - (a.year*12+a.month) == 1
    for d in whole:
        if rec != "monthly": assert d.weekday() == wd
        else: assert d.day == min(dom, calendar.monthrange(d.year, d.month)[1])
    assert len(set(whole)) == len(whole)
    if whole: assert whole[0] == ch.anchor_date  # anchor is first due date

@settings(max_examples=2000)
@given(rot=st.lists(st.uuids().map(str), min_size=1, max_size=6, unique=True), members_mask=st.lists(st.booleans(), min_size=6, max_size=6), idx=st.integers(0, 50), n=st.integers(1, 30))
def test_rotation_round_robin(rot, members_mask, idx, n):
    members = {u for u, m in zip(rot, members_mask) if m}
    ch = NS(rotation_order=rot, next_rotation_index=idx)
    seq = [_resolve_next_assignee(ch, members) for _ in range(n)]
    active = [u for u in rot if u in members]
    if not active:
        assert all(s is None for s in seq); return
    # every assignee is a member and consecutive assignees follow the active cyclic order
    strs = [str(s) for s in seq]
    assert all(s in members for s in strs)
    for a, b in zip(strs, strs[1:]):
        i = active.index(a); assert b == active[(i+1) % len(active)]

def test_specific_edges():
    # Dec 31 -> Jan 1 weekly; Feb 29 leap; DST irrelevant for dates
    ch = NS(recurrence="monthly", weekday=None, day_of_month=31, anchor_date=date(2027,12,31))
    print("monthly31 2027-12..2028-03:", next_due_dates(ch, date(2027,12,1), date(2028,3,31)))
    ch = NS(recurrence="monthly", weekday=None, day_of_month=29, anchor_date=date(2026,1,29))
    print("monthly29 2027 Feb / 2028 Feb:", next_due_dates(ch, date(2027,2,1), date(2027,3,1)), next_due_dates(ch, date(2028,2,1), date(2028,3,1)))
    ch = NS(recurrence="biweekly", weekday=4, day_of_month=None, anchor_date=date(2026,12,25))
    print("biweekly Fri over new year:", next_due_dates(ch, date(2026,12,20), date(2027,1,31)))
    # anchor not respected for weekly when from_date < anchor (relevant after schedule edits)
    ch = NS(recurrence="weekly", weekday=2, day_of_month=None, anchor_date=date(2026,10,14))
    print("weekly Wed anchor 10-14, from 10-06:", next_due_dates(ch, date(2026,10,6), date(2026,10,17)))
    ch = NS(recurrence="biweekly", weekday=2, day_of_month=None, anchor_date=date(2026,10,14))
    print("biweekly Wed anchor 10-14, from 10-06:", next_due_dates(ch, date(2026,10,6), date(2026,10,31)))

if __name__ == "__main__":
    test_incremental_equals_oneshot(); print("incremental==oneshot OK")
    test_rotation_round_robin(); print("rotation OK")
    test_specific_edges()
