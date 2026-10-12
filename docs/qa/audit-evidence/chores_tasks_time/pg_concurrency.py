"""Concurrent materialisation on PG: GET /assignments, /tasks, scheduler, in parallel."""
import sys; sys.path.insert(0, ".")
import tt; H = tt.H
from datetime import datetime, timezone, date
from collections import Counter
H.fresh_db("ctt_conc")
tt.install()
tt.set_now(datetime(2026, 10, 10, 10, 0, tzinfo=timezone.utc))
c = H.client()
hid, users, toks = H.household(["Anna", "Ben", "Carla"])
A = H.auth(toks[0])
base = f"/api/households/{hid}"
for i in range(5):
    r = c.post(f"{base}/chores/", json={"title": f"C{i}", "recurrence": "weekly", "weekday": i, "rotation_order": [str(u) for u in users]}, headers=A)
    assert r.status_code == 201, r.text

from fastapi.testclient import TestClient
from app.main import app
clients = [TestClient(app) for _ in range(12)]
def hit(i):
    path = ["/chores/assignments", "/tasks", "/chores/assignments"][i % 3]
    r = clients[i].get(base + path, headers=H.auth(toks[i % 3]))
    return r.status_code, len(r.json()) if r.status_code == 200 else r.text[:200]
res = H.parallel(hit, 12)
print("statuses:", Counter(r[0] if isinstance(r, tuple) else type(r).__name__ for r in res))
print("results:", res)
s = H.session()
from app.models import ChoreAssignment, Chore
rows = s.query(ChoreAssignment.chore_id, ChoreAssignment.due_date).all()
print("assignments:", len(rows), "dupes:", len(rows) - len(set(rows)))
for ch in s.query(Chore).order_by(Chore.title):
    n = s.query(ChoreAssignment).filter_by(chore_id=ch.id).count()
    print(ch.title, "assignments", n, "next_rotation_index", ch.next_rotation_index)
created = [e for e in H.emits if e[0][1] == "chore_assignment_created"]
print("chore_assignment_created emits:", len(created), "distinct ids:", len({e[0][2]['id'] for e in created}))
# Scheduler path in parallel with API (simulating 2 workers + users)
import app.services.push_service as ps
sent = []
ps.send_to_users = lambda db, uids, b, household_id=None: (sent.append(tuple(uids)), 1)[1]
tt.set_now(datetime(2026, 10, 19, 7, 30, tzinfo=timezone.utc))  # Mon 09:30 local, new materialisation needed
ps._chores_materialized.clear()
def mixed(i):
    if i < 4:
        db = H.session()
        try:
            return ("sched", ps.process_chore_assignments(db, tt.NOW[0]))
        finally: db.close()
    r = clients[i].get(base + "/chores/assignments", headers=A)
    return ("api", r.status_code)
res2 = H.parallel(mixed, 10)
print("mixed:", res2)
s.close(); s = H.session()
rows = s.query(ChoreAssignment.chore_id, ChoreAssignment.due_date).all()
print("after mixed: assignments", len(rows), "dupes", len(rows) - len(set(rows)))
print("pushes sent (per assignment claim):", len(sent), sent and Counter(sent))
for ch in s.query(Chore).order_by(Chore.title):
    n = s.query(ChoreAssignment).filter_by(chore_id=ch.id).count()
    print(ch.title, "assignments", n, "next_rotation_index", ch.next_rotation_index)
print("emit events:", Counter(e[0][1] if len(e[0])>1 else e for e in H.emits))
