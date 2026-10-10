"""PG audit of AI quota reservation (tags_ai). Anthropic client is ALWAYS mocked."""
import sys, time, threading, types
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("tagsai_ai")
from app.core.config import settings
object.__setattr__(settings, "anthropic_api_key", "sk-fake-test") if False else None
try:
    settings.anthropic_api_key = "sk-fake-test"
except Exception as e:
    object.__setattr__(settings, "anthropic_api_key", "sk-fake-test")
settings.ai_daily_limit_per_household = 5
import anthropic, httpx
import app.services.ai.client as aic
from app.services.ai.schemas import RecipeOutput, IngredientOutput, PlantCareOutput
from app.models import AiUsage
aic._slots = threading.BoundedSemaphore(100)
assert settings.ai_available

MODE = {"kind": "ok", "delay": 0.0}
calls = {"n": 0}
lock = threading.Lock()
def recipe_out():
    return RecipeOutput(name="Risotto", servings=2, duration_min=30,
                        ingredients=[IngredientOutput(name="Reis", quantity="200 g")], steps=["Kochen."], tags=["x"],
                        missing_ingredients=[], tip=None)
class FakeMessages:
    def parse(self, **kw):
        with lock: calls["n"] += 1
        time.sleep(MODE["delay"])
        k = MODE["kind"]
        req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        if k == "conn": raise anthropic.APIConnectionError(request=req)
        if k == "status500": raise anthropic.InternalServerError("x", response=httpx.Response(500, request=req), body=None)
        if k == "respvalid": raise anthropic.APIResponseValidationError(response=httpx.Response(200, request=req), body=None)
        if k == "runtime": raise RuntimeError("unexpected SDK bug")
        if k == "valerr":
            RecipeOutput.model_validate_json('{"name": 1}')
        return types.SimpleNamespace(usage=types.SimpleNamespace(input_tokens=10, output_tokens=20), model="claude-opus-5-5",
                                     stop_reason="end_turn", stop_details=None, parsed_output=recipe_out())
fake = types.SimpleNamespace(beta=types.SimpleNamespace(messages=FakeMessages()))
aic.get_client = lambda: fake

c = H.client()
def new_hh():
    hid, users, toks = H.household(["Anna", "Ben"])
    r = c.put(f"/api/households/{hid}/ai/settings", json={"ai_enabled": True}, headers=H.auth(toks[0])); assert r.status_code == 200, r.text
    return hid, toks
def usage_row(hid):
    s = H.session(); r = s.query(AiUsage).filter_by(household_id=hid).all(); s.close()
    return [(x.day.isoformat(), x.calls, x.input_tokens, x.output_tokens) for x in r]
def req(hid, tok):
    clt = H.client()
    r = clt.post(f"/api/households/{hid}/ai/recipe", json={"ingredients": ["Reis"]}, headers=H.auth(tok))
    return r.status_code, (r.json().get("detail", {}) or {}).get("code") if r.status_code != 200 else "ok"

print("=== A0: opt-in / not enabled ===")
hid0, toks0 = H.household(["Zed"])[0], H.household(["Zed"])[2]
r = c.post(f"/api/households/{hid0}/ai/recipe", json={"ingredients": ["Reis"]}, headers=H.auth(toks0[0])); print("not enabled:", r.status_code, r.json()["detail"])

print("=== A1: 12 parallel, limit 5, fresh day row (insert race) ===")
hid, toks = new_hh(); MODE.update(kind="ok", delay=0.2); calls["n"] = 0
out = H.parallel(lambda i: req(hid, toks[i % 2]), 12)
from collections import Counter
print(Counter(out), "provider calls:", calls["n"], "usage:", usage_row(hid))

print("=== A2: 20 parallel against existing row ===")
for trial in range(2):
    hid, toks = new_hh(); MODE.update(kind="ok", delay=0.0)
    req(hid, toks[0])  # create row
    calls["n"] = 0
    out = H.parallel(lambda i: req(hid, toks[i % 2]), 20)
    print(Counter(out), "provider calls:", calls["n"], "usage:", usage_row(hid))

print("=== A3: failure modes and quota accounting ===")
for kind in ["conn", "status500", "valerr", "respvalid", "runtime"]:
    hid, toks = new_hh(); MODE.update(kind=kind, delay=0)
    try:
        res = req(hid, toks[0])
    except Exception as e:
        res = ("EXC", type(e).__name__)
    print(f"{kind:10s} ->", res, "usage:", usage_row(hid))

print("=== A4: parallel failures (conn) with limit 5: can failures block successes? ===")
hid, toks = new_hh(); MODE.update(kind="conn", delay=0.3)
out = H.parallel(lambda i: req(hid, toks[0]), 8)
print(Counter(out), "usage:", usage_row(hid))

print("=== A5: semaphore busy releases quota ===")
aic._slots = threading.BoundedSemaphore(1)
hid, toks = new_hh(); MODE.update(kind="ok", delay=0.5)
out = H.parallel(lambda i: req(hid, toks[0]), 3)
print(Counter(out), "usage:", usage_row(hid))
