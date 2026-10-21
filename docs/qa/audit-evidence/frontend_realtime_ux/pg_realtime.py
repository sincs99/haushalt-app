import sys, uuid, datetime as dt
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("fe_rt_1")
c = H.client()
hid, users, toks = H.household(["Anna", "Ben"])
A, B = H.auth(toks[0]), H.auth(toks[1])
base = f"/api/households/{hid}"
def ev(): 
    out=[(a[1], a[2]) for a,k in H.emits]; H.emits.clear(); return out

print("== P1 chore schedule change: what is emitted? ==")
r = c.post(f"{base}/chores/", json={"title":"Bad","recurrence":"weekly","weekday":(dt.date.today().weekday()+3)%7,"rotation_order":[str(users[0]),str(users[1])]}, headers=A); assert r.status_code==201, r.text
ch = r.json(); ev()
asg = c.get(f"{base}/chores/assignments", headers=A).json()
print("assignments before:", [(a['id'][:8], a['due_date']) for a in asg])
print("emits during GET (materialize):", [e for e,_ in ev()])
r = c.patch(f"{base}/chores/{ch['id']}", json={"weekday": (ch['weekday']+2)%7}, headers=B); print("PATCH", r.status_code)
print("emits after schedule PATCH:", [e for e,_ in ev()])
old_ids = {a['id'] for a in asg}
r2 = c.get(f"{base}/chores/assignments", headers=A).json()
print("assignments after:", [(a['id'][:8], a['due_date']) for a in r2], "| emits:", [e for e,_ in ev()])
gone = old_ids - {a['id'] for a in r2}
for g in gone:
    rr = c.post(f"{base}/chores/assignments/{g}/complete", headers=A)
    print("complete on stale assignment", g[:8], "->", rr.status_code, rr.json().get('detail'))

print("== P2 notes: stale full-payload save overwrites other member's edit ==")
n = c.post(f"{base}/notes/", json={"title":"WLAN","body":"PW: alt"}, headers=A).json()
snapshot_A = dict(n)  # A opens edit dialog
c.patch(f"{base}/notes/{n['id']}", json={"body":"PW: NEU-1234"}, headers=B)
r = c.patch(f"{base}/notes/{n['id']}", json={"title":snapshot_A['title']+" (Router)","body":snapshot_A['body'],"tag":None,"pinned":False}, headers=A)
print("A save status", r.status_code, "final body:", c.get(f"{base}/notes/", headers=A).json()[0]['body'], "| has version field:", 'version' in r.json())

print("== P3 expenses: stale full-payload edit overwrites amount ==")
e = c.post(f"{base}/expenses/", json={"description":"Coop","amount_rappen":10000,"paid_by_user_id":str(users[0]),"split_type":"even","participant_ids":[str(users[0]),str(users[1])]}, headers=A).json()
c.patch(f"{base}/expenses/{e['id']}", json={"amount_rappen":15000}, headers=B)   # Ben corrects amount
r = c.patch(f"{base}/expenses/{e['id']}", json={"description":"Coop Wocheneinkauf","amount_rappen":e['amount_rappen'],"paid_by_user_id":str(users[0]),"expense_date":e['expense_date'],"split_type":"even","participant_ids":[str(users[0]),str(users[1])]}, headers=A)
print("A edit status", r.status_code, "final amount:", r.json()['amount_rappen'], "| version field:", 'version' in r.json(), "| updated_at:", r.json().get('updated_at'))

print("== P4 shopping: create-retry after delete recreates (documented M0 limit) ==")
lst = c.post(f"{base}/shopping-lists/", json={"name":"Coop"}, headers=A).json()
iid = str(uuid.uuid4())
r1 = c.post(f"{base}/shopping-items/", json={"id":iid,"name":"Milch","list_id":lst['id']}, headers=A); print("create", r1.status_code, "v", r1.json()['version'])
print("delete by Ben", c.delete(f"{base}/shopping-items/{iid}", headers=B).status_code)
r2 = c.post(f"{base}/shopping-items/", json={"id":iid,"name":"Milch","list_id":lst['id']}, headers=A); print("retry create ->", r2.status_code, "(201 = resurrected)")
ev()
print("== P5 bulk reassign: version bumped server-side but payload has no versions ==")
it = c.post(f"{base}/shopping-items/", json={"name":"Brot","list_id":lst['id'],"store":"Migros"}, headers=A).json(); ev()
r = c.post(f"{base}/shopping-items/reassign-store", json={"from_store":"Migros","to_store":"Coop"}, headers=A); print("reassign", r.status_code, r.json())
print("emits:", ev())
cur = [x for x in c.get(f"{base}/shopping-items/?include_checked=true", headers=A).json() if x['id']==it['id']][0]
print("item version before", it['version'], "after", cur['version'])
print("== P6 double DELETE ==")
print("second delete:", c.delete(f"{base}/shopping-items/{it['id']}", headers=A).status_code, c.delete(f"{base}/shopping-items/{it['id']}", headers=B).status_code)
print("== P7 meal_plan_updated payload from poll decide vs food ==")
