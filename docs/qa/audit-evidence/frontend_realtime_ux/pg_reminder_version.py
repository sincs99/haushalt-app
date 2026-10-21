import sys, datetime as dt
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("fe_rt_2")
c = H.client(); hid, users, toks = H.household(["Anna","Ben"]); A = H.auth(toks[0]); base=f"/api/households/{hid}/todos"
t = c.post(f"{base}/", json={"title":"Velo"}, headers=A).json(); print("todo v", t["version"])
when = (dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1)).isoformat()
r = c.post(f"{base}/{t['id']}/reminders/", json={"remind_at": when}, headers=A); print("add reminder", r.status_code)
ev = [a for a,k in H.emits if a[1]=="todo_updated"]; print("todo_updated after add: version", ev[-1][2]["version"], "reminders", len(ev[-1][2]["reminders"]))
rid = r.json()["id"]
r = c.delete(f"{base}/{t['id']}/reminders/{rid}", headers=A); print("delete reminder", r.status_code)
ev = [a for a,k in H.emits if a[1]=="todo_updated"]; print("todo_updated after delete: version", ev[-1][2]["version"], "reminders", len(ev[-1][2]["reminders"]))
