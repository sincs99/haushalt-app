"""Effects of member removal / leave on dependent entities (PG)."""
import sys, uuid, datetime as dt
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("hh_life")
import logging; logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from app.main import app
from app.models import *
c = TestClient(app, raise_server_exceptions=False)
A = lambda t: H.auth(t)
def P(label, r): print(f"{label}: {r.status_code} {r.text[:160]}")

hid, (ua, ub, uc), (ta, tb, tc) = H.household(["Anna", "Ben", "Carla"])
base = f"/api/households/{hid}"
s = H.session(); h = s.get(Household, hid); h.invite_code_expires_at = dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=3); s.commit(); s.close()

print("### 1. Widget token of a member who leaves, then rejoins")
w = c.post(f"{base}/widget-token", headers=A(tb)).json()["token"]
P("B widget summary while member", c.get("/api/widget/summary", headers={"Authorization": f"Bearer {w}"}))
P("B leaves", c.post(f"{base}/leave", headers=A(tb)))
s = H.session(); print("widget_tokens rows for B after leave (before any widget call):", s.query(WidgetToken).filter_by(user_id=ub).count()); code = s.get(Household, hid).invite_code; s.close()
P("B rejoins with (unrotated) invite code", c.post("/api/households/join", json={"invite_code": code}, headers=A(tb)))
P("old widget key after rejoin", c.get("/api/widget/summary", headers={"Authorization": f"Bearer {w}"}))
P("A removes B", c.delete(f"{base}/members/{ub}", headers=A(ta)))
P("old widget key after removal", c.get("/api/widget/summary", headers={"Authorization": f"Bearer {w}"}))

print("\n### 2. Stale (still valid) access JWT of removed member B")
for path in ["/todos/", "/expenses/", "/members", "/invite-code", "/widget-token", "/dashboard", "/finance-summary"]:
    P(f"  GET {path}", c.get(base + path, headers=A(tb)))
P("  POST todo", c.post(f"{base}/todos/", json={"title": "x"}, headers=A(tb)))
P("  /api/auth/me still lists household?", c.get("/api/auth/me", headers=A(tb)))

print("\n### 3. Dependent data of an ex-member (re-add B as fresh member D to test)")
ud, td = H.add_member(hid, "Dora")
# recurring bill with default payer D
rb = c.post(f"{base}/recurring-bills/", json={"name": "Miete", "amount_rappen": 300000, "day_of_month": 1, "paid_by_user_id": str(ud)}, headers=A(ta))
P("create bill payer=D", rb); bill_id = rb.json().get("id")
# todo assigned to D with reminder in 2s
td_r = c.post(f"{base}/todos/", json={"title": "Dora-Todo", "assigned_to_user_id": str(ud), "due_date": dt.date.today().isoformat()}, headers=A(ta)); todo_id = td_r.json()["id"]
P("todo for D", td_r)
# shopping item assigned to D (needs a list)
lst = c.get(f"{base}/shopping-lists/", headers=A(ta)); P("lists", lst)
# event with participants D
cal_id = c.post(f"{base}/calendars/", json={"name":"Allg","color":"#5B8DEF"}, headers=A(ta)).json()["id"]
ev = c.post(f"{base}/events/", json={"calendar_id": cal_id, "title": "Essen", "starts_at": "2026-12-01T18:00:00", "participant_ids": [str(ud)]}, headers=A(ta)); P("event participants=[D]", ev)
# expense paid by D, split A,C,D -> D is owed money
ex = c.post(f"{base}/expenses/", json={"description": "Einkauf", "amount_rappen": 9000, "paid_by_user_id": str(ud), "split_type": "even"}, headers=A(ta)); P("expense paid by D", ex)
# widget + push subscription for D
s = H.session(); s.add(PushSubscription(user_id=ud, endpoint=f"https://fcm.googleapis.com/x/{uuid.uuid4()}", p256dh="k", auth="a", locale="de"))
s.add(PushSubscription(user_id=ua, endpoint=f"https://fcm.googleapis.com/x/{uuid.uuid4()}", p256dh="k", auth="a", locale="de")); s.commit(); s.close()

P("D leaves", c.post(f"{base}/leave", headers=A(td)))
r = c.post(f"{base}/recurring-bills/{bill_id}/book", headers=A(ta)); P("book bill w/ default payer = ex-member", r)
r = c.get(f"{base}/finance-summary", headers=A(ta)); print("finance-summary pending bill paid_by:", [b["paid_by_user_id"] for b in r.json()["pending_bills"]], "(ex-member D =", ud, ")")
r = c.get(f"{base}/recurring-bills/", headers=A(ta)); print("bill list paid_by:", [b.get("paid_by_user_id") for b in r.json()])
r = c.patch(f"{base}/recurring-bills/{bill_id}", json={"name": "Miete neu"}, headers=A(ta)); P("rename bill (payer unchanged ex-member)", r)
r = c.get(f"{base}/expenses/balances", headers=A(ta)); print("balances:", r.text[:300])
r = c.get(f"{base}/events/?from=2026-11-01&to=2026-12-31", headers=A(ta)); print("events:", r.status_code, r.text[:200])
r = c.get(f"{base}/todos/", headers=A(ta)); print("todo assignee after leave:", [(t["title"], t["assigned_to_user_id"]) for t in r.json()])
r = c.patch(f"{base}/todos/{todo_id}", json={"title": "Dora-Todo2"}, headers=A(ta)); P("edit todo still assigned to ex-member", r)

# attention/badge
r = c.get(f"{base}/dashboard/badge", headers=A(ta)); P("badge for A (todo due today assigned to ex-member)", r)
r = c.get(f"{base}/dashboard/badge", headers=A(tc)); P("badge for C", r)

# push: todo reminder for ex-member's todo -> who receives?
import app.services.push_service as ps
sent = []
ps.webpush = lambda subscription_info, **k: sent.append(subscription_info["endpoint"])
s = H.session()
s.add(TodoReminder(household_id=hid, todo_id=uuid.UUID(todo_id), remind_at=dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=1))); s.commit()
n = ps.process_todo_reminders(s, dt.datetime.now(dt.timezone.utc))
subs = {p.endpoint: p.user_id for p in s.query(PushSubscription).all()}
print("push recipients for reminder of ex-member's todo:", [("A" if subs[e]==ua else "D(ex)" if subs[e]==ud else subs[e]) for e in sent])
s.close()

print("\n### 4. Assign to non-member / outsider (no validation?)")
ho, (uo,), (to,) = H.household(["Outsider"])
P("todo assigned to user of ANOTHER household", c.post(f"{base}/todos/", json={"title": "fremd", "assigned_to_user_id": str(uo)}, headers=A(ta)))
P("todo assigned to random uuid", c.post(f"{base}/todos/", json={"title": "random", "assigned_to_user_id": str(uuid.uuid4())}, headers=A(ta)))
P("event participant outsider", c.post(f"{base}/events/", json={"calendar_id": cal_id, "title": "x", "starts_at": "2026-12-02T18:00:00", "participant_ids": [str(uo)]}, headers=A(ta)))

print("\n### 5. Members list / UI name resolution for ex-member")
print("members:", [m["display_name"] for m in c.get(f"{base}/members", headers=A(ta)).json()])
