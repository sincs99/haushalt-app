import sys; sys.path.insert(0,".")
from sfc_common import H, client as mk
H.fresh_db("sfc_vote")
c = mk()
hid, users, toks = H.household(["Anna","Ben"])
A = H.auth(toks[0]); base=f"/api/households/{hid}"
res=[]
for k in range(10):
    P = c.post(f"{base}/polls/", json={"question":"q","options":[{"label":"a"},{"label":"b"},{"label":"c"}]}, headers=A).json()
    o = [x["id"] for x in P["options"]]
    c.post(f"{base}/polls/{P['id']}/vote", json={"option_id":o[0]}, headers=A)
    rs = H.parallel(lambda i: mk().post(f"{base}/polls/{P['id']}/vote", json={"option_id":o[1+i]}, headers=A), 2)
    votes = sum(len(x["votes"]) for x in c.get(f"{base}/polls/{P['id']}", headers=A).json()["options"])
    res.append((tuple(x.status_code for x in rs), votes))
print(res)
