"""Explicit nulls in PATCH /expenses. Run with $S/venv/bin/python."""
import sys
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("finance_nulls")
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app, raise_server_exceptions=False)
hid, U, T = H.household(["A", "B"])
E = f"/api/households/{hid}/expenses/"
e = c.post(E, json={"description": "x", "amount_rappen": 1000, "paid_by_user_id": str(U[0]), "split_type": "custom", "shares": [{"user_id": str(U[1]), "amount_rappen": 1000}], "category": "groceries"}, headers=H.auth(T[0])).json()
for body in ({"description": None}, {"expense_date": None}, {"split_type": None}, {"amount_rappen": None}, {"category": None}, {"shares": None, "split_type": "custom"}):
    r = c.patch(E + e["id"], json=body, headers=H.auth(T[0]))
    print(body, "->", r.status_code, r.text[:90])
r = c.patch(f"/api/households/{hid}/recurring-bills/00000000-0000-0000-0000-000000000000", json={"name": None}, headers=H.auth(T[0])); print("bill 404 check", r.status_code)
b = c.post(f"/api/households/{hid}/recurring-bills/", json={"name": "n", "amount_rappen": 5, "day_of_month": 2}, headers=H.auth(T[0])).json()
for body in ({"name": None}, {"amount_rappen": None}, {"active": None}, {"day_of_month": None}):
    r = c.patch(f"/api/households/{hid}/recurring-bills/{b['id']}", json=body, headers=H.auth(T[0])); print("bill", body, "->", r.status_code)
