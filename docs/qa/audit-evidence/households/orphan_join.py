"""Consequences of the race outcomes: orphan household (0 members) and household without admin."""
import sys, uuid, datetime as dt
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("hh_orphan")
import logging; logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from app.main import app
from app.models import *
from app.core.security import create_access_token
c = TestClient(app, raise_server_exceptions=False)

# produce orphan via the real race (retry until it happens)
for attempt in range(30):
    hid, users, toks = H.household(["A", "B"])
    s = H.session(); h = s.get(Household, hid); h.invite_code_expires_at = dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=7); code = h.invite_code; s.commit(); s.close()
    c.post(f"/api/households/{hid}/todos/", json={"title": "geheime Notiz von A"}, headers=H.auth(toks[0]))
    cs = [TestClient(app, raise_server_exceptions=False) for _ in range(2)]
    H.parallel(lambda i: cs[i].post(f"/api/households/{hid}/leave", headers=H.auth(toks[i])), 2)
    s = H.session(); exists = s.get(Household, hid) is not None; n = s.query(HouseholdMember).filter_by(household_id=hid).count(); s.close()
    if exists and n == 0:
        print(f"orphan produced on attempt {attempt+1}: household exists, 0 members")
        break
s = H.session(); u = User(id=uuid.uuid4(), email=f"x-{uuid.uuid4().hex[:6]}@ex.com", password_hash="x", display_name="X"); s.add(u); s.commit(); xt = create_access_token(str(u.id)); s.close()
r = c.post("/api/households/join", json={"invite_code": code}, headers=H.auth(xt)); print("outsider joins orphan with code:", r.status_code, r.text[:100])
r = c.get(f"/api/households/{hid}/todos/", headers=H.auth(xt)); print("outsider sees old data:", r.status_code, [t["title"] for t in r.json()])
r = c.get(f"/api/households/{hid}/members", headers=H.auth(xt)); print("members/roles:", r.json())
r = c.patch(f"/api/households/{hid}", json={"name": "neu"}, headers=H.auth(xt)); print("rename (admin fn):", r.status_code, r.text[:90])
r = c.post(f"/api/households/{hid}/invite-code/rotate", headers=H.auth(xt)); print("rotate (admin fn):", r.status_code)
r = c.post(f"/api/households/{hid}/leave", headers=H.auth(xt)); print("sole member leaves -> household deleted?", r.status_code)
s = H.session(); print("household exists after:", s.get(Household, hid) is not None); s.close()
