"""Property-basierte Tests der reinen Finanzfunktionen (ohne DB).

Portiert aus docs/qa/audit-evidence/finance/test_pure_props.py. Die Ledger-Invarianten
über echte REST-Sequenzen laufen in der PostgreSQL-Lane (tests/pg/test_pg_finance_props.py).
"""

import random
import time
import uuid
from functools import lru_cache

import pytest
from fastapi import HTTPException
from hypothesis import given, settings
from hypothesis import strategies as st

from app.routers.expenses import (
    ExpenseShareInput,
    compute_settlements,
    split_evenly,
    validate_custom_shares,
)
from app.services.finance_rules import MAX_AMOUNT_RAPPEN

uuids = st.builds(uuid.uuid4)


@settings(max_examples=500, deadline=None)
@given(
    amount=st.integers(min_value=1, max_value=MAX_AMOUNT_RAPPEN),
    ids=st.lists(uuids, min_size=1, max_size=40, unique=True),
)
def test_split_evenly_sums_and_fair(amount, ids):
    m = split_evenly(amount, ids)
    assert sum(m.values()) == amount
    assert set(m) == set(ids)
    assert max(m.values()) - min(m.values()) <= 1
    assert all(v >= 0 for v in m.values())
    # Deterministisch unabhängig von der Reihenfolge
    assert split_evenly(amount, list(reversed(ids))) == m


@settings(deadline=None)
@given(amount=st.integers(min_value=1, max_value=10**6), ids=st.lists(uuids, min_size=1, max_size=5, unique=True))
def test_split_evenly_rejects_duplicates(amount, ids):
    with pytest.raises(HTTPException) as exc:
        split_evenly(amount, ids + [ids[0]])
    assert exc.value.status_code == 422


def _apply(saldi, settlements):
    s = dict(saldi)
    for t in settlements:
        s[t["from_user_id"]] += t["amount_rappen"]
        s[t["to_user_id"]] -= t["amount_rappen"]
    return s


@st.composite
def zero_sum_saldi(draw, max_n=30):
    n = draw(st.integers(min_value=0, max_value=max_n))
    ids = [uuid.uuid4() for _ in range(n + 1)]
    vals = draw(st.lists(st.integers(min_value=-10**7, max_value=10**7), min_size=n, max_size=n))
    vals.append(-sum(vals))
    return dict(zip(ids, vals, strict=True))


@settings(max_examples=500, deadline=None)
@given(zero_sum_saldi())
def test_settlements_zero_balances(saldi):
    sett = compute_settlements(saldi)
    after = _apply(saldi, sett)
    assert all(v == 0 for v in after.values())
    nonzero = sum(1 for v in saldi.values() if v != 0)
    assert len(sett) <= max(nonzero - 1, 0)
    for t in sett:
        assert t["amount_rappen"] > 0 and t["from_user_id"] != t["to_user_id"]
        # Nur Schuldner zahlen, nur Gläubiger empfangen
        assert saldi[t["from_user_id"]] < 0 < saldi[t["to_user_id"]]
    assert compute_settlements(dict(reversed(list(saldi.items())))) == sett


@settings(max_examples=300, deadline=None)
@given(st.dictionaries(uuids, st.integers(min_value=-10**6, max_value=10**6), max_size=20))
def test_settlements_non_zero_sum(saldi):
    """Summe != 0 (z. B. Ausgaben ohne Zahler): nie überschiessen, danach bleibt nur eine Seite."""
    sett = compute_settlements(saldi)
    after = _apply(saldi, sett)
    for uid, v in saldi.items():
        assert (v >= 0 and 0 <= after[uid] <= v) or (v <= 0 and v <= after[uid] <= 0)
    assert not (any(v > 0 for v in after.values()) and any(v < 0 for v in after.values()))


def _optimal_count(vals):
    """n_nonzero - max. Anzahl disjunkter Nullsummen-Gruppen (Brute Force, kleines n)."""
    vals = [v for v in vals if v != 0]
    n = len(vals)

    @lru_cache(None)
    def best(mask):
        if mask == 0:
            return 0
        res = 0
        low = mask & -mask
        sub = mask
        while sub:
            if sub & low and sum(vals[i] for i in range(n) if sub >> i & 1) == 0:
                res = max(res, best(mask ^ sub) + 1)
            sub = (sub - 1) & mask
        return res

    return n - best((1 << n) - 1) if n else 0


def test_greedy_never_beats_optimum():
    """Greedy braucht nie weniger Überweisungen als das Optimum (Plausibilität der Vorschläge)."""
    rng = random.Random(1)
    for _ in range(2000):
        n = rng.randint(4, 7)
        vals = [rng.randint(-9, 9) for _ in range(n - 1)]
        vals.append(-sum(vals))
        ids = [uuid.uuid4() for _ in vals]
        assert len(compute_settlements(dict(zip(ids, vals, strict=True)))) >= _optimal_count(vals)


@settings(deadline=None)
@given(amount=st.integers(1, 10**6), parts=st.lists(st.integers(0, 10**5), min_size=1, max_size=8))
def test_validate_custom_shares(amount, parts):
    shares = [ExpenseShareInput(user_id=uuid.uuid4(), amount_rappen=p) for p in parts]
    if sum(parts) == amount:
        validate_custom_shares(amount, shares)
    else:
        with pytest.raises(HTTPException):
            validate_custom_shares(amount, shares)


def test_large_n_performance():
    ids = [uuid.uuid4() for _ in range(5000)]
    vals = [((i * 7919) % 20001) - 10000 for i in range(4999)]
    vals.append(-sum(vals))
    saldi = dict(zip(ids, vals, strict=True))
    start = time.monotonic()
    sett = compute_settlements(saldi)
    assert time.monotonic() - start < 5
    assert all(v == 0 for v in _apply(saldi, sett).values())
