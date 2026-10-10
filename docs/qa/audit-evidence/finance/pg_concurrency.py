"""Concurrency checks on PostgreSQL (real per-request sessions, true threads).
Run: $S/venv/bin/python pg_concurrency.py
"""
import sys, collections
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("finance_conc")
from fastapi.testclient import TestClient
from app.main import app
from sqlalchemy import text

def cl(): return TestClient(app, raise_server_exceptions=False)
c = cl()
ROUNDS = 15

def share_check(eid):
    s = H.session()
    amt, ssum, n = s.execute(text("""SELECT e.amount_rappen, COALESCE(SUM(sh.amount_rappen),0), COUNT(sh.id) FROM expenses e
        LEFT JOIN expense_shares sh ON sh.expense_id=e.id WHERE e.id=:e GROUP BY e.id"""), {"e": eid}).one()
    s.close(); return amt, ssum, n

def tally(rs): return dict(collections.Counter(r.status_code if hasattr(r, "status_code") else type(r).__name__ for r in rs))

# a) duplicate settlement
agg = collections.Counter()
for _ in range(ROUNDS):
    hid, U, T = H.household(["A", "B"])
    body = {"from_user_id": str(U[1]), "to_user_id": str(U[0]), "amount_rappen": 2500}
    rs = H.parallel(lambda i: cl().post(f"/api/households/{hid}/settlements/", json=body, headers=H.auth(T[i % 2])), 2)
    n = len(c.get(f"/api/households/{hid}/settlements/", headers=H.auth(T[0])).json())
    agg[(tuple(sorted(tally(rs).items())), n)] += 1
print("a) 2 parallel identical settlements -> (statuses, rows):", dict(agg))

# b) parallel booking
agg = collections.Counter()
for _ in range(ROUNDS):
    hid, U, T = H.household(["A", "B", "C"])
    bill = c.post(f"/api/households/{hid}/recurring-bills/", json={"name": "Miete", "amount_rappen": 150000, "day_of_month": 1, "paid_by_user_id": str(U[0])}, headers=H.auth(T[0])).json()
    rs = H.parallel(lambda i: cl().post(f"/api/households/{hid}/recurring-bills/{bill['id']}/book", headers=H.auth(T[i % 3])), 8)
    s = H.session(); n = s.execute(text("SELECT count(*) FROM expenses WHERE recurring_bill_id=:b"), {"b": bill["id"]}).scalar(); s.close()
    agg[(tuple(sorted(tally(rs).items())), n)] += 1
print("b) 8 parallel book -> (statuses, expense rows):", dict(agg))

# c) parallel PATCH participants (different sets) on the same expense
agg = collections.Counter(); bad = []
for _ in range(ROUNDS):
    hid, U, T = H.household(["A", "B", "C", "D"])
    e = c.post(f"/api/households/{hid}/expenses/", json={"description": "x", "amount_rappen": 1000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0])).json()
    sets = [[U[0], U[1]], [U[2], U[3]], [U[0], U[2]], [U[1], U[3]]]
    rs = H.parallel(lambda i: cl().patch(f"/api/households/{hid}/expenses/{e['id']}", json={"participant_ids": [str(x) for x in sets[i]]}, headers=H.auth(T[i])), 4)
    amt, ssum, n = share_check(e["id"])
    agg[(tuple(sorted(tally(rs).items())), ssum == amt)] += 1
    if ssum != amt: bad.append((amt, ssum, n))
print("c) 4 parallel PATCH participant sets -> (statuses, shares==amount):", dict(agg), "violations:", bad[:3])

# d) parallel PATCH amount
agg = collections.Counter(); bad = []
for _ in range(ROUNDS):
    hid, U, T = H.household(["A", "B", "C"])
    e = c.post(f"/api/households/{hid}/expenses/", json={"description": "x", "amount_rappen": 1000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0])).json()
    rs = H.parallel(lambda i: cl().patch(f"/api/households/{hid}/expenses/{e['id']}", json={"amount_rappen": 1000 + 7 * (i + 1)}, headers=H.auth(T[i % 3])), 4)
    amt, ssum, n = share_check(e["id"])
    agg[(tuple(sorted(tally(rs).items())), ssum == amt)] += 1
    if ssum != amt: bad.append((amt, ssum, n))
print("d) 4 parallel PATCH amount -> (statuses, shares==amount):", dict(agg), "violations:", bad[:3])

# e) PATCH amount + PATCH participants concurrently (lost update / mixed state)
agg = collections.Counter(); bad = []
for _ in range(ROUNDS):
    hid, U, T = H.household(["A", "B", "C"])
    e = c.post(f"/api/households/{hid}/expenses/", json={"description": "x", "amount_rappen": 900, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0])).json()
    bodies = [{"amount_rappen": 1200}, {"participant_ids": [str(U[0]), str(U[1])]}]
    rs = H.parallel(lambda i: cl().patch(f"/api/households/{hid}/expenses/{e['id']}", json=bodies[i], headers=H.auth(T[i])), 2)
    amt, ssum, n = share_check(e["id"])
    agg[(tuple(sorted(tally(rs).items())), amt, ssum, n)] += 1
print("e) PATCH amount=1200 || PATCH participants=[A,B] (start 900 over 3) -> (statuses, amount, sum(shares), n_shares):", dict(agg))

# f) PATCH vs DELETE
agg = collections.Counter()
for _ in range(ROUNDS):
    hid, U, T = H.household(["A", "B"])
    e = c.post(f"/api/households/{hid}/expenses/", json={"description": "x", "amount_rappen": 1000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0])).json()
    def f(i):
        if i == 0: return cl().delete(f"/api/households/{hid}/expenses/{e['id']}", headers=H.auth(T[0]))
        return cl().patch(f"/api/households/{hid}/expenses/{e['id']}", json={"amount_rappen": 1500}, headers=H.auth(T[1]))
    rs = H.parallel(f, 2)
    s = H.session(); left = s.execute(text("SELECT count(*) FROM expense_shares WHERE expense_id=:e"), {"e": e["id"]}).scalar(); s.close()
    agg[(rs[0].status_code, rs[1].status_code, left)] += 1
print("f) DELETE || PATCH amount -> (delete, patch, orphan shares):", dict(agg))

# g) parallel budget upsert (first creation)
agg = collections.Counter()
for _ in range(ROUNDS):
    hid, U, T = H.household(["A", "B"])
    rs = H.parallel(lambda i: cl().put(f"/api/households/{hid}/budget", json={"month": "2026-10-01", "amount_rappen": 100000 + i}, headers=H.auth(T[i % 2])), 4)
    agg[tuple(sorted(tally(rs).items()))] += 1
print("g) 4 parallel PUT /budget (no budget yet) -> statuses:", dict(agg))

# h) concurrent full-payload edits by two users (UI behaviour) -> last writer wins, no error
hid, U, T = H.household(["A", "B"])
e = c.post(f"/api/households/{hid}/expenses/", json={"description": "x", "amount_rappen": 1000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0])).json()
bodies = [{"description": "A edit", "amount_rappen": 1000, "paid_by_user_id": str(U[0]), "split_type": "even", "participant_ids": [str(U[0]), str(U[1])]},
          {"description": "x", "amount_rappen": 2000, "paid_by_user_id": str(U[0]), "split_type": "even", "participant_ids": [str(U[0]), str(U[1])]}]
rs = H.parallel(lambda i: cl().patch(f"/api/households/{hid}/expenses/{e['id']}", json=bodies[i], headers=H.auth(T[i])), 2)
final = c.get(f"/api/households/{hid}/expenses/", headers=H.auth(T[0])).json()[0]
print("h) parallel full-payload edits (A renames, B changes amount) ->", tally(rs), "final:", final["description"], final["amount_rappen"])
print("DONE")
