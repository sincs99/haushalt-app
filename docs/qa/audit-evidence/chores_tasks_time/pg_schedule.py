"""Schedule edits, pause/reactivate, completed-future blocking, L-09, ex-member, push for paused chore."""
import sys; sys.path.insert(0, ".")
import tt; H = tt.H
from datetime import datetime, timezone, date, timedelta
H.fresh_db("ctt_sched")
tt.install()
def at(y,m,d,h=10):  # local Zurich 10:00 approx (UTC+2 in Oct)
    tt.set_now(datetime(y,m,d,h-2,0,tzinfo=timezone.utc))
c = H.client()
hid, users, toks = H.household(["Anna", "Ben", "Carla"])
A = H.auth(toks[0]); base = f"/api/households/{hid}"
name = {str(u): n for u, n in zip(users, ["Anna","Ben","Carla"])}; ALLN = dict(name)
def asg(chore_id=None):
    r = c.get(f"{base}/chores/assignments", headers=A); assert r.status_code == 200, r.text
    return [(a["due_date"], name.get(a["assigned_user_id"], a["assigned_user_id"]), bool(a["completed_at"])) for a in r.json() if chore_id is None or a["chore_id"] == chore_id]
def mk(title, **kw):
    r = c.post(f"{base}/chores/", json={"title": title, "rotation_order": [str(u) for u in users], **kw}, headers=A); assert r.status_code == 201, r.text
    return r.json()["id"]

print("== 1. weekly Mon -> Wed edit on Sat 2026-10-10 (last assignment Mon 10-05 exists) ==")
at(2026,9,28)  # Mon
c1 = mk("Weekly", recurrence="weekly", weekday=0)
print("initial (on 09-28):", asg(c1))
at(2026,10,10)  # Sat
print("before edit (10-10):", asg(c1))
r = c.patch(f"{base}/chores/{c1}", json={"weekday": 2}, headers=A); print("patch", r.status_code, "anchor", r.json()["anchor_date"])
print("after edit:", asg(c1))

print("== 2. monthly 1st -> 8th edit on 10-10 ==")
at(2026,10,1)
c2 = mk("Monthly", recurrence="monthly", day_of_month=1)
print("initial:", asg(c2))
at(2026,10,10)
r = c.patch(f"{base}/chores/{c2}", json={"day_of_month": 8}, headers=A); print("patch", r.status_code, "anchor", r.json()["anchor_date"])
print("after edit:", asg(c2))

print("== 3. completed future assignment blocks new schedule ==")
at(2026,10,10)
c3 = mk("Early", recurrence="weekly", weekday=4)  # Fri 10-16
a = [x for x in c.get(f"{base}/chores/assignments", headers=A).json() if x["chore_id"] == c3]
print("initial:", [(x["due_date"]) for x in a])
c.post(f"{base}/chores/assignments/{a[0]['id']}/complete", headers=A)
r = c.patch(f"{base}/chores/{c3}", json={"weekday": 0}, headers=A); print("patch Fri->Mon anchor", r.json()["anchor_date"])
print("after edit (expect Mon 10-12 next):", asg(c3))

print("== 4. pause then reactivate after 6 weeks ==")
at(2026,10,10)
c4 = mk("Pause", recurrence="weekly", weekday=5)  # Sat -> today
print("initial:", asg(c4))
r = c.patch(f"{base}/chores/{c4}", json={"active": False}, headers=A); print("paused", r.status_code)
at(2026,11,21)
r = c.patch(f"{base}/chores/{c4}", json={"active": True}, headers=A); print("reactivated", r.status_code)
res = asg(c4); print("after reactivation on 11-21:", res)
print("overdue open right after reactivation:", [x for x in res if x[0] < "2026-11-21" and not x[2]])

print("== 5. paused chore: materialised assignment still pushed? ==")
at(2026,11,21)
c5 = mk("PausedPush", recurrence="weekly", weekday=1)  # Tue 11-24
print("initial:", asg(c5))
c.patch(f"{base}/chores/{c5}", json={"active": False}, headers=A)
import app.services.push_service as ps
sent = []
ps.send_to_users = lambda db, uids, b, household_id=None: (sent.append((b('de')['title'], b('de')['body'], [ALLN.get(str(u), str(u)) for u in uids])), 1)[1]
tt.set_now(datetime(2026,11,24,8,30,tzinfo=timezone.utc))  # 09:30 CET
db = H.session(); ps.process_chore_assignments(db, tt.NOW[0]); db.close()
print("pushes on 11-24:", [s for s in sent if s[1] == "PausedPush"])
r = c.get(f"{base}/dashboard/badge", headers=A); print("badge Anna", r.json())
r = c.get(f"{base}/tasks", headers=A); print("tasks containing PausedPush:", [t["due_date"] for t in r.json() if t["title"] == "PausedPush"])

print("== 6. L-09 rotation give-back with ex-member ==")
hid2, u2, t2 = H.household(["A","X","B"]); n2 = {str(u): n for u, n in zip(u2, ["A","X","B"])}
B2 = H.auth(t2[0]); base2 = f"/api/households/{hid2}"
at(2026,10,10)
r = c.post(f"{base2}/chores/", json={"title":"R","recurrence":"weekly","weekday":0,"rotation_order":[str(u) for u in u2]}, headers=B2); cid = r.json()["id"]
s = H.session(); from app.models import HouseholdMember
s.query(HouseholdMember).filter_by(household_id=hid2, user_id=u2[1]).delete(); s.commit(); s.close()
at(2026,10,12)
print("assignments:", [(a["due_date"], n2[a["assigned_user_id"]]) for a in c.get(f"{base2}/chores/assignments", headers=B2).json()])
r = c.patch(f"{base2}/chores/{cid}", json={"weekday": 2}, headers=B2)
print("after Mon->Wed:", [(a["due_date"], n2[a["assigned_user_id"]]) for a in c.get(f"{base2}/chores/assignments", headers=B2).json()])

print("== 7. member leaves with materialised future assignment ==")
hid3, u3, t3 = H.household(["P","Q"]); n3 = {str(u): n for u, n in zip(u3, ["P","Q"])}
P = H.auth(t3[0]); Q = H.auth(t3[1]); base3 = f"/api/households/{hid3}"; ALLN.update(n3)
at(2026,10,10)
r = c.post(f"{base3}/chores/", json={"title":"Trash","recurrence":"weekly","weekday":5,"rotation_order":[str(u3[1]), str(u3[0])]}, headers=P)
print("assignments:", [(a["due_date"], n3[a["assigned_user_id"]]) for a in c.get(f"{base3}/chores/assignments", headers=P).json()])
r = c.post(f"/api/households/leave", headers=H.auth(t3[1], hid3)); print("Q leaves", r.status_code, r.text[:120])
if r.status_code >= 400:
    r = c.post(f"{base3}/leave", headers=Q); print("Q leaves (alt)", r.status_code)
print("assignments after leave:", [(a["due_date"], n3.get(a["assigned_user_id"], a["assigned_user_id"])) for a in c.get(f"{base3}/chores/assignments", headers=P).json()])
print("badge P (today chore assigned to ex-member):", c.get(f"{base3}/dashboard/badge", headers=P).json())
print("dashboard chores P:", c.get(f"{base3}/dashboard", headers=P).json()["chores"])
sent.clear(); tt.set_now(datetime(2026,10,10,7,0,tzinfo=timezone.utc)); db = H.session(); ps.process_chore_assignments(db, tt.NOW[0]); db.close()
print("push for Trash:", [s for s in sent if s[1] == "Trash"])
print("tasks for P:", [(t["title"], t["due_date"], n3.get(t["assigned_to_user_id"] or "", t["assigned_to_user_id"])) for t in c.get(f"{base3}/tasks", headers=P).json()])
print("== 8. reassign after notification ==")
a = [x for x in c.get(f"{base3}/chores/assignments", headers=P).json() if x["due_date"] == "2026-10-10"][0]
r = c.patch(f"{base3}/chores/assignments/{a['id']}", json={"assigned_user_id": str(u3[0])}, headers=P); print("reassign to P", r.status_code)
sent.clear(); db = H.session(); ps.process_chore_assignments(db, tt.NOW[0]); db.close()
print("push after reassign:", [s for s in sent if s[1] == "Trash"])
print("badge P now:", c.get(f"{base3}/dashboard/badge", headers=P).json())
