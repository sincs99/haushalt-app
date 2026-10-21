import sys, uuid, json
sys.path.insert(0, ".")
from sfc_common import H, client as mkclient
H.fresh_db("sfc_shop")
c = mkclient()
hid, users, toks = H.household(["Anna","Ben"])
A, B = H.auth(toks[0]), H.auth(toks[1])
base = f"/api/households/{hid}"
def p(label, r): print(label, r.status_code, (r.text[:300] if r.status_code>=300 else ""))

# list
r = c.post(f"{base}/shopping-lists/", json={"name":"Wocheneinkauf"}, headers=A); p("create list", r); L = r.json()["id"]

print("\n== S1: two people add same item concurrently ==")
def add(i):
    cc = mkclient()
    return cc.post(f"{base}/shopping-items/", json={"name":"Milch","list_id":L,"quantity":"1 l"}, headers=[A,B][i])
rs = H.parallel(add, 2)
print([x.status_code for x in rs])
items = c.get(f"{base}/shopping-items/", params={"list_id":L}, headers=A).json()
print("Milch items:", [ (i["name"], i["quantity"]) for i in items if i["name"]=="Milch"])

print("\n== S2: delete then re-POST same client_id ==")
cid = str(uuid.uuid4())
r = c.post(f"{base}/shopping-items/", json={"id":cid,"name":"Brot","list_id":L}, headers=A); p("create", r)
r = c.delete(f"{base}/shopping-items/{cid}", headers=B); p("delete by B", r)
H.emits.clear()
r = c.post(f"{base}/shopping-items/", json={"id":cid,"name":"Brot","list_id":L}, headers=A); p("re-POST same client id", r)
print(" resurrected:", r.status_code==201, "emits:", [e[0][1] for e in H.emits])

print("\n== S3: concurrent toggles ==")
r = c.post(f"{base}/shopping-items/", json={"name":"Eier","list_id":L}, headers=A); iid = r.json()["id"]; v0=r.json()["version"]
def tog(i):
    cc = mkclient()
    return cc.patch(f"{base}/shopping-items/{iid}", json={"is_checked": i==0}, headers=[A,B][i])
rs = H.parallel(tog, 2)
print("statuses", [x.status_code for x in rs], "resp versions", [x.json()["version"] for x in rs], "resp checked", [x.json()["is_checked"] for x in rs])
fin = [i for i in c.get(f"{base}/shopping-items/", params={"include_checked":True}, headers=A).json() if i["id"]==iid][0]
print("final", fin["is_checked"], "version", fin["version"], "v0", v0)
# PATCH with stale version? send version field
r = c.patch(f"{base}/shopping-items/{iid}", json={"is_checked": False, "version": 1}, headers=A); p("patch with stale version field (ignored?)", r); print(" version now", r.json().get("version"))

print("\n== S4: concurrent increments of version 20 patches ==")
def pt(i):
    cc = mkclient()
    return cc.patch(f"{base}/shopping-items/{iid}", json={"quantity": str(i)}, headers=A)
rs = H.parallel(pt, 10)
vs = sorted(x.json()["version"] for x in rs if x.status_code==200)
print("status", set(x.status_code for x in rs), "versions returned", vs)

print("\n== S5: assignment to non-member / ex-member ==")
r = c.patch(f"{base}/shopping-items/{iid}", json={"assigned_to_user_id": str(uuid.uuid4())}, headers=A); p("assign random", r)
r = c.patch(f"{base}/shopping-items/{iid}", json={"assigned_to_user_id": str(users[1])}, headers=A); p("assign Ben", r)

print("\n== S6: null in PATCH for non-null fields ==")
for f in ["name","is_checked"]:
    r = c.patch(f"{base}/shopping-items/{iid}", json={f: None}, headers=A); p(f"PATCH {f}=null", r)

print("\n== S7: store rename merging ==")
for nm, st in [("a","Coop"),("b","coop"),("c","Migros"),("d","migros ")]:
    c.post(f"{base}/shopping-items/", json={"name":nm,"list_id":L,"store":st}, headers=A)
print("stores", c.get(f"{base}/shopping-items/stores", headers=A).json())
r = c.post(f"{base}/shopping-items/reassign-store", json={"from_store":"coop","to_store":"MIGROS"}, headers=A); p("reassign coop->MIGROS", r); print(r.json())
print("stores", c.get(f"{base}/shopping-items/stores", headers=A).json())
allit = c.get(f"{base}/shopping-items/", params={"include_checked":True}, headers=A).json()
print("store values", sorted(set(str(i["store"]) for i in allit)))

print("\n== S8: concurrent rename vs create with old store ==")
def race(i):
    cc = mkclient()
    if i==0: return cc.post(f"{base}/shopping-items/reassign-store", json={"from_store":"Migros","to_store":"Denner"}, headers=A)
    return cc.post(f"{base}/shopping-items/", json={"name":"late","list_id":L,"store":"Migros"}, headers=B)
rs = H.parallel(race, 2); print([x.status_code for x in rs])
print("stores after race", c.get(f"{base}/shopping-items/stores", headers=A).json())

print("\n== S9: delete list with items (no force / force) ==")
r = c.delete(f"{base}/shopping-lists/{L}", headers=B); p("delete no force", r)
r2 = c.post(f"{base}/shopping-lists/", json={"name":"Second"}, headers=A); L2=r2.json()["id"]
c.post(f"{base}/shopping-items/", json={"name":"x","list_id":L2}, headers=A)
H.emits.clear()
r = c.delete(f"{base}/shopping-lists/{L2}?force=true", headers=B); p("delete force", r)
print(" emits:", [e[0][1] for e in H.emits])
print(" items left in L2:", len([i for i in c.get(f"{base}/shopping-items/", params={"include_checked":True}, headers=A).json() if i["list_id"]==L2]))

print("\n== S10: create item into list that is concurrently deleted ==")
r2 = c.post(f"{base}/shopping-lists/", json={"name":"Third"}, headers=A); L3=r2.json()["id"]
def race2(i):
    cc=mkclient()
    if i==0: return cc.delete(f"{base}/shopping-lists/{L3}?force=true", headers=A)
    return cc.post(f"{base}/shopping-items/", json={"name":"y","list_id":L3}, headers=B)
for k in range(5):
    r2 = c.post(f"{base}/shopping-lists/", json={"name":"T%d"%k}, headers=A); L3=r2.json()["id"]
    rs = H.parallel(race2, 2); print([x.status_code for x in rs], [x.text[:80] for x in rs if x.status_code>=500])

print("\n== S11: list create with client id after delete ==")
lid = str(uuid.uuid4())
c.post(f"{base}/shopping-lists/", json={"id":lid,"name":"Z"}, headers=A)
c.delete(f"{base}/shopping-lists/{lid}", headers=A)
r = c.post(f"{base}/shopping-lists/", json={"id":lid,"name":"Z"}, headers=A); p("list re-POST after delete", r)

print("\n== S12: quantity free text ==")
r = c.post(f"{base}/shopping-items/", json={"name":"Mehl","list_id":L,"quantity":"-5 kg; DROP"}, headers=A); p("weird qty", r); print(r.json().get("quantity"))
r = c.post(f"{base}/shopping-items/", json={"name":"Mehl","list_id":L,"quantity":"x"*51}, headers=A); p("qty 51", r)
