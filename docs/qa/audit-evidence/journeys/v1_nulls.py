import sys; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("v1")
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app, raise_server_exceptions=False)
hid, (A, B), (tA, tB) = H.household(["Anna", "Ben"])
P = f"/api/households/{hid}"; ha = H.auth(tA)
cal = c.get(P + "/calendars/", headers=ha).json()
if not cal: cal=[c.post(P+"/calendars/", json={"name":"K","color":"#112233"}, headers=ha).json()]
ev = c.post(P + "/events/", json={"title": "Zahnarzt", "starts_at": "2026-10-12T09:00:00", "calendar_id": cal[0]["id"]}, headers=ha); print("create event", ev.status_code)
ev = ev.json()
print("PATCH participants null:", c.patch(P + f"/events/{ev['id']}", json={"participant_ids": None}, headers=ha).status_code)
print("GET events range (household-wide):", c.get(P + "/events/?from_date=2026-10-01&to_date=2026-10-31", headers=ha).status_code)
print("GET dashboard:", c.get(P + "/dashboard", headers=ha).status_code)
r = c.post(P + "/recipes/", json={"name": "Zopf", "ingredients": ["Mehl"]}, headers=ha).json()
print("PATCH recipe ingredients null:", c.patch(P + f"/recipes/{r['id']}", json={"ingredients": None}, headers=ha).status_code)
print("GET recipes:", c.get(P + "/recipes/", headers=ha).status_code, " (Ben):", c.get(P + "/recipes/", headers=H.auth(tB)).status_code)
