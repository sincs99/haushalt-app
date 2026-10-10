import sys, collections; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("j3")
from fastapi.testclient import TestClient
from app.main import app
hid, (A, B, C), (tA, tB, tC) = H.household(["Anna", "Ben", "Carla"])
P = f"/api/households/{hid}"
clients = [TestClient(app, raise_server_exceptions=True) for _ in range(2)]
stats = collections.Counter(); violations = []
for trial in range(6):
    e = clients[0].post(P + "/expenses/", json={"description": "x", "amount_rappen": 10000, "paid_by_user_id": str(A), "split_type": "even"}, headers=H.auth(tA)).json()
    eid = e["id"]
    def op(i):
        if i == 0:
            r = clients[0].patch(P + f"/expenses/{eid}", json={"amount_rappen": 12000}, headers=H.auth(tA)); return r.status_code
        return clients[1].patch(P + f"/expenses/{eid}", json={"participant_ids": [str(A), str(B)]}, headers=H.auth(tB)).status_code
    codes = H.parallel(op, 2); [print("EXC", type(x).__name__, str(x)[:160]) for x in codes if isinstance(x, Exception)]
    stats[tuple(codes)] += 1
    s = H.session()
    from app.models import Expense
    ex = s.get(Expense, __import__("uuid").UUID(eid)); s.refresh(ex)
    total = sum(x.amount_rappen for x in ex.shares)
    if total != ex.amount_rappen:
        violations.append((trial, ex.amount_rappen, total, len(ex.shares), codes))
    s.close()
print("status code combos:", dict(stats))
print("invariant violations (trial, amount, sum_shares, n_shares, codes):", violations[:10], "count", len(violations))
