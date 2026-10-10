import sys; sys.path.insert(0,".")
from sfc_common import H, client as mk
H.fresh_db("sfc_food3")
c = mk()
hid, users, toks = H.household(["Anna","Ben"])
A = H.auth(toks[0]); base=f"/api/households/{hid}"
R = c.post(f"{base}/recipes/", json={"name":"P","ingredients":["a"]}, headers=A).json()
c.put(f"{base}/meal-plan/2026-10-21", json={"recipe_id": R["id"]}, headers=A)
r = c.patch(f"{base}/recipes/{R['id']}", json={"ingredients": None}, headers=A); print("PATCH ingredients=null", r.status_code)
import subprocess
print(subprocess.run(["psql","postgresql://audit:audit@localhost:5432/audit_sfc_food3","-Atc","select name, ingredients::text, json_typeof(ingredients) from recipes"],capture_output=True,text=True).stdout)
print("GET recipes", c.get(f"{base}/recipes/", headers=A).status_code)
print("GET meal-plan week", c.get(f"{base}/meal-plan/", params={"week":"2026-10-21"}, headers=A).status_code)
print("GET dashboard", c.get(f"{base}/dashboard", headers=A).status_code)
r = c.patch(f"{base}/recipes/{R['id']}", json={"ingredients": ["a"]}, headers=A); print("repair PATCH", r.status_code)
# other null fields
for f in ["name","servings","is_favorite"]:
    r = c.patch(f"{base}/recipes/{R['id']}", json={f: None}, headers=A); print(f, r.status_code)
print(subprocess.run(["psql","postgresql://audit:audit@localhost:5432/audit_sfc_food3","-Atc","select name, servings, is_favorite from recipes"],capture_output=True,text=True).stdout)
# poll creator / events null fields
