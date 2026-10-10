import sys; sys.path.insert(0,".")
from sfc_common import H, client as mk
import uuid, subprocess
H.fresh_db("sfc_polls")
c = mk()
hid, users, toks = H.household(["Anna","Ben","Carla"])
A, B, Cc = [H.auth(t) for t in toks]
base = f"/api/households/{hid}"
def p(l, r): print(l, r.status_code, (r.text[:200] if r.status_code>=300 else ""))
def sql(q): return subprocess.run(["psql","postgresql://audit:audit@localhost:5432/audit_sfc_polls","-Atc",q],capture_output=True,text=True).stdout.strip()
CAL = c.post(f"{base}/calendars/", json={"name":"Fam","color":"#112233"}, headers=A).json()["id"]
CAL2 = c.post(f"{base}/calendars/", json={"name":"Two","color":"#112233"}, headers=A).json()["id"]
def mkpoll(opts=None, **kw):
    body={"question":"Wann?","options": opts or [{"label":"Sa 19:00","starts_at":"2026-10-17T19:00:00"},{"label":"So 12:00","starts_at":"2026-10-18T12:00:00"}]}
    body.update(kw); r = c.post(f"{base}/polls/", json=body, headers=A); return r
print("== P1: concurrent decide (10 rounds x 3) ==")
dup=0; codes=set()
for k in range(10):
    P = mkpoll().json(); o = P["options"][0]["id"]
    rs = H.parallel(lambda i: mk().post(f"{base}/polls/{P['id']}/decide", json={"option_id":o,"event_title":"Essen","calendar_id":CAL}, headers=[A,B,Cc][i]), 3)
    codes.add(tuple(sorted(x.status_code for x in rs)))
print(" status sets:", codes)
print(" events titled Essen:", sql("select count(*) from events where title='Essen'"), " decided polls:", sql("select count(*) from event_polls where status='entschieden'"))
print("== P2: option starts_at in API (L-13) ==")
P = mkpoll().json(); print(" option starts_at:", [o["starts_at"] for o in P["options"]])
print("== P3: decide twice / vote after decide / vote other poll option ==")
P2 = mkpoll().json()
r = c.post(f"{base}/polls/{P['id']}/vote", json={"option_id":P2["options"][0]["id"]}, headers=B); p(" vote w/ option of other poll", r)
r = c.post(f"{base}/polls/{P['id']}/vote", json={"option_id":P["options"][0]["id"]}, headers=B); p(" vote", r)
r = c.post(f"{base}/polls/{P['id']}/vote", json={"option_id":P["options"][1]["id"]}, headers=B); p(" change vote", r); print("  votes per option:", [len(o["votes"]) for o in r.json()["options"]])
r = c.post(f"{base}/polls/{P['id']}/decide", json={"option_id":P["options"][1]["id"],"event_title":"E","calendar_id":CAL}, headers=A); p(" decide", r)
ev = r.json()["decided_event_id"]; print("  event:", c.get(f"{base}/events/{ev}", headers=A).json()["starts_at"])
r = c.post(f"{base}/polls/{P['id']}/decide", json={"option_id":P["options"][0]["id"],"event_title":"E","calendar_id":CAL}, headers=A); p(" decide again", r)
r = c.post(f"{base}/polls/{P['id']}/vote", json={"option_id":P["options"][0]["id"]}, headers=Cc); p(" vote after decide", r)
print("== P4: delete decided event, then calendar ==")
r = c.delete(f"{base}/events/{ev}", headers=A); p(" delete event", r)
print("  poll after:", c.get(f"{base}/polls/{P['id']}", headers=A).json()["status"], c.get(f"{base}/polls/{P['id']}", headers=A).json()["decided_event_id"])
print("== P5: race decide vs delete calendar ==")
res=[]
for k in range(6):
    Ck = c.post(f"{base}/calendars/", json={"name":"Z%d"%k,"color":"#112233"}, headers=A).json()["id"]
    Pk = mkpoll().json()
    rs = H.parallel(lambda i: mk().delete(f"{base}/calendars/{Ck}", headers=A) if i==0 else mk().post(f"{base}/polls/{Pk['id']}/decide", json={"option_id":Pk["options"][0]["id"],"event_title":"RaceDecide","calendar_id":Ck}, headers=B), 2)
    st = c.get(f"{base}/polls/{Pk['id']}", headers=A).json()
    res.append((tuple(x.status_code for x in rs), st["status"], st["decided_event_id"] is not None))
print(" (del,decide), poll status, has event:", res)
print("  RaceDecide events in DB:", sql("select count(*) from events where title='RaceDecide'"))
print("== P6: poll w/o starts_at decides to 'now' ==")
Pn = mkpoll(opts=[{"label":"a"},{"label":"b"}]).json()
r = c.post(f"{base}/polls/{Pn['id']}/decide", json={"option_id":Pn["options"][0]["id"],"event_title":"Now","calendar_id":CAL}, headers=A)
print(" event starts:", c.get(f"{base}/events/{r.json()['decided_event_id']}", headers=A).json()["starts_at"])
print("== P7: meal poll overwrites existing day entry ==")
R1 = c.post(f"{base}/recipes/", json={"name":"Risotto","ingredients":["Reis"]}, headers=A).json()
R2 = c.post(f"{base}/recipes/", json={"name":"Pizza","ingredients":["Mehl"]}, headers=A).json()
c.put(f"{base}/meal-plan/2026-10-20", json={"free_text":"Grosis Geburtstag – Fondue"}, headers=A)
MP = mkpoll(opts=[{"label":"Risotto","recipe_id":R1["id"]},{"label":"Pizza","recipe_id":R2["id"]}], poll_type="meal", meal_date="2026-10-20").json()
H.emits.clear()
r = c.post(f"{base}/polls/{MP['id']}/meal-decide", json={"option_id":MP["options"][0]["id"]}, headers=B); p(" meal-decide", r)
wk = c.get(f"{base}/meal-plan/", params={"week":"2026-10-20"}, headers=A).json()
print("  day entry now:", [(e["date"], e["free_text"], e["recipe"]["name"] if e["recipe"] else None) for e in wk])
print("  emits:", [(e[0][1], e[0][2]) for e in H.emits if e[0][1]=="meal_plan_updated"])
print("== P8: recipe deleted between vote and meal-decide ==")
MP2 = mkpoll(opts=[{"label":"Risotto","recipe_id":R1["id"]},{"label":"Pizza","recipe_id":R2["id"]}], poll_type="meal", meal_date="2026-10-21").json()
c.delete(f"{base}/recipes/{R2['id']}", headers=A)
print("  option recipe ids after delete:", [o["recipe_id"] for o in c.get(f"{base}/polls/{MP2['id']}", headers=A).json()["options"]])
r = c.post(f"{base}/polls/{MP2['id']}/meal-decide", json={"option_id":MP2["options"][1]["id"]}, headers=B); p(" meal-decide pizza", r)
wk = c.get(f"{base}/meal-plan/", params={"week":"2026-10-21"}, headers=A).json()
print("  entry:", [(e["date"], e["recipe_id"], e["free_text"]) for e in wk if e["date"]=="2026-10-21"])
print("== P9: concurrent meal-decide on 2 different polls, same date, no prior entry ==")
res=[]
for k in range(5):
    d=f"2026-12-0{k+1}"
    Ma = mkpoll(opts=[{"label":"A"},{"label":"B"}], poll_type="meal", meal_date=d).json()
    Mb = mkpoll(opts=[{"label":"C"},{"label":"D"}], poll_type="meal", meal_date=d).json()
    rs = H.parallel(lambda i: mk().post(f"{base}/polls/{[Ma,Mb][i]['id']}/meal-decide", json={"option_id":[Ma,Mb][i]["options"][0]["id"]}, headers=A), 2)
    sa = c.get(f"{base}/polls/{Ma['id']}", headers=A).json()["status"]; sb = c.get(f"{base}/polls/{Mb['id']}", headers=A).json()["status"]
    res.append((tuple(x.status_code for x in rs), sa, sb))
print(" ", res)
print("== P10: event poll with foreign-household recipe_id ==")
hid2,u2,t2 = H.household(["Eve"]); A2=H.auth(t2[0])
Rf = c.post(f"/api/households/{hid2}/recipes/", json={"name":"Secret","ingredients":["x"]}, headers=A2).json()
r = mkpoll(opts=[{"label":"a","recipe_id":Rf["id"]},{"label":"b"}]); p(" event poll w/ foreign recipe", r)
r = mkpoll(opts=[{"label":"a","recipe_id":Rf["id"]},{"label":"b"}], poll_type="meal", meal_date="2026-12-24"); p(" meal poll w/ foreign recipe", r)
print("== P11: meal_date on event poll / meal options with starts_at ==")
r = mkpoll(meal_date="2026-12-24"); p(" event poll with meal_date", r); 
if r.status_code<300: print("  decided_meal_date:", r.json()["decided_meal_date"])
print("== P12: decide meal poll via /decide, event poll via /meal-decide ==")
r = c.post(f"{base}/polls/{MP2['id']}/decide", json={"option_id":MP2["options"][0]["id"],"event_title":"x","calendar_id":CAL}, headers=A); p(" ", r)
print("== P13: ex-member's vote remains counted ==")
P3 = mkpoll().json()
c.post(f"{base}/polls/{P3['id']}/vote", json={"option_id":P3["options"][0]["id"]}, headers=Cc)
r = c.post(f"{base}/households/{hid}/leave", headers=Cc) if False else c.post(f"/api/households/{hid}/leave", headers=Cc); p(" Carla leaves", r)
print("  votes:", [len(o["votes"]) for o in c.get(f"{base}/polls/{P3['id']}", headers=A).json()["options"]])
