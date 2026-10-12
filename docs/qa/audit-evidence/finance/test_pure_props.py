"""Property-based tests against the real pure functions (no DB).
Run: $S/venv/bin/python -m pytest -q test_pure_props.py -p no:cacheprovider
"""
import sys, uuid, itertools
sys.path.insert(0, "/home/user/haushalt-app/backend")
import os
os.environ.setdefault("JWT_SECRET_KEY", "audit-secret-key-only-for-tests-min32-xyz")
os.environ.setdefault("DATABASE_URL", "sqlite://")
from hypothesis import given, settings, strategies as st, assume, example
from fastapi import HTTPException
from app.routers.expenses import split_evenly, compute_settlements, validate_custom_shares, ExpenseShareInput

uuids = st.builds(uuid.uuid4)


@settings(max_examples=3000)
@given(amount=st.integers(min_value=1, max_value=2**31 - 1),
       ids=st.lists(uuids, min_size=1, max_size=40, unique=True))
def test_split_evenly_sums_and_fair(amount, ids):
    m = split_evenly(amount, ids)
    assert sum(m.values()) == amount
    assert set(m) == set(ids)
    assert max(m.values()) - min(m.values()) <= 1
    assert all(v >= 0 for v in m.values())
    # deterministic regardless of input order
    assert split_evenly(amount, list(reversed(ids))) == m


@given(amount=st.integers(min_value=1, max_value=10**6), ids=st.lists(uuids, min_size=1, max_size=5, unique=True))
def test_split_evenly_rejects_duplicates(amount, ids):
    try:
        split_evenly(amount, ids + [ids[0]])
        assert False, "duplicate accepted"
    except HTTPException as e:
        assert e.status_code == 422


def apply(saldi, sett):
    s = dict(saldi)
    for t in sett:
        s[t["from_user_id"]] += t["amount_rappen"]
        s[t["to_user_id"]] -= t["amount_rappen"]
    return s


@st.composite
def zero_sum_saldi(draw, max_n=30):
    n = draw(st.integers(min_value=0, max_value=max_n))
    ids = [uuid.uuid4() for _ in range(n + 1)]
    vals = draw(st.lists(st.integers(min_value=-10**7, max_value=10**7), min_size=n, max_size=n))
    vals.append(-sum(vals))
    return dict(zip(ids, vals))


@settings(max_examples=3000)
@given(zero_sum_saldi())
def test_settlements_zero_balances(saldi):
    sett = compute_settlements(saldi)
    after = apply(saldi, sett)
    assert all(v == 0 for v in after.values())
    nonzero = sum(1 for v in saldi.values() if v != 0)
    assert len(sett) <= max(nonzero - 1, 0)
    for t in sett:
        assert t["amount_rappen"] > 0 and t["from_user_id"] != t["to_user_id"]
        assert saldi[t["from_user_id"]] < 0 < saldi[t["to_user_id"]]  # only debtors pay, creditors receive
    assert compute_settlements(dict(reversed(list(saldi.items())))) == sett  # deterministic


@settings(max_examples=2000)
@given(st.dictionaries(uuids, st.integers(min_value=-10**6, max_value=10**6), max_size=20))
def test_settlements_non_zero_sum(saldi):
    """sum != 0 (e.g. unassigned): never overshoots; afterwards only one side remains."""
    sett = compute_settlements(saldi)
    after = apply(saldi, sett)
    for uid, v in saldi.items():
        # nobody flips sign / overshoots
        assert (v >= 0 and 0 <= after[uid] <= v) or (v <= 0 and v <= after[uid] <= 0)
    assert not (any(v > 0 for v in after.values()) and any(v < 0 for v in after.values()))


def optimal_count(vals):
    """n_nonzero - max number of disjoint zero-sum groups (brute force, small n)."""
    vals = [v for v in vals if v != 0]
    n = len(vals)
    from functools import lru_cache
    @lru_cache(None)
    def best(mask):
        # max number of zero-sum groups partitioning mask
        if mask == 0:
            return 0
        res = 0
        low = mask & -mask
        sub = mask
        while sub:
            if sub & low and sum(vals[i] for i in range(n) if sub >> i & 1) == 0:
                r = best(mask ^ sub)
                if r + 1 > res:
                    res = r + 1
            sub = (sub - 1) & mask
        return res
    return n - best((1 << n) - 1) if n else 0


def test_greedy_not_minimal_example():
    """Search for a small case where greedy uses more transfers than optimal."""
    import random
    random.seed(1)
    found = None
    for _ in range(20000):
        n = random.randint(4, 7)
        vals = [random.randint(-9, 9) for _ in range(n - 1)]
        vals.append(-sum(vals))
        ids = [uuid.uuid4() for _ in vals]
        g = len(compute_settlements(dict(zip(ids, vals))))
        o = optimal_count(vals)
        assert g >= o
        if g > o:
            found = (vals, g, o)
            break
    print("GREEDY_NOT_OPTIMAL_EXAMPLE", found)


@given(amount=st.integers(1, 10**6), parts=st.lists(st.integers(0, 10**5), min_size=1, max_size=8))
def test_validate_custom_shares(amount, parts):
    ids = [uuid.uuid4() for _ in parts]
    shares = [ExpenseShareInput(user_id=i, amount_rappen=p) for i, p in zip(ids, parts)]
    ok = sum(parts) == amount
    try:
        validate_custom_shares(amount, shares)
        assert ok
    except HTTPException:
        assert not ok


def test_large_n_performance():
    import time
    ids = [uuid.uuid4() for _ in range(5000)]
    vals = [((i * 7919) % 20001) - 10000 for i in range(4999)]
    vals.append(-sum(vals))
    t = time.time(); sett = compute_settlements(dict(zip(ids, vals))); dt = time.time() - t
    assert all(v == 0 for v in apply(dict(zip(ids, vals)), sett).values())
    print("N=5000 settlements", len(sett), "time", round(dt, 3))
