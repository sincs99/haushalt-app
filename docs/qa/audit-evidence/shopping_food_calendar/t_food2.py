import sys; sys.path.insert(0,".")
from sfc_common import H, client as mk
H.fresh_db("sfc_food2")
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
hid, users, toks = H.household(["Anna","Ben"])
A = H.auth(toks[0]); base=f"/api/households/{hid}"
R = c.post(f"{base}/recipes/", json={"name":"P","ingredients":["a"]}, headers=A).json()
try:
    r = c.put(f"{base}/meal-plan/2026-10-21", json={"recipe_id": R["id"], "free_text":"abc"}, headers=A); print(r.status_code, r.text)
except Exception as e:
    import traceback; print(repr(e)[:600])
