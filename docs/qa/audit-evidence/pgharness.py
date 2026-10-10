"""PostgreSQL audit harness (read-only w.r.t. the repo).

Usage (from any script):
    import sys; sys.path.insert(0, "<scratchpad>/pg")
    import pgharness as H
    H.fresh_db("mydb")          # creates fresh DB + runs `alembic upgrade head`; MUST be called before importing app
    client = H.client()          # FastAPI TestClient on real PG sessions (one session per request)
    hh, users, tokens = H.household(["Anna","Ben","Carla"])  # creates household + members (first is admin)
    H.auth(tokens[0])           # -> headers dict
    H.parallel(fn, n)           # run fn(i) in n threads at once (barrier), returns results

Socket emits & push are mocked (H.emits holds calls).
"""
import os, sys, subprocess, threading, uuid
from unittest.mock import patch, MagicMock

REPO_BACKEND = __import__("os").path.abspath(__import__("os").path.join(__import__("os").path.dirname(__file__), "..", "..", "..", "backend"))
PG = "postgresql://audit:audit@localhost:5432/"
emits = []

def fresh_db(name):
    name = "audit_" + name
    subprocess.run(["psql", PG + "postgres", "-qc", f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"], check=True, env={**os.environ, "PGPASSWORD": "audit"})
    subprocess.run(["psql", PG + "postgres", "-qc", f"CREATE DATABASE {name}"], check=True, env={**os.environ, "PGPASSWORD": "audit"})
    url = PG + name
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("JWT_SECRET_KEY", "audit-secret-key-only-for-tests-min32-xyz")
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
    os.environ["VAPID_PUBLIC_KEY"] = ""
    os.environ["VAPID_PRIVATE_KEY"] = ""
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=REPO_BACKEND, capture_output=True, text=True, env=os.environ)
    if r.returncode != 0:
        print(r.stdout[-3000:], r.stderr[-3000:]); raise SystemExit("alembic failed")
    if REPO_BACKEND not in sys.path:
        sys.path.insert(0, REPO_BACKEND)
    _patch_emits()
    return url

_patched = False
def _patch_emits():
    global _patched
    if _patched: return
    import app.socket_manager as sm
    def rec(*a, **k): emits.append((a, k))
    sm.emit_to_household_sync = rec
    import importlib, pkgutil, app.routers as R
    for m in pkgutil.iter_modules(R.__path__):
        mod = importlib.import_module("app.routers." + m.name)
        if hasattr(mod, "emit_to_household_sync"):
            mod.emit_to_household_sync = rec
    for name in ("app.services.tag_actions", "app.services.push_service"):
        try:
            mod = importlib.import_module(name)
            if hasattr(mod, "emit_to_household_sync"): mod.emit_to_household_sync = rec
        except Exception: pass
    from app.core.rate_limit import limiter
    limiter.enabled = False
    _patched = True

def client():
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)

def session():
    from app.database import SessionLocal
    return SessionLocal()

def household(names, tz="Europe/Zurich", currency="CHF"):
    from app.models import Household, HouseholdMember, User
    from app.core.security import create_access_token
    import datetime as dt
    s = session()
    h = Household(id=uuid.uuid4(), name="HH-"+uuid.uuid4().hex[:6], invite_code=uuid.uuid4().hex[:8].upper(), timezone=tz, currency=currency)
    s.add(h); s.flush()
    users, tokens = [], []
    base = dt.datetime(2026,1,1,tzinfo=dt.timezone.utc)
    for i, n in enumerate(names):
        u = User(id=uuid.uuid4(), email=f"{n.lower()}-{uuid.uuid4().hex[:6]}@ex.com", password_hash="x", display_name=n)
        s.add(u); s.flush()
        s.add(HouseholdMember(id=uuid.uuid4(), household_id=h.id, user_id=u.id, role="admin" if i == 0 else "member", joined_at=base+dt.timedelta(days=i)))
        users.append(u.id); tokens.append(create_access_token(str(u.id)))
    s.commit(); hid = h.id; s.close()
    return hid, users, tokens

def add_member(hid, name, role="member"):
    from app.models import HouseholdMember, User
    from app.core.security import create_access_token
    s = session()
    u = User(id=uuid.uuid4(), email=f"{name.lower()}-{uuid.uuid4().hex[:6]}@ex.com", password_hash="x", display_name=name)
    s.add(u); s.flush(); s.add(HouseholdMember(id=uuid.uuid4(), household_id=hid, user_id=u.id, role=role)); s.commit(); uid=u.id; s.close()
    return uid, create_access_token(str(uid))

def auth(token, hid=None):
    h = {"Authorization": f"Bearer {token}"}
    if hid: h["X-Household-ID"] = str(hid)
    return h

def parallel(fn, n):
    barrier = threading.Barrier(n); out = [None]*n
    def run(i):
        barrier.wait()
        try: out[i] = fn(i)
        except Exception as e: out[i] = e
    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return out
