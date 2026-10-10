import sys; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("ppd_pets")
from fastapi.testclient import TestClient
from app.main import app
from collections import Counter
hid, users, toks = H.household(["Anna","Ben"])
A, B = H.auth(toks[0]), H.auth(toks[1])
base = f"/api/households/{hid}/pets"
def mk():
    return TestClient(app, raise_server_exceptions=False)
c = mk()
pets = [c.post(base+"/", json={"name": n, "species": sp}, headers=A).json()["id"] for n, sp in [("Mia","cat"),("Leo","cat"),("Nemo","fish"),("Rex","dog")]]

print("== S1 concurrent single feeding same pet/slot (8 trials, 2 threads) ==")
cnt = Counter()
for t in range(8):
    slot = "morning"
    r = H.parallel(lambda i: mk().post(f"{base}/{pets[0]}/feedings", json={"slot": slot}, headers=[A,B][i]).status_code, 2)
    cnt[tuple(sorted(r))] += 1
    fs = c.get(base+"/feeding-status", headers=A).json()
    fid = [x for x in fs if x["pet_id"]==pets[0]][0]["morning"]["id"]
    c.delete(f"{base}/{pets[0]}/feedings/{fid}", headers=A)
print(dict(cnt))

print("== S2 feed-all vs single feeding of one pet (race) ==")
from app.models import FeedingLog
outcomes = Counter()
for t in range(30):
    def f(i):
        cl = mk()
        if i == 0:
            r = cl.post(f"{base}/{pets[0]}/feedings", json={"slot":"evening"}, headers=A); return ("single", r.status_code, None)
        r = cl.post(base+"/feed-all", json={"slot":"evening"}, headers=B); return ("all", r.status_code, len(r.json()))
    res = H.parallel(f, 2)
    s = H.session(); fed = s.query(FeedingLog).filter(FeedingLog.household_id==hid, FeedingLog.slot=="evening").count()
    s.query(FeedingLog).filter(FeedingLog.household_id==hid, FeedingLog.slot=="evening").delete(); s.commit(); s.close()
    allres = [x for x in res if x[0]=="all"][0]
    outcomes[(allres[1], allres[2], fed)] += 1
print("(feed-all status, feed-all returned n, pets fed in DB [4 pets]):", dict(outcomes))

print("== S2b feed-all vs feed-all ==")
outcomes = Counter()
for t in range(15):
    res = H.parallel(lambda i: (lambda r: (r.status_code, len(r.json())))(mk().post(base+"/feed-all", json={"slot":"evening"}, headers=[A,B][i])), 2)
    s = H.session(); fed = s.query(FeedingLog).filter(FeedingLog.household_id==hid, FeedingLog.slot=="evening").count()
    s.query(FeedingLog).filter(FeedingLog.household_id==hid, FeedingLog.slot=="evening").delete(); s.commit(); s.close()
    outcomes[(tuple(sorted(res)), fed)] += 1
print(dict(outcomes))

print("== S2c feed-all scope: includes fish/dog (no species/active filter) ==")
r = c.post(base+"/feed-all", json={"slot":"morning"}, headers=A).json()
print("feed-all fed", len(r), "pets of 4 incl. fish+dog")
# B deletes A's feeding (no ownership check, no audit)
fid = r[0]["id"]; pid = r[0]["pet_id"]
print("Ben deletes Anna's feeding:", c.delete(f"{base}/{pid}/feedings/{fid}", headers=B).status_code)

print("== S3 medication ==")
med = c.post(f"{base}/{pets[0]}/medications", json={"name":"Antibiotikum","dosage":"1 Tbl","schedule":"2x täglich"}, headers=A).json()
res = H.parallel(lambda i: mk().post(f"{base}/{pets[0]}/medications/{med['id']}/give", headers=[A,B][i]).status_code, 2)
print("parallel give by Anna+Ben:", res)
r1 = c.post(f"{base}/{pets[0]}/medications/{med['id']}/give", headers=A).status_code
r2 = c.post(f"{base}/{pets[0]}/medications/{med['id']}/give", headers=A).status_code
print("sequential double give:", r1, r2)
log = c.get(f"{base}/{pets[0]}/medications/{med['id']}/log", headers=A).json()
print("log entries:", len(log))
print("log entry delete endpoint:", c.delete(f"{base}/{pets[0]}/medications/{med['id']}/log/{log[0]['id']}", headers=A).status_code)
c.patch(f"{base}/{pets[0]}/medications/{med['id']}", json={"active": False}, headers=A)
print("give on inactive medication:", c.post(f"{base}/{pets[0]}/medications/{med['id']}/give", headers=A).status_code)
from app.models import MedicationLog
s = H.session(); before = s.query(MedicationLog).filter_by(medication_id=med["id"]).count(); s.close()
print("Ben (non-admin member) deletes medication:", c.delete(f"{base}/{pets[0]}/medications/{med['id']}", headers=B).status_code)
s = H.session(); after = s.query(MedicationLog).filter_by(medication_id=med["id"]).count(); s.close()
print(f"medication_logs before={before} after={after}")

print("== S4 care tasks ==")
import datetime as dt
from app.models import PetCareTask
task = c.post(f"{base}/{pets[1]}/care-tasks/", json={"name":"Wurmkur","interval_days":30,"next_due_at":"2026-10-01"}, headers=A).json()
res = H.parallel(lambda i: mk().post(f"{base}/{pets[1]}/care-tasks/{task['id']}/complete", headers=[A,B][i]).json()["next_due_at"], 2)
print("parallel complete -> next_due:", res)
s = H.session(); t = s.get(PetCareTask, task["id"]); t.notified_at = dt.datetime.now(dt.timezone.utc); s.commit(); s.close()
r = c.patch(f"{base}/{pets[1]}/care-tasks/{task['id']}", json={"interval_days": 7}, headers=A).json()
print("interval 30->7 : next_due", r["next_due_at"], "notified_at", r["notified_at"] is not None)
r = c.patch(f"{base}/{pets[1]}/care-tasks/{task['id']}", json={"next_due_at": "2026-10-20"}, headers=A).json()
print("move due -> notified_at reset:", r["notified_at"] is None)
print("pet delete by member Ben:", c.delete(f"{base}/{pets[0]}", headers=B).status_code)
