"""Spurious AI_DAILY_LIMIT_REACHED on first-row race (limit far from reached). Mocked client."""
import sys, threading, types, runpy
sys.argv = ["x"]
src = open("pg_ai.py").read().split('c = H.client()')[0].replace('H.fresh_db("tagsai_ai")', 'H.fresh_db("tagsai_ai2")')
exec(src)
from collections import Counter
settings.ai_daily_limit_per_household = 50
c = H.client()
def new_hh():
    hid, users, toks = H.household(["Anna", "Ben"])
    r = c.put(f"/api/households/{hid}/ai/settings", json={"ai_enabled": True}, headers=H.auth(toks[0])); assert r.status_code == 200
    return hid, toks
def req(hid, tok):
    r = H.client().post(f"/api/households/{hid}/ai/plant-care", json={"plant": "Ficus"}, headers=H.auth(tok))
    return r.status_code, (r.json().get("detail") or {}).get("code") if r.status_code != 200 else "ok"

def rreq(hid, tok):
    r = H.client().post(f"/api/households/{hid}/ai/recipe", json={"ingredients": ["Reis"]}, headers=H.auth(tok))
    return r.status_code, (r.json().get("detail") or {}).get("code") if r.status_code != 200 else "ok"
MODE.update(kind="ok", delay=0.0)
for trial in range(5):
    hid, toks = new_hh()
    out = H.parallel(lambda i: rreq(hid, toks[i % 2]), 10)
    s_ = H.session(); row = s_.query(AiUsage).filter_by(household_id=hid).first(); s_.close()
    print("trial", trial, Counter(out), "calls counted:", row.calls if row else None, "(limit 50)")
