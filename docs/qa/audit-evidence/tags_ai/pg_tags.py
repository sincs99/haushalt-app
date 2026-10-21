"""PG audit of tag actions (tags_ai area). Read-only wrt repo."""
import sys, uuid, datetime as dt
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("tagsai_tags")
from app.models import (Pet, PetCareTask, Plant, PlantCareTask, PlantCareLog, Chore, ChoreAssignment,
                        Todo, FeedingLog, Tag, Household)
from app.services.chore_scheduler import today_in_tz
c = H.client()
hid, users, toks = H.household(["Anna", "Ben", "Carla"])
A = H.auth(toks[0]); B = H.auth(toks[1])
today = today_in_tz("Europe/Zurich")

def add(*objs):
    s = H.session(); ids = []
    for o in objs: s.add(o)
    s.commit(); ids = [o.id for o in objs]; s.close(); return ids

def mktag(target_type, action, target_id=None, hh=hid, hdr=A):
    r = c.post(f"/api/households/{hh}/tags/", json={"label": action, "target_type": target_type, "action": action,
               "target_id": str(target_id) if target_id else None}, headers=hdr)
    assert r.status_code == 201, r.text
    return r.json()["token"]

def ex(tok, hdr=A, body=None):
    r = c.post(f"/api/tags/{tok}/execute", json=body, headers=hdr)
    return r.status_code, (r.json() if r.headers.get("content-type","").startswith("application/json") else r.text)

def rs(tok, hdr=A):
    r = c.post(f"/api/tags/resolve/{tok}", headers=hdr)
    return r.status_code, r.json()

def q(fn):
    s = H.session()
    try: return fn(s)
    finally: s.close()

print("=== T1 chore: sequential double scan with backlog ===")
chore_id, = add(Chore(household_id=hid, title="Bad putzen", recurrence="weekly", weekday=today.weekday(),
                      rotation_order=[str(u) for u in users], anchor_date=today - dt.timedelta(days=14)))
tok = mktag("chore", "chore.assignment.done", chore_id)
st, res = rs(tok); print("resolve:", st, res["details"]["due_date"], res["can_execute"])
for i in range(3):
    st, r = ex(tok); print(f"execute#{i+1}:", st, r.get("changed") if isinstance(r, dict) else r,
                         r.get("result", {}).get("assignment", {}).get("due_date") if isinstance(r, dict) else "")
rows = q(lambda s: [(a.due_date.isoformat(), a.completed_at is not None) for a in s.query(ChoreAssignment).filter_by(chore_id=chore_id).order_by(ChoreAssignment.due_date)])
print("assignments (due, done):", rows)

print("=== T2 chore: two parallel scans ===")
chore2, = add(Chore(household_id=hid, title="Küche", recurrence="weekly", weekday=today.weekday(),
                    rotation_order=[str(u) for u in users], anchor_date=today - dt.timedelta(days=14)))
tok2 = mktag("chore", "chore.assignment.done", chore2)
rs(tok2)  # materialize
out = H.parallel(lambda i: ex(tok2, hdr=A if i == 0 else B), 2)
for o in out: print("parallel:", o[0], o[1].get("changed") if isinstance(o[1], dict) else o[1], o[1].get("result", {}).get("assignment", {}).get("due_date") if isinstance(o[1], dict) else "")
rows = q(lambda s: [(a.due_date.isoformat(), a.completed_at is not None) for a in s.query(ChoreAssignment).filter_by(chore_id=chore2).order_by(ChoreAssignment.due_date)])
print("assignments:", rows)

print("=== T3 chore: resolve->(app completes)->execute drift ===")
chore3, = add(Chore(household_id=hid, title="Müll", recurrence="weekly", weekday=today.weekday(),
                    rotation_order=[str(u) for u in users], anchor_date=today - dt.timedelta(days=14)))
tok3 = mktag("chore", "chore.assignment.done", chore3)
st, res = rs(tok3); shown = res["details"]["assignment_id"]; print("resolve shows", res["details"]["due_date"], shown)
r = c.post(f"/api/households/{hid}/chores/assignments/{shown}/complete", headers=B); print("Ben completes via app:", r.status_code)
st, r = ex(tok3); print("execute after:", st, r.get("changed"), "completed due_date", r["result"]["assignment"]["due_date"], "same as shown?", r["result"]["assignment"]["id"] == shown)

print("=== T4 feed: parallel single-pet feed (X) + feed-all ===")
hid2, users2, toks2 = H.household(["Dora", "Emil"])
A2 = H.auth(toks2[0]); B2 = H.auth(toks2[1])
px, py, pz = add(Pet(household_id=hid2, name="X"), Pet(household_id=hid2, name="Y"), Pet(household_id=hid2, name="Z"))
tx = mktag("pet", "pet.feed", px, hh=hid2, hdr=A2); tall = mktag("pet", "pet.feed", None, hh=hid2, hdr=A2)
for attempt in range(6):
    # reset feedings
    s = H.session(); s.query(FeedingLog).filter_by(household_id=hid2).delete(); s.commit(); s.close()
    out = H.parallel(lambda i: ex(tx, A2, {"slot": "morning"}) if i == 0 else ex(tall, B2, {"slot": "morning"}), 2)
    fed = q(lambda s: sorted(p.name for p in s.query(Pet).join(FeedingLog, FeedingLog.pet_id == Pet.id).filter(FeedingLog.slot == "morning").all()))
    print(f"attempt {attempt}: single={out[0][0]} changed={out[0][1].get('changed') if isinstance(out[0][1], dict) else out[0][1]}; feed-all={out[1][0]} changed={out[1][1].get('changed') if isinstance(out[1][1], dict) else out[1][1]}; fed pets now={fed}")

print("=== T5 feed-all parallel x3 ===")
s = H.session(); s.query(FeedingLog).filter_by(household_id=hid2).delete(); s.commit(); s.close()
out = H.parallel(lambda i: ex(tall, A2 if i % 2 == 0 else B2, {"slot": "evening"}), 3)
print([(o[0], o[1].get("changed"), len(o[1]["result"]["feedings"])) for o in out])
print("evening logs:", q(lambda s: s.query(FeedingLog).filter_by(household_id=hid2, slot="evening").count()))

print("=== T6 pet.feed single parallel x3 ===")
s = H.session(); s.query(FeedingLog).filter_by(household_id=hid2).delete(); s.commit(); s.close()
out = H.parallel(lambda i: ex(tx, A2, {"slot": "morning"}), 3)
print([(o[0], (o[1].get("detail") or {}).get("code") if isinstance(o[1], dict) and "detail" in o[1] else o[1].get("changed")) for o in out])
print("feedings X morning:", q(lambda s: s.query(FeedingLog).filter_by(pet_id=px, slot="morning").count()))

print("=== T7 plant.water all: parallel x2 ===")
pl1, pl2 = add(Plant(household_id=hid, name="Ficus"), Plant(household_id=hid, name="Monstera"))
w1, w2 = add(PlantCareTask(household_id=hid, plant_id=pl1, care_type="water", interval_days=7, next_due_at=today - dt.timedelta(days=1)),
             PlantCareTask(household_id=hid, plant_id=pl2, care_type="water", interval_days=7, next_due_at=today))
twall = mktag("plant", "plant.water", None)
H.emits.clear()
out = H.parallel(lambda i: ex(twall, A if i == 0 else B), 2)
print([(o[0], o[1].get("changed"), len(o[1]["result"]["logs"])) for o in out])
print("logs:", q(lambda s: s.query(PlantCareLog).filter_by(household_id=hid).count()), "emits plant_care_logged:", sum(1 for a, k in H.emits if a[1] == "plant_care_logged"))
st, r = ex(twall); print("sequential 3rd scan:", st, r.get("changed"))

print("=== T8 plant.water single target: 2 water tasks, one not due; and repeated ===")
pl3, = add(Plant(household_id=hid, name="Kaktus"))
wa, wb = add(PlantCareTask(household_id=hid, plant_id=pl3, care_type="water", interval_days=30, next_due_at=today + dt.timedelta(days=20), label="Winter"),
             PlantCareTask(household_id=hid, plant_id=pl3, care_type="water", interval_days=7, next_due_at=today))
t1 = mktag("plant", "plant.water", pl3)
st, res = rs(t1); print("resolve:", st, res["can_execute"], res["details"]["next_due_at"])
for i in range(2):
    st, r = ex(t1); print(f"exec#{i+1}", st, r.get("changed"), len(r["result"]["logs"]))
print("Winter task next_due (was today+20):", q(lambda s: s.get(PlantCareTask, wa).next_due_at.isoformat()), "logs on plant:", q(lambda s: s.query(PlantCareLog).filter_by(plant_id=pl3).count()))

print("=== T9 plant.care_task.done parallel x2 ===")
fz, = add(PlantCareTask(household_id=hid, plant_id=pl1, care_type="fertilize", interval_days=30, next_due_at=today))
tf = mktag("plant_care_task", "plant.care_task.done", fz)
out = H.parallel(lambda i: ex(tf, A if i == 0 else B), 2)
print([(o[0], o[1].get("changed")) for o in out], "logs:", q(lambda s: s.query(PlantCareLog).filter_by(care_task_id=fz).count()))

print("=== T10 pet.care_task.done twice ===")
pc, = add(PetCareTask(household_id=hid2, pet_id=px, name="Wurmkur", interval_days=90, next_due_at=today))
tpc = mktag("pet_care_task", "pet.care_task.done", pc, hh=hid2, hdr=A2)
st, res = rs(tpc, A2); print("resolve1 can_execute", res["can_execute"])
print("exec1", ex(tpc, A2)[1]["changed"])
st, res = rs(tpc, A2); print("resolve2 can_execute", res["can_execute"], "next_due", res["details"]["next_due_at"])
print("exec2", ex(tpc, A2)[1]["changed"])

print("=== T11 todo.done parallel x2 ===")
td, = add(Todo(household_id=hid, title="Pflanzen giessen"))
tt = mktag("todo", "todo.done", td)
H.emits.clear()
out = H.parallel(lambda i: ex(tt, A if i == 0 else B), 2)
print([(o[0], o[1].get("changed")) for o in out], "todo_updated emits:", sum(1 for a, k in H.emits if a[1] == "todo_updated"),
      "version:", q(lambda s: s.get(Todo, td).version))

print("=== T12 household membership / disabled / rotated / deleted ===")
# user only in hid2 scans tag of hid
print("Dora (only HH2) resolve HH1 tag:", rs(tt, A2)[0], ex(tt, A2)[0])
# user in both: Anna joins hid2
uid_both, tok_both = H.add_member(hid2, "Both")
from app.models import HouseholdMember
s = H.session(); s.add(HouseholdMember(household_id=hid, user_id=uid_both, role="member")); s.commit(); s.close()
st, res = rs(tx, H.auth(tok_both)); print("user in both resolve HH2 tag:", st, res["household_id"] == str(hid2))
tag_id = q(lambda s: s.query(Tag).filter_by(token=tt).first().id)
c.patch(f"/api/households/{hid}/tags/{tag_id}", json={"enabled": False}, headers=A)
print("disabled:", rs(tt)[0], ex(tt)[0])
c.patch(f"/api/households/{hid}/tags/{tag_id}", json={"enabled": True}, headers=A)
r = c.post(f"/api/households/{hid}/tags/{tag_id}/regenerate-token", headers=A); newtok = r.json()["token"]
print("old token after rotation:", rs(tt)[0], ex(tt)[0], "new:", rs(newtok)[0])
c.delete(f"/api/households/{hid}/todos/{td}", headers=A)
print("deleted target:", rs(newtok)[0], rs(newtok)[1].get("detail", {}).get("code"))
# member removed? Ben leaves -> tag scan 403
print("use_count after failures:", q(lambda s: s.get(Tag, tag_id).use_count))

print("=== T13 pet.feed single: describe blocked when default slot fed; user cannot choose other slot ===")
s = H.session(); s.query(FeedingLog).filter_by(household_id=hid2).delete(); s.commit(); s.close()
from app.services.tag_actions import default_feeding_slot
slot = q(lambda s: default_feeding_slot(s.get(Household, hid2)))
ex(tx, A2, {"slot": slot})
st, res = rs(tx, A2); print("default slot", slot, "-> resolve can_execute", res["can_execute"], res["reason"])
