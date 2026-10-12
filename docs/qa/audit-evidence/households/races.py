"""PG races for household membership lifecycle."""
import sys, uuid, collections, datetime as dt
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("hh_races")
from fastapi.testclient import TestClient
from app.main import app
from app.models import Household, HouseholdMember, RefreshToken, User
from sqlalchemy import func
import logging; logging.disable(logging.CRITICAL)

def mk():
    return TestClient(app, raise_server_exceptions=False)

N = 15

def state(hid):
    s = H.session()
    h = s.get(Household, hid)
    ms = s.query(HouseholdMember).filter_by(household_id=hid).all()
    r = (h is not None, len(ms), sum(1 for m in ms if m.role == "admin"))
    s.close(); return r

def race(label, setup, ops):
    out = collections.Counter(); codes = collections.Counter()
    for _ in range(N):
        ctx = setup()
        clients = [mk() for _ in ops]
        res = H.parallel(lambda i: ops[i](clients[i], ctx), len(ops))
        codes[tuple(getattr(r, "status_code", repr(r)[:40]) for r in res)] += 1
        out[ctx["check"]()] += 1
    print(f"\n== {label}")
    print("  status codes:", dict(codes))
    print("  outcomes:", dict(out))

# 1) Admin A and senior member B (would be promoted) leave concurrently; C stays.
def s1():
    hid, users, toks = H.household(["A", "B", "C"])
    return {"hid": hid, "toks": toks, "check": lambda: "exists=%s members=%d admins=%d" % state(hid)}
race("admin A + senior B leave concurrently (C remains)", s1, [
    lambda c, x: c.post(f"/api/households/{x['hid']}/leave", headers=H.auth(x["toks"][0])),
    lambda c, x: c.post(f"/api/households/{x['hid']}/leave", headers=H.auth(x["toks"][1])),
])

# 2) Last two members (A admin, B) leave concurrently
def s2():
    hid, users, toks = H.household(["A", "B"])
    return {"hid": hid, "toks": toks, "check": lambda: "exists=%s members=%d admins=%d" % state(hid)}
race("last two members leave concurrently", s2, [
    lambda c, x: c.post(f"/api/households/{x['hid']}/leave", headers=H.auth(x["toks"][0])),
    lambda c, x: c.post(f"/api/households/{x['hid']}/leave", headers=H.auth(x["toks"][1])),
])

# 3) Last member leaves while a new user joins with the valid code
def s3():
    hid, users, toks = H.household(["A"])
    s = H.session(); h = s.get(Household, hid); h.invite_code_expires_at = dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1); code = h.invite_code; s.commit(); s.close()
    # create outsider user
    from app.core.security import create_access_token
    s = H.session(); u = User(id=uuid.uuid4(), email=f"j-{uuid.uuid4().hex[:6]}@ex.com", password_hash="x", display_name="J"); s.add(u); s.commit(); uid = u.id; s.close()
    def chk():
        s = H.session(); n = s.query(HouseholdMember).filter_by(user_id=uid).count(); s.close()
        return "household_exists=%s joiner_memberships=%d" % (state(hid)[0], n)
    return {"hid": hid, "toks": toks, "code": code, "jtok": create_access_token(str(uid)), "check": chk}
race("last member leaves || outsider joins", s3, [
    lambda c, x: c.post(f"/api/households/{x['hid']}/leave", headers=H.auth(x["toks"][0])),
    lambda c, x: c.post("/api/households/join", json={"invite_code": x["code"]}, headers=H.auth(x["jtok"])),
])

# 4) Admin removes B while B leaves
def s4():
    hid, users, toks = H.household(["A", "B", "C"])
    return {"hid": hid, "toks": toks, "users": users, "check": lambda: "exists=%s members=%d admins=%d" % state(hid)}
race("admin removes B || B leaves", s4, [
    lambda c, x: c.delete(f"/api/households/{x['hid']}/members/{x['users'][1]}", headers=H.auth(x["toks"][0])),
    lambda c, x: c.post(f"/api/households/{x['hid']}/leave", headers=H.auth(x["toks"][1])),
])

# 5) same user joins twice concurrently (double tap)
def s5():
    hid, users, toks = H.household(["A"])
    s = H.session(); h = s.get(Household, hid); h.invite_code_expires_at = dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=1); code = h.invite_code; s.commit(); s.close()
    from app.core.security import create_access_token
    s = H.session(); u = User(id=uuid.uuid4(), email=f"j-{uuid.uuid4().hex[:6]}@ex.com", password_hash="x", display_name="J"); s.add(u); s.commit(); uid = u.id; s.close()
    def chk():
        s = H.session(); n = s.query(HouseholdMember).filter_by(user_id=uid).count(); s.close(); return f"memberships={n}"
    return {"code": code, "jtok": create_access_token(str(uid)), "check": chk}
race("double join same user", s5, [
    lambda c, x: c.post("/api/households/join", json={"invite_code": x["code"]}, headers=H.auth(x["jtok"])),
    lambda c, x: c.post("/api/households/join", json={"invite_code": x["code"]}, headers=H.auth(x["jtok"])),
])

# 6) concurrent register with same email
def s6():
    em = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    def chk():
        s = H.session(); n = s.query(User).filter(User.email == em).count(); s.close(); return f"users={n}"
    return {"em": em, "check": chk}
race("double register same email", s6, [
    (lambda c, x: c.post("/api/auth/register", json={"email": x["em"], "password": "password123", "display_name": "D", "household_name": "H"})),
    (lambda c, x: c.post("/api/auth/register", json={"email": x["em"], "password": "password123", "display_name": "D", "household_name": "H"})),
])

# 7) concurrent refresh with the same refresh token (body mode)
def s7():
    em = f"rt-{uuid.uuid4().hex[:6]}@example.com"
    c = mk(); r = c.post("/api/auth/register", json={"email": em, "password": "password123", "display_name": "D", "household_name": "H"})
    rt = r.json()["refresh_token"]
    s = H.session(); uid = s.query(User).filter_by(email=em).one().id; s.close()
    def chk():
        s = H.session(); n = s.query(RefreshToken).filter(RefreshToken.user_id == uid, RefreshToken.revoked_at.is_(None)).count(); s.close()
        return f"active_refresh_tokens={n}"
    return {"rt": rt, "check": chk}
race("two concurrent refreshes with same token", s7, [
    lambda c, x: c.post("/api/auth/refresh", json={"refresh_token": x["rt"]}),
    lambda c, x: c.post("/api/auth/refresh", json={"refresh_token": x["rt"]}),
])
