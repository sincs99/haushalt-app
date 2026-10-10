"""Same refresh token presented three times within the grace window (3 tabs / retries), sequentially."""
import sys, uuid
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("hh_grace3")
import logging; logging.disable(logging.CRITICAL)
from fastapi.testclient import TestClient
from app.main import app
from app.models import RefreshToken, User
c = TestClient(app, raise_server_exceptions=False)
em = f"g3-{uuid.uuid4().hex[:6]}@example.com"
r = c.post("/api/auth/register", json={"email": em, "password": "password123", "display_name": "D", "household_name": "H"})
t0 = r.json()["refresh_token"]
for i in range(3):
    r = c.post("/api/auth/refresh", json={"refresh_token": t0})
    print(f"refresh #{i+1} with T0:", r.status_code, r.json().get("detail", "ok"))
s = H.session(); uid = s.query(User).filter_by(email=em).one().id
print("active refresh tokens:", s.query(RefreshToken).filter(RefreshToken.user_id == uid, RefreshToken.revoked_at.is_(None)).count())
