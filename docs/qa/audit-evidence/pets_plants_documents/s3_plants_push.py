import sys, os; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("ppd_plants")
from fastapi.testclient import TestClient
from app.main import app
from collections import Counter
import datetime as dt, zoneinfo
from app.models import PlantCareLog, PlantCareTask, PetCareTask, Document
hid, users, toks = H.household(["Anna","Ben"])
A, B = (H.auth(t) for t in toks)
P = f"/api/households/{hid}/plants/"
mk = lambda: TestClient(app, raise_server_exceptions=False)
c = mk()
tz = zoneinfo.ZoneInfo("Europe/Zurich"); today = dt.datetime.now(tz).date()

print("== P1 parallel complete same plant task ==")
pl = c.post(P, json={"name":"Monstera"}, headers=A).json()
t = c.post(f"{P}{pl['id']}/care-tasks/", json={"care_type":"water","next_due_at":str(today)}, headers=A).json()
res = H.parallel(lambda i: mk().post(f"{P}{pl['id']}/care-tasks/{t['id']}/complete", headers=[A,B][i]).status_code, 2)
print(res, "logs:", len(c.get(f"{P}{pl['id']}/care-log", headers=A).json()))

print("== P2 parallel water-all (5 plants with due water task) ==")
plants = []
for i in range(5):
    p = c.post(P, json={"name":f"P{i}"}, headers=A).json(); plants.append(p["id"])
    c.post(f"{P}{p['id']}/care-tasks/", json={"care_type":"water","next_due_at":str(today - dt.timedelta(days=1))}, headers=A)
cnt = Counter()
for trial in range(6):
    s = H.session(); s.query(PlantCareTask).filter(PlantCareTask.plant_id.in_(plants)).update({"next_due_at": today}, synchronize_session=False); s.query(PlantCareLog).filter(PlantCareLog.plant_id.in_(plants)).delete(synchronize_session=False); s.commit(); s.close()
    res = H.parallel(lambda i: (lambda r: (r.status_code, len(r.json())))(mk().post(P+"water-all", headers=[A,B][i])), 2)
    s = H.session(); n = s.query(PlantCareLog).filter(PlantCareLog.plant_id.in_(plants)).count(); s.close()
    cnt[(tuple(sorted(res)), n)] += 1
print("(responses, logs in DB for 5 plants):", dict(cnt))

print("== P3 multiple water tasks on one plant; water-all only due ones ==")
p = c.post(P, json={"name":"Ficus"}, headers=A).json()
c.post(f"{P}{p['id']}/care-tasks/", json={"care_type":"water","next_due_at":str(today)}, headers=A)
c.post(f"{P}{p['id']}/care-tasks/", json={"care_type":"water","label":"Sommer","next_due_at":str(today+dt.timedelta(days=3))}, headers=A)
c.post(f"{P}{p['id']}/care-tasks/", json={"care_type":"fertilize","next_due_at":str(today)}, headers=A)
r = c.post(P+"water-all", headers=A).json()
print("water-all logs for Ficus:", sum(1 for l in r if l["plant_id"]==p["id"]))

print("== P4 interval change: due date not recomputed (E-2) ==")
t = c.post(f"{P}{p['id']}/care-tasks/", json={"care_type":"repot","interval_days":365,"next_due_at":str(today+dt.timedelta(days=300))}, headers=A).json()
r = c.patch(f"{P}{p['id']}/care-tasks/{t['id']}", json={"interval_days":30}, headers=A).json()
print("interval 365->30, next_due stays:", r["next_due_at"])

print("== PU1 push scheduler claim race: task completed between due-query and claim ==")
import app.services.push_service as PS
pet = c.post(f"/api/households/{hid}/pets/", json={"name":"Mia"}, headers=A).json()
t1 = c.post(f"/api/households/{hid}/pets/{pet['id']}/care-tasks/", json={"name":"Wurmkur","interval_days":30,"next_due_at":str(today)}, headers=A).json()
t2 = c.post(f"/api/households/{hid}/pets/{pet['id']}/care-tasks/", json={"name":"Krallen","interval_days":14,"next_due_at":str(today)}, headers=A).json()
order = []
def fake_send(db, recipients, build, household_id=None):
    order.append(build("de")["body"])
    if len(order) == 1:   # while sending first push (HTTP), a user completes the other task
        other = t2 if "Wurmkur" in order[0] else t1
        print("  user completes", other["name"], "->", c.post(f"/api/households/{hid}/pets/{pet['id']}/care-tasks/{other['id']}/complete", headers=B).json()["next_due_at"])
    return 1
PS.send_to_users = fake_send
now = dt.datetime.combine(today, dt.time(10, 0), tzinfo=tz).astimezone(dt.timezone.utc)
db = H.session(); sent = PS.process_pet_care_tasks(db, now); db.close()
print("  pushes sent:", sent, order)
s = H.session()
for tid in (t1["id"], t2["id"]):
    tk = s.get(PetCareTask, tid); print("  ", tk.name, "next_due", tk.next_due_at, "notified_at set:", tk.notified_at is not None)
s.close()
later = dt.datetime.combine(today + dt.timedelta(days=31), dt.time(10, 0), tzinfo=tz).astimezone(dt.timezone.utc)
order.clear()
db = H.session(); print("  run at next due date(s) +31d: pushes", PS.process_pet_care_tasks(db, later), order); db.close()

print("== PU2 document expiry: claim race with date change ==")
fid = c.post(f"/api/households/{hid}/files/", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")}, headers=A).json()["id"]
d1 = c.post(f"/api/households/{hid}/documents/", json={"title":"Garantie TV","file_ids":[fid],"expiry_date":str(today+dt.timedelta(days=10))}, headers=A).json()
fid2 = c.post(f"/api/households/{hid}/files/", files={"file": ("a.pdf", b"%PDF-1.4 y", "application/pdf")}, headers=A).json()["id"]
d0 = c.post(f"/api/households/{hid}/documents/", json={"title":"AAA first","file_ids":[fid2],"expiry_date":str(today+dt.timedelta(days=5))}, headers=A).json()
order = []
def fake_send2(db, recipients, build, household_id=None):
    order.append(build("de")["body"])
    if len(order) == 1:
        other = d1 if "AAA" in order[0] else d0
        c.patch(f"/api/households/{hid}/documents/{other['id']}", json={"expiry_date": str(today+dt.timedelta(days=200))}, headers=A)
        print("  user moves expiry of", other["title"], "to +200d")
    return 1
PS.send_to_users = fake_send2
db = H.session(); print("  sent", PS.process_document_expiry(db, now), order); db.close()
s = H.session()
for d in (d0, d1):
    x = s.get(Document, d["id"]); print("  ", x.title, x.expiry_date, "soon_notified set:", x.expiry_soon_notified_at is not None)
