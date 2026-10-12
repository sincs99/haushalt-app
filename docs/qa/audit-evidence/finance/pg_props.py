"""Hypothesis property test: random sequences of REST operations on PostgreSQL.
After every step, check ledger invariants straight from the DB and from GET /balances.
Run: $S/venv/bin/python pg_props.py
"""
import sys, uuid, random
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("finance_props")
from fastapi.testclient import TestClient
from app.main import app
from sqlalchemy import text
from hypothesis import given, settings, strategies as st, HealthCheck, Phase

c = TestClient(app, raise_server_exceptions=False)
stats = {}

def check(hid, tok):
    s = H.session()
    rows = s.execute(text("""SELECT e.id, e.amount_rappen, COALESCE(SUM(sh.amount_rappen),0), COUNT(sh.id), e.split_type
                            FROM expenses e LEFT JOIN expense_shares sh ON sh.expense_id=e.id
                            WHERE e.household_id=:h GROUP BY e.id"""), {"h": hid}).all()
    neg = s.execute(text("SELECT count(*) FROM expense_shares WHERE household_id=:h AND amount_rappen<0"), {"h": hid}).scalar()
    s.close()
    for eid, amt, ssum, n, stype in rows:
        assert ssum == amt, f"expense {eid}: shares {ssum} != amount {amt}"
        assert n >= 1, f"expense {eid} without shares"
    assert neg == 0
    b = c.get(f"/api/households/{hid}/expenses/balances", headers=H.auth(tok)).json()
    sal = {x["user_id"]: x["saldo_rappen"] for x in b["balances"]}
    assert sum(sal.values()) + b["unassigned_rappen"] == 0 or b["unassigned_rappen"] == 0 and sum(sal.values()) == 0, (sal, b["unassigned_rappen"])
    assert sum(sal.values()) == -b["unassigned_rappen"]
    after = dict(sal)
    for t in b["settlements"]:
        after[t["from_user_id"]] += t["amount_rappen"]; after[t["to_user_id"]] -= t["amount_rappen"]
    assert all(v == 0 for v in after.values()), after
    nz = sum(1 for v in sal.values() if v)
    assert len(b["settlements"]) <= max(nz - 1, 0)


op = st.one_of(
    st.tuples(st.just("create_even"), st.integers(1, 10**7), st.integers(0, 4), st.lists(st.integers(0, 4), max_size=5)),
    st.tuples(st.just("create_custom"), st.integers(0, 4), st.lists(st.tuples(st.integers(0, 4), st.integers(0, 5000)), min_size=1, max_size=5)),
    st.tuples(st.just("patch_amount"), st.integers(0, 50), st.integers(1, 10**7)),
    st.tuples(st.just("patch_participants"), st.integers(0, 50), st.lists(st.integers(0, 4), max_size=5)),
    st.tuples(st.just("patch_to_custom"), st.integers(0, 50), st.lists(st.tuples(st.integers(0, 4), st.integers(0, 5000)), min_size=1, max_size=5)),
    st.tuples(st.just("patch_to_even"), st.integers(0, 50)),
    st.tuples(st.just("patch_payer"), st.integers(0, 50), st.integers(0, 4)),
    st.tuples(st.just("patch_fullpayload"), st.integers(0, 50)),
    st.tuples(st.just("delete"), st.integers(0, 50)),
    st.tuples(st.just("settle_suggestion"), st.integers(0, 10), st.integers(0, 4)),
    st.tuples(st.just("settle_random"), st.integers(0, 4), st.integers(0, 4), st.integers(1, 10**6)),
    st.tuples(st.just("leave"), st.integers(1, 4)),
    st.tuples(st.just("join"),),
    st.tuples(st.just("book"), st.integers(1, 10**6), st.integers(0, 4)),
)


@settings(max_examples=300, deadline=None, suppress_health_check=list(HealthCheck), phases=[Phase.generate])
@given(st.lists(op, min_size=1, max_size=25))
def test_ledger(ops):
    hid, U, T = H.household(["A", "B", "C", "D"])
    users = list(U); toks = list(T); active = [True] * 4
    E = f"/api/households/{hid}/expenses/"
    exp_ids = []
    def uid(i): return str(users[i % len(users)])
    def actor():
        for i, a in enumerate(active):
            if a: return toks[i]
    for k, amt in enumerate((1001, 77, 333334)):
        r0 = c.post(E, json={"description": "seed", "amount_rappen": amt, "paid_by_user_id": uid(k), "split_type": "even",
                             "participant_ids": [uid(j) for j in range(k + 1, 4)] if k < 2 else None}, headers=H.auth(toks[0]))
        exp_ids.append(r0.json()["id"])
    for o in ops:
        kind = o[0]; tok = actor()
        if tok is None: break
        if kind == "create_even":
            r = c.post(E, json={"description": "e", "amount_rappen": o[1], "paid_by_user_id": uid(o[2]), "split_type": "even",
                                "participant_ids": [uid(i) for i in o[3]] or None}, headers=H.auth(tok))
            if r.status_code == 201: exp_ids.append(r.json()["id"])
        elif kind == "create_custom":
            shares = [{"user_id": uid(i), "amount_rappen": a} for i, a in o[2]]
            amt = sum(a for _, a in o[2])
            r = c.post(E, json={"description": "c", "amount_rappen": amt, "paid_by_user_id": uid(o[1]), "split_type": "custom", "shares": shares}, headers=H.auth(tok))
            if r.status_code == 201: exp_ids.append(r.json()["id"])
        elif kind.startswith("patch") or kind == "delete":
            if not exp_ids: continue
            eid = exp_ids[o[1] % len(exp_ids)]
            if kind == "patch_amount": body = {"amount_rappen": o[2]}
            elif kind == "patch_participants": body = {"participant_ids": [uid(i) for i in o[2]]}
            elif kind == "patch_to_custom":
                body = {"split_type": "custom", "amount_rappen": max(1, sum(a for _, a in o[2])),
                        "shares": [{"user_id": uid(i), "amount_rappen": a} for i, a in o[2]]}
            elif kind == "patch_to_even": body = {"split_type": "even"}
            elif kind == "patch_payer": body = {"paid_by_user_id": uid(o[2])}
            elif kind == "patch_fullpayload":
                cur = next((e for e in c.get(E, headers=H.auth(tok)).json() if e["id"] == eid), None)
                if not cur: continue
                body = {"description": cur["description"], "amount_rappen": cur["amount_rappen"], "paid_by_user_id": cur["paid_by_user_id"],
                        "expense_date": cur["expense_date"], "split_type": cur["split_type"]}
                if cur["split_type"] == "even": body["participant_ids"] = [s["user_id"] for s in cur["shares"]]
                else: body["shares"] = [s for s in cur["shares"] if s["amount_rappen"] > 0] or cur["shares"]
                r = c.patch(E + eid, json=body, headers=H.auth(tok))
                stats.setdefault("fullpayload", {}).setdefault(r.status_code, 0); stats["fullpayload"][r.status_code] += 1
                assert r.status_code == 200, ("UI-style full payload edit failed", r.status_code, r.text, body)
                check(hid, actor()); continue
            if kind == "delete":
                r = c.delete(E + eid, headers=H.auth(tok)); exp_ids.remove(eid)
            else:
                r = c.patch(E + eid, json=body, headers=H.auth(tok))
        elif kind == "settle_suggestion":
            sug = c.get(E + "balances", headers=H.auth(tok)).json()["settlements"]
            if not sug: continue
            s = sug[o[1] % len(sug)]
            r = c.post(f"/api/households/{hid}/settlements/", json={k: s[k] for k in ("from_user_id", "to_user_id", "amount_rappen")}, headers=H.auth(tok))
        elif kind == "settle_random":
            r = c.post(f"/api/households/{hid}/settlements/", json={"from_user_id": uid(o[1]), "to_user_id": uid(o[2]), "amount_rappen": o[3]}, headers=H.auth(tok))
        elif kind == "leave":
            i = o[1] % len(users)
            if not active[i] or sum(active) <= 1: continue
            r = c.post(f"/api/households/{hid}/leave", headers=H.auth(toks[i])); active[i] = False
        elif kind == "join":
            if len(users) >= 6: continue
            u, t = H.add_member(hid, "J"); users.append(u); toks.append(t); active.append(True); r = None
        elif kind == "book":
            b = c.post(f"/api/households/{hid}/recurring-bills/", json={"name": "b", "amount_rappen": o[1], "day_of_month": 5, "paid_by_user_id": uid(o[2])}, headers=H.auth(tok))
            if b.status_code != 201: continue
            r = c.post(f"/api/households/{hid}/recurring-bills/{b.json()['id']}/book", headers=H.auth(tok))
            if r.status_code == 201: exp_ids.append(r.json()["id"])
        if r is not None:
            assert r.status_code < 500, (kind, r.status_code, r.text)
            stats.setdefault(kind, {}).setdefault(r.status_code, 0); stats[kind][r.status_code] += 1
        check(hid, actor())


if __name__ == "__main__":
    test_ledger()
    print("PASSED")
    for k, v in sorted(stats.items()): print(" ", k, v)
