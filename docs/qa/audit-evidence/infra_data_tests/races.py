import sys, uuid, collections; sys.path.insert(0, sys.argv[1]+"/pg")
import pgharness as H
H.fresh_db("infra_races")
c = H.client()
def codes(res): return collections.Counter(r.status_code if hasattr(r,'status_code') else repr(r)[:80] for r in res)
N=6
# 1 budget upsert same month
hid, users, toks = H.household(["Anna","Ben"])
res = H.parallel(lambda i: c.put(f"/api/households/{hid}/budget", json={"month":"2026-10-01","amount_rappen":1000+i}, headers=H.auth(toks[i%2])), N)
print("budget PUT same month:", codes(res))
# 2 meal plan same date
res = H.parallel(lambda i: c.put(f"/api/households/{hid}/meal-plan/2026-10-12", json={"free_text":f"x{i}"}, headers=H.auth(toks[i%2])), N)
print("meal-plan PUT same date:", codes(res))
# 3 join same user twice
s = H.session(); from app.models import Household, HouseholdMember
code = s.get(Household, hid).invite_code; s.close()
uid, tok = H.add_member(H.household(["Zed"])[0], "Joiner")
res = H.parallel(lambda i: c.post("/api/households/join", json={"invite_code":code}, headers=H.auth(tok)), N)
print("join same user concurrently:", codes(res))
s = H.session(); print("  memberships for joiner in hh:", s.query(HouseholdMember).filter_by(household_id=hid,user_id=uid).count()); s.close()
# 4 widget token create
res = H.parallel(lambda i: c.post(f"/api/households/{hid}/widget-token", headers=H.auth(toks[0])), N)
print("widget token create:", codes(res))
# 5 register same email
em = f"dup-{uuid.uuid4().hex[:6]}@ex.com"
res = H.parallel(lambda i: c.post("/api/auth/register", json={"email":em,"password":"password123","display_name":"D","household_name":"H"}), N)
print("register same email:", codes(res))
from app.models import User
s = H.session(); print("  households orphaned? users with email:", s.query(User).filter_by(email=em).count()); 
import sqlalchemy as sa
print("  households with 0 members total:", s.execute(sa.text("select count(*) from households h where not exists(select 1 from household_members m where m.household_id=h.id)")).scalar()); s.close()
# 6 last two members leave concurrently
hid2, u2, t2 = H.household(["P","Q"])
res = H.parallel(lambda i: c.post(f"/api/households/{hid2}/leave", headers=H.auth(t2[i])), 2)
print("last two leave concurrently:", codes(res))
s = H.session(); print("  household still exists:", s.get(Household, hid2) is not None, "members:", s.query(HouseholdMember).filter_by(household_id=hid2).count()); s.close()
# 7 leave of sole admin concurrently with other member leaving (3 members)
hid3, u3, t3 = H.household(["A1","M1","M2"])
res = H.parallel(lambda i: c.post(f"/api/households/{hid3}/leave", headers=H.auth(t3[i])), 2)
s = H.session(); ms = s.query(HouseholdMember).filter_by(household_id=hid3).all(); print("admin+member leave concurrently:", codes(res), "remaining roles:", [m.role for m in ms]); s.close()
