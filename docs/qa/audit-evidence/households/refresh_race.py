"""Concurrent refresh of the same refresh token (two tabs) on PG: how often is reuse-detection
(=global logout) falsely triggered?"""
import sys, uuid, collections, time, random
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("hh_refresh")
from fastapi.testclient import TestClient
from app.main import app
from app.models import RefreshToken, User
import logging; logging.disable(logging.CRITICAL)

def run(N, jitter_ms):
    outc = collections.Counter()
    for _ in range(N):
        em = f"rt-{uuid.uuid4().hex[:6]}@example.com"
        c0 = TestClient(app)
        rt = c0.post("/api/auth/register", json={"email": em, "password": "password123", "display_name": "D", "household_name": "H"}).json()["refresh_token"]
        s = H.session(); uid = s.query(User).filter_by(email=em).one().id; s.close()
        cs = [TestClient(app, raise_server_exceptions=False) for _ in range(2)]
        def op(i):
            if i == 1 and jitter_ms: time.sleep(random.uniform(0, jitter_ms) / 1000)
            r = cs[i].post("/api/auth/refresh", json={"refresh_token": rt})
            return (r.status_code, r.json().get("detail", {}).get("code") if r.status_code != 200 else None)
        res = H.parallel(op, 2)
        s = H.session(); active = s.query(RefreshToken).filter(RefreshToken.user_id == uid, RefreshToken.revoked_at.is_(None)).count(); s.close()
        reused = any(code == "REFRESH_TOKEN_REUSED" for _, code in res)
        outc[("reuse_detected_all_revoked" if reused else "ok", f"active={active}", tuple(sorted(str(x) for x in res)))] += 1
    print(f"N={N} jitter<= {jitter_ms}ms")
    for k, v in outc.most_common(): print("  ", v, k)

run(40, 0)
run(40, 20)
