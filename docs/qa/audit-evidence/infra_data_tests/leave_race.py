import sys, collections; sys.path.insert(0, sys.argv[1]+"/pg")
import pgharness as H, sqlalchemy as sa
H.fresh_db("infra_leave")
c = H.client()
from app.models import Household, HouseholdMember
out = collections.Counter()
for k in range(40):
    hid, u, t = H.household(["P","Q"])
    res = H.parallel(lambda i: c.post(f"/api/households/{hid}/leave", headers=H.auth(t[i])), 2)
    s = H.session(); exists = s.get(Household, hid) is not None; n = s.query(HouseholdMember).filter_by(household_id=hid).count(); s.close()
    out[(tuple(sorted(str(r.status_code) if hasattr(r,'status_code') else type(r).__name__ for r in res)), exists, n)] += 1
for k,v in out.items(): print(v, "x  results=%s household_exists=%s members=%d" % k)
s=H.session(); print("orphan households (0 members):", s.execute(sa.text("select count(*) from households h where not exists(select 1 from household_members m where m.household_id=h.id)")).scalar())
