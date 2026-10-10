"""Todos: due-date classification across /tasks, /dashboard, /badge, /widget; tz west of UTC; reminders lifecycle; claim race."""
import sys; sys.path.insert(0, ".")
import tt; H = tt.H
from datetime import datetime, timezone, timedelta
from collections import Counter
H.fresh_db("ctt_todos")
tt.install()
c = H.client()

def scenario(tz, now_utc, label):
    tt.set_now(now_utc)
    hid, users, toks = H.household(["Anna", "Ben"], tz=tz)
    A = H.auth(toks[0]); base = f"/api/households/{hid}"
    local_today = now_utc.astimezone(__import__("zoneinfo").ZoneInfo(tz)).date()
    for title, d in [("due_yesterday", local_today - timedelta(days=1)), ("due_today", local_today), ("due_tomorrow", local_today + timedelta(days=1))]:
        r = c.post(f"{base}/todos/", json={"title": title, "due_date": d.isoformat()}, headers=A); assert r.status_code == 201, r.text
    stored = {t["title"]: t["due_date"] for t in c.get(f"{base}/todos/", headers=A).json()}
    # Real clock is used by dashboard 'now' for reminders only; today comes from patched today_in_tz
    dash = c.get(f"{base}/dashboard", headers=A).json()["todos"]
    tasks = {t["title"]: t["due_date"] for t in c.get(f"{base}/tasks", headers=A).json()}
    import app.services.attention as at
    s = H.session(); from app.models import Household
    items = at.due_items(s, s.get(Household, hid), users[0]); s.close()
    print(f"--- {label}: tz={tz} local_today={local_today}")
    print("  stored due_date:", stored)
    print("  /tasks due_date:", tasks)
    print("  dashboard overdue_count:", dash["overdue_count"], "items:", [(i["title"], i["is_overdue"]) for i in dash["items"]])
    print("  attention/badge/widget:", [(i.title, "overdue" if i.overdue else "today") for i in items])

# Zurich, 10:00 local
scenario("Europe/Zurich", datetime(2026,10,10,8,0,tzinfo=timezone.utc), "Zurich morning")
# Zurich 00:30 local (22:30 UTC previous day)
scenario("Europe/Zurich", datetime(2026,10,9,22,30,tzinfo=timezone.utc), "Zurich 00:30")
# New York, 10:00 local
scenario("America/New_York", datetime(2026,10,10,14,0,tzinfo=timezone.utc), "New York morning")
# Auckland (UTC+13), 10:00 local
scenario("Pacific/Auckland", datetime(2026,10,9,21,0,tzinfo=timezone.utc), "Auckland morning")

print("=== reminders lifecycle ===")
import app.services.push_service as ps
sent = []
ps.send_to_users = lambda db, uids, b, household_id=None: (sent.append((b('de')['body'], len(uids))), 1)[1]
hid, users, toks = H.household(["R1", "R2"]); A = H.auth(toks[0]); base = f"/api/households/{hid}"
now = datetime.now(timezone.utc)
tid = c.post(f"{base}/todos/", json={"title": "T-reopen"}, headers=A).json()["id"]
r = c.post(f"{base}/todos/{tid}/reminders/", json={"remind_at": (now + timedelta(hours=5)).isoformat()}, headers=A); print("add reminder", r.status_code)
c.patch(f"{base}/todos/{tid}", json={"is_done": True}, headers=A)
c.patch(f"{base}/todos/{tid}", json={"is_done": False}, headers=A)
t = [x for x in c.get(f"{base}/todos/", headers=A).json() if x["id"] == tid][0]
print("after done+reopen (undo within seconds): future reminder notified_at =", t["reminders"][0]["notified_at"])
db = H.session(); ps.process_todo_reminders(db, now + timedelta(hours=5, minutes=1)); db.close()
print("push at reminder time after reopen:", [s for s in sent if s[0] == "T-reopen"])
dash = c.get(f"{base}/dashboard", headers=A).json()["upcoming_reminders"]
print("dashboard upcoming_reminders after reopen:", [d["todo_title"] for d in dash])

tid2 = c.post(f"{base}/todos/", json={"title": "T-del"}, headers=A).json()["id"]
c.post(f"{base}/todos/{tid2}/reminders/", json={"remind_at": (now + timedelta(hours=1)).isoformat()}, headers=A)
c.delete(f"{base}/todos/{tid2}", headers=A)
s = H.session(); from app.models import TodoReminder
print("reminders left for deleted todo:", s.query(TodoReminder).filter_by(todo_id=tid2).count()); s.close()

# reminder to assignee who left
hid4, u4, t4 = H.household(["S1", "S2", "S3"]); base4 = f"/api/households/{hid4}"
tid3 = c.post(f"{base4}/todos/", json={"title": "T-ex", "assigned_to_user_id": str(u4[1])}, headers=H.auth(t4[0])).json()["id"]
c.post(f"{base4}/todos/{tid3}/reminders/", json={"remind_at": (now + timedelta(minutes=2)).isoformat()}, headers=H.auth(t4[0]))
print("leave S2:", c.post(f"{base4}/leave", headers=H.auth(t4[1])).status_code)
sent.clear(); db = H.session(); ps.process_todo_reminders(db, now + timedelta(minutes=3)); db.close()
print("reminder push for todo of ex-member -> recipients count:", sent)

# assign todo to non-member on create
hid5, u5, t5 = H.household(["V1"]); other, _ = H.add_member(hid4, "Other")
r = c.post(f"/api/households/{hid5}/todos/", json={"title": "foreign", "assigned_to_user_id": str(other)}, headers=H.auth(t5[0]))
print("create todo assigned to user of another household:", r.status_code)
r2 = c.patch(f"/api/households/{hid5}/todos/{r.json().get('id')}", json={"assigned_to_user_id": str(other)}, headers=H.auth(t5[0])) if r.status_code == 201 else None
print("patch assign to foreign user:", r2 and r2.status_code)

print("=== claim race on PG ===")
hid6, u6, t6 = H.household([f"M{i}" for i in range(8)]); base6 = f"/api/households/{hid6}"
tid6 = c.post(f"{base6}/todos/", json={"title": "claim me"}, headers=H.auth(t6[0])).json()["id"]
from fastapi.testclient import TestClient
from app.main import app
cl = [TestClient(app) for _ in range(8)]
res = H.parallel(lambda i: cl[i].post(f"{base6}/todos/{tid6}/claim", headers=H.auth(t6[i])).status_code, 8)
print("claim statuses:", Counter(res))
print("todo_updated emits for claim:", sum(1 for e in H.emits if e[0][1] == "todo_updated" and e[0][2]["id"] == tid6))

print("=== reminder past / DST nonexistent local time ===")
r = c.post(f"{base}/todos/{tid}/reminders/", json={"remind_at": "2027-03-28T02:30:00"}, headers=A)
print("naive 02:30 on DST day ->", r.status_code, r.json().get("remind_at"))
