"""Exception classes for overlapping concurrent PATCH (amount) and DELETE||PATCH. Run with $S/venv/bin/python."""
import sys, collections, warnings
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("finance_conc3")
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
def name(r): return r.status_code if hasattr(r, "status_code") else f"{type(r).__module__}.{type(r).__name__}: {str(r).splitlines()[0][:120]}"
out = collections.Counter()
for _ in range(8):
    hid, U, T = H.household(["A", "B", "C"])
    e = c.post(f"/api/households/{hid}/expenses/", json={"description": "x", "amount_rappen": 1000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0])).json()
    for r in H.parallel(lambda i: TestClient(app).patch(f"/api/households/{hid}/expenses/{e['id']}", json={"amount_rappen": 1001 + i}, headers=H.auth(T[i])), 2):
        out["PATCH||PATCH " + str(name(r))] += 1
    e = c.post(f"/api/households/{hid}/expenses/", json={"description": "x", "amount_rappen": 1000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0])).json()
    rs = H.parallel(lambda i: TestClient(app).delete(f"/api/households/{hid}/expenses/{e['id']}", headers=H.auth(T[0])) if i == 0 else TestClient(app).patch(f"/api/households/{hid}/expenses/{e['id']}", json={"amount_rappen": 1500}, headers=H.auth(T[1])), 2)
    out["DELETE " + str(name(rs[0]))] += 1; out["PATCH(vs delete) " + str(name(rs[1]))] += 1
    rs = H.parallel(lambda i: TestClient(app).put(f"/api/households/{hid}/budget", json={"month": "2026-11-01", "amount_rappen": 5000 + i}, headers=H.auth(T[i])), 2)
    for r in rs: out["PUT budget " + str(name(r))] += 1
for k, v in sorted(out.items()): print(v, k)
