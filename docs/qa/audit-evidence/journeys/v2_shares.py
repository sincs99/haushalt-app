import sys, uuid; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("v2")
from fastapi.testclient import TestClient
from app.main import app
from app.models import Expense
cs = [TestClient(app, raise_server_exceptions=False) for _ in range(2)]
hid, (A, B, C, D), toks = H.household(["Anna", "Ben", "Carla", "Dora"])
P = f"/api/households/{hid}"
bad = 0; codes_all = []
for t in range(10):
    e = cs[0].post(P + "/expenses/", json={"description": "x", "amount_rappen": 1000, "paid_by_user_id": str(A), "split_type": "even"}, headers=H.auth(toks[0])).json()
    sets = [[str(A), str(B)], [str(C), str(D)]]
    codes = H.parallel(lambda i: cs[i].patch(P + f"/expenses/{e['id']}", json={"participant_ids": sets[i]}, headers=H.auth(toks[i])).status_code, 2)
    s = H.session(); ex = s.get(Expense, uuid.UUID(e["id"]))
    tot = sum(x.amount_rappen for x in ex.shares); n = len(ex.shares); s.close()
    codes_all.append((tuple(codes), n, tot))
    if tot != 1000: bad += 1
bal = cs[0].get(P + "/expenses/balances", headers=H.auth(toks[0])).json()
print("rounds (codes, n_shares, sum):", codes_all)
print("invariant violations:", bad, "/10; sum saldi:", sum(b["saldo_rappen"] for b in bal["balances"]), "unassigned:", bal["unassigned_rappen"])
