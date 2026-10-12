"""Detail repro for concurrent PATCH: exception classes + balance effect. Run: $S/venv/bin/python pg_conc_detail.py"""
import sys, collections
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("finance_conc2")
from fastapi.testclient import TestClient
from app.main import app
from sqlalchemy import text
c = TestClient(app)
exc = collections.Counter()
for rnd in range(10):
    hid, U, T = H.household(["A", "B", "C", "D"])
    e = c.post(f"/api/households/{hid}/expenses/", json={"description": "Einkauf", "amount_rappen": 1000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0])).json()
    sets = [[U[0], U[1]], [U[2], U[3]]]
    rs = H.parallel(lambda i: TestClient(app).patch(f"/api/households/{hid}/expenses/{e['id']}", json={"participant_ids": [str(x) for x in sets[i]]}, headers=H.auth(T[i])), 2)
    for r in rs:
        exc[r.status_code if hasattr(r, "status_code") else f"{type(r).__module__}.{type(r).__name__}: {str(r).splitlines()[0][:110]}"] += 1
    b = c.get(f"/api/households/{hid}/expenses/balances", headers=H.auth(T[0])).json()
    got = c.get(f"/api/households/{hid}/expenses/", headers=H.auth(T[0])).json()[0]
    if rnd < 3 or sum(s["amount_rappen"] for s in got["shares"]) != got["amount_rappen"]:
        print(f"round {rnd}: amount={got['amount_rappen']} shares={sorted(s['amount_rappen'] for s in got['shares'])} n={len(got['shares'])} "
              f"sum(saldi)={sum(x['saldo_rappen'] for x in b['balances'])} unassigned={b['unassigned_rappen']} saldi={[x['saldo_rappen'] for x in b['balances']]}")
print("outcomes:", dict(exc))
