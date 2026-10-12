import sys; sys.path.insert(0,".")
from sfc_common import H, client as mk
import uuid
H.fresh_db("sfc_food")
c = mk()
hid, users, toks = H.household(["Anna","Ben"])
A, B = H.auth(toks[0]), H.auth(toks[1])
base = f"/api/households/{hid}"
def p(l, r): print(l, r.status_code, (r.text[:250] if r.status_code>=300 else ""))

print("== F0: version consistency of concurrent shopping patches ==")
L = c.post(f"{base}/shopping-lists/", json={"name":"L"}, headers=A).json()["id"]
iid = c.post(f"{base}/shopping-items/", json={"name":"Eier","list_id":L}, headers=A).json()["id"]
rs = H.parallel(lambda i: mk().patch(f"{base}/shopping-items/{iid}", json={"quantity": str(i)}, headers=A), 8)
seen = {}
for x in rs:
    j = x.json(); seen.setdefault(j["version"], set()).add(j["quantity"])
print("version -> quantities in responses:", seen)
print("final:", [ (i["version"], i["quantity"]) for i in c.get(f"{base}/shopping-items/", headers=A).json() if i["id"]==iid])

print("\n== F1: recipe delete leaves meal plan entry with neither recipe nor text ==")
R = c.post(f"{base}/recipes/", json={"name":"Lasagne","ingredients":["200 g Mehl","Milch","milch "," Tomaten"]}, headers=A).json()
r = c.put(f"{base}/meal-plan/2026-10-12", json={"recipe_id": R["id"]}, headers=A); p("assign", r); E = r.json()
r = c.delete(f"{base}/recipes/{R['id']}", headers=B); p("delete recipe", r)
wk = c.get(f"{base}/meal-plan/", params={"week":"2026-10-12"}, headers=A).json()
print("entry after delete:", [(e["date"], e["recipe_id"], e["free_text"], e["recipe"]) for e in wk])
r = c.post(f"{base}/meal-plan/{E['id']}/add-missing-to-shopping", headers=A); p("add-missing on orphan entry", r)

print("\n== F2: add-missing dedupe ==")
R = c.post(f"{base}/recipes/", json={"name":"Pasta","ingredients":["200 g Mehl","Milch","milch "," Tomaten","Eier"]}, headers=A).json()
E = c.put(f"{base}/meal-plan/2026-10-13", json={"recipe_id": R["id"]}, headers=A).json()
c.post(f"{base}/shopping-items/", json={"name":"Mehl","list_id":L}, headers=A)
H.emits.clear()
r = c.post(f"{base}/meal-plan/{E['id']}/add-missing-to-shopping", headers=A); print("1st:", r.json())
print(" emits:", [(e[0][1], e[0][2].get("name")) for e in H.emits])
r = c.post(f"{base}/meal-plan/{E['id']}/add-missing-to-shopping", headers=A); print("2nd:", r.json())
# check one off then import again
items = c.get(f"{base}/shopping-items/", headers=A).json()
tom = [i for i in items if i["name"]=="Tomaten"][0]
c.patch(f"{base}/shopping-items/{tom['id']}", json={"is_checked": True}, headers=A)
r = c.post(f"{base}/meal-plan/{E['id']}/add-missing-to-shopping", headers=A); print("3rd after checking Tomaten:", r.json())
print("Which list?", r.json()["list_id"]==L)

print("\n== F2b: concurrent add-missing ==")
E2 = c.put(f"{base}/meal-plan/2026-10-14", json={"recipe_id": R["id"]}, headers=A).json()
c2 = c.post(f"{base}/recipes/", json={"name":"Curry","ingredients":["Reis","Kokosmilch","Curry"]}, headers=A).json()
E3 = c.put(f"{base}/meal-plan/2026-10-15", json={"recipe_id": c2["id"]}, headers=A).json()
rs = H.parallel(lambda i: mk().post(f"{base}/meal-plan/{E3['id']}/add-missing-to-shopping", headers=[A,B][i]), 2)
print([ (x.status_code, x.json().get("added")) for x in rs])
items = c.get(f"{base}/shopping-items/", headers=A).json()
print("Reis count:", sum(1 for i in items if i["name"]=="Reis"))

print("\n== F2c: concurrent add-missing with NO list (default list created twice?) ==")
hid2, u2, t2 = H.household(["C","D"]); A2,B2 = H.auth(t2[0]),H.auth(t2[1]); b2=f"/api/households/{hid2}"
R2 = c.post(f"{b2}/recipes/", json={"name":"X","ingredients":["Salz"]}, headers=A2).json()
E4 = c.put(f"{b2}/meal-plan/2026-10-12", json={"recipe_id": R2["id"]}, headers=A2).json()
rs = H.parallel(lambda i: mk().post(f"{b2}/meal-plan/{E4['id']}/add-missing-to-shopping", headers=[A2,B2][i]), 2)
print([x.status_code for x in rs])
print("lists:", [(l["name"], l["position"]) for l in c.get(f"{b2}/shopping-lists/", headers=A2).json()])

print("\n== F3: concurrent PUT same day ==")
for k in range(4):
    d = f"2026-11-0{k+1}"
    rs = H.parallel(lambda i: mk().put(f"{base}/meal-plan/{d}", json={"free_text": f"by{i}"}, headers=[A,B][i]), 2)
    print(d, [x.status_code for x in rs])

print("\n== F4: recipe edit after scheduling reflects in plan ==")
c.patch(f"{base}/recipes/{R['id']}", json={"name":"Pasta2"}, headers=A)
wk = c.get(f"{base}/meal-plan/", params={"week":"2026-10-13"}, headers=A).json()
print([e["recipe"]["name"] for e in wk if e["recipe"]])

print("\n== F5: recipe update with null on NOT NULL fields ==")
for f in ["name","servings","is_favorite","ingredients"]:
    r = c.patch(f"{base}/recipes/{R['id']}", json={f: None}, headers=A); p(f"recipe {f}=null", r)

print("\n== F6: recipe_id of other household in meal plan ==")
r = c.put(f"{b2}/meal-plan/2026-10-20", json={"recipe_id": R["id"]}, headers=A2); p("foreign recipe", r)

print("\n== F7: meal plan both recipe and free_text ==")
from fastapi.testclient import TestClient
from app.main import app
try:
    r = TestClient(app).put(f"{base}/meal-plan/2026-10-21", json={"recipe_id": R["id"], "free_text":"abc"}, headers=A); print(r.status_code, r.text[:200])
except Exception as e: print("EXC", repr(e)[:700])
