import sys; sys.path.insert(0,".")
from sfc_common import H, client as mk
import uuid, subprocess
H.fresh_db("sfc_cal")
c = mk()
hid, users, toks = H.household(["Anna","Ben"])
A, B = H.auth(toks[0]), H.auth(toks[1])
base = f"/api/households/{hid}"
def p(l, r): print(l, r.status_code, (r.text[:250] if r.status_code>=300 else ""))
def sql(q): return subprocess.run(["psql","postgresql://audit:audit@localhost:5432/audit_sfc_cal","-Atc",q],capture_output=True,text=True).stdout.strip()
cals = c.get(f"{base}/calendars/", headers=A).json()
print("default calendars:", [x["name"] for x in cals])
if not cals:
    cals=[c.post(f"{base}/calendars/", json={"name":"Familie","color":"#112233"}, headers=A).json()]
C = cals[0]["id"]

print("== C1: DST gap 2026-03-29 02:30 (nonexistent) ==")
r = c.post(f"{base}/events/", json={"title":"gap","starts_at":"2026-03-29T02:30:00","ends_at":"2026-03-29T03:15:00","calendar_id":C}, headers=A); p("create 02:30-03:15", r)
r = c.post(f"{base}/events/", json={"title":"gap","starts_at":"2026-03-29T02:30:00","ends_at":"2026-03-29T03:45:00","calendar_id":C}, headers=A); p("create 02:30-03:45", r)
j=r.json(); print(" response starts/ends:", j["starts_at"], j["ends_at"]); print(" db:", sql(f"select starts_at at time zone 'UTC', ends_at at time zone 'UTC' from events where id='{j['id']}'"))
print("== C2: DST overlap 2026-10-25 02:30 (ambiguous) ==")
r = c.post(f"{base}/events/", json={"title":"amb","starts_at":"2026-10-25T02:30:00","calendar_id":C}, headers=A); j=r.json(); print(" response:", j["starts_at"]); print(" db:", sql(f"select starts_at at time zone 'UTC' from events where id='{j['id']}'"))
r = c.post(f"{base}/events/", json={"title":"amb2","starts_at":"2026-10-25T02:00:00","ends_at":"2026-10-25T02:59:00","calendar_id":C}, headers=A); j=r.json(); print(" 02:00-02:59 resp:", j["starts_at"], j["ends_at"])
# end before start across fold: 02:45 start, 02:15 end ambiguous
r = c.post(f"{base}/events/", json={"title":"x","starts_at":"2026-03-29T01:59:00","ends_at":"2026-03-29T02:10:00","calendar_id":C}, headers=A); p(" gap end 02:10 after start 01:59", r); 
if r.status_code<300: print("  ", r.json()["starts_at"], r.json()["ends_at"])
print("== C3: all-day event edit title only (UI sends full payload) ==")
r = c.post(f"{base}/events/", json={"title":"Ferien","starts_at":"2026-10-24T00:00:00","ends_at":"2026-10-26T23:59:00","all_day":True,"calendar_id":C}, headers=A); E=r.json(); print(" created", E["starts_at"], E["ends_at"])
r = c.patch(f"{base}/events/{E['id']}", json={"title":"Ferien!"}, headers=A); print(" title-only patch:", r.json()["starts_at"], r.json()["ends_at"])
# UI style patch: substring(0,19) re-sent
r = c.patch(f"{base}/events/{E['id']}", json={"title":"Ferien!!","starts_at":"2026-10-24T00:00:00","ends_at":"2026-10-26T23:59:00","all_day":True}, headers=A); print(" UI full patch:", r.json()["starts_at"], r.json()["ends_at"])
print("== C4: timed event, PATCH starts_at only later than existing end ==")
r = c.post(f"{base}/events/", json={"title":"t","starts_at":"2026-10-12T09:00:00","ends_at":"2026-10-12T10:00:00","calendar_id":C}, headers=A); T=r.json()
r = c.patch(f"{base}/events/{T['id']}", json={"starts_at":"2026-10-12T11:00:00"}, headers=A); p(" move start after end", r)
r = c.patch(f"{base}/events/{T['id']}", json={"starts_at":"2026-10-12T11:00:00","ends_at":None}, headers=A); p(" move start + clear end", r)
print("== C5: null on NOT NULL fields ==")
for f in ["title","starts_at","calendar_id","all_day","participant_ids"]:
    X = c.post(f"{base}/events/", json={"title":"n_"+f,"starts_at":"2026-11-20T09:00:00","calendar_id":C}, headers=A).json()
    r = c.patch(f"{base}/events/{X['id']}", json={f: None}, headers=A); p(f" {f}=null", r)
    print("   GET single:", c.get(f"{base}/events/{X['id']}", headers=A).status_code, " db participant_ids:", sql(f"select participant_ids::text from events where id='{X['id']}'"))
print(" GET range containing corrupted event:", c.get(f"{base}/events/", params={"from_date":"2026-11-16","to_date":"2026-11-22"}, headers=A).status_code)
print(" GET range Oct (unaffected):", c.get(f"{base}/events/", params={"from_date":"2026-10-01","to_date":"2026-10-31"}, headers=A).status_code)
print("== C6: participants not members / duplicates ==")
r = c.post(f"{base}/events/", json={"title":"p","starts_at":"2026-10-13T09:00:00","calendar_id":C,"participant_ids":[str(uuid.uuid4()), str(users[0]), str(users[0])]}, headers=A); p(" random participant", r); print("  stored:", r.json().get("participant_ids"))
hid2,u2,t2 = H.household(["Eve"])
r = c.post(f"{base}/events/", json={"title":"p","starts_at":"2026-10-13T09:00:00","calendar_id":C,"participant_ids":[str(u2[0])]}, headers=A); p(" other-household user as participant", r)
print("== C7: range query consistency ==")
r = c.post(f"{base}/events/", json={"title":"late","starts_at":"2026-10-12T23:30:00","ends_at":"2026-10-13T00:00:00","calendar_id":C}, headers=A)
r = c.post(f"{base}/events/", json={"title":"multi","starts_at":"2026-10-09T10:00:00","ends_at":"2026-10-14T10:00:00","calendar_id":C}, headers=A)
for rng in [("2026-10-13","2026-10-13"),("2026-10-12","2026-10-18"),("2026-10-01","2026-10-31")]:
    ev = c.get(f"{base}/events/", params={"from_date":rng[0],"to_date":rng[1]}, headers=A)
    if ev.status_code!=200: print("  ", rng, ev.status_code); continue
    ev=ev.json()
    print(" ", rng, sorted(e["title"] for e in ev))
print("== C8: delete calendar with events / last calendar ==")
C2 = c.post(f"{base}/calendars/", json={"name":"Arbeit","color":"#aabbcc"}, headers=A).json()["id"]
c.post(f"{base}/events/", json={"title":"w","starts_at":"2026-10-14T09:00:00","calendar_id":C2}, headers=A)
r = c.delete(f"{base}/calendars/{C2}", headers=B); p(" delete with events", r)
print("== C9: race: delete empty calendar vs create event in it ==")
res=[]
for k in range(6):
    C3 = c.post(f"{base}/calendars/", json={"name":"R%d"%k,"color":"#aabbcc"}, headers=A).json()["id"]
    rs = H.parallel(lambda i: mk().delete(f"{base}/calendars/{C3}", headers=A) if i==0 else mk().post(f"{base}/events/", json={"title":"race","starts_at":"2026-10-15T09:00:00","calendar_id":C3}, headers=B), 2)
    res.append(tuple(x.status_code for x in rs))
print(" (delete, create) statuses:", res)
print(" orphan check (events whose calendar missing):", sql("select count(*) from events e left join calendars c on c.id=e.calendar_id where c.id is null"))
print(" race events existing:", sql("select count(*) from events where title='race'"))
print("== C10: race: delete two calendars concurrently leaving zero ==")
hid3,u3,t3 = H.household(["X","Y"]); A3=H.auth(t3[0]); b3=f"/api/households/{hid3}"
cs = c.get(f"{b3}/calendars/", headers=A3).json()
while len(cs)<2:
    c.post(f"{b3}/calendars/", json={"name":"K%d"%len(cs),"color":"#aabbcc"}, headers=A3); cs = c.get(f"{b3}/calendars/", headers=A3).json()
for x in cs[2:]: c.delete(f"{b3}/calendars/{x['id']}", headers=A3)
cs = c.get(f"{b3}/calendars/", headers=A3).json()
rs = H.parallel(lambda i: mk().delete(f"{b3}/calendars/{cs[i]['id']}", headers=A3), 2)
print(" statuses", [x.status_code for x in rs], "remaining calendars:", len(c.get(f"{b3}/calendars/", headers=A3).json()))
print("== C11: dashboard today events vs multi-day ==")
