import sys, json; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("j1")
c = H.client()
hid, (A, B, C), (tA, tB, tC) = H.household(["Anna", "Ben", "Carla"])
P = f"/api/households/{hid}"
name = {str(A): "Anna", str(B): "Ben", str(C): "Carla"}
def bal(tok=tA):
    r = c.get(P + "/expenses/balances", headers=H.auth(tok)).json()
    b = {name.get(x["user_id"], x["user_id"][:6]): x["saldo_rappen"] for x in r["balances"]}
    s = [(name.get(x["from_user_id"]), name.get(x["to_user_id"]), x["amount_rappen"]) for x in r["settlements"]]
    return b, s, r["unassigned_rappen"]
def show(step): b, s, u = bal(); print(f"{step}: saldi={b} sum={sum(b.values())} unassigned={u} suggestions={s}")

# 1. Anna creates a recurring rent bill with herself as payer and books it (3 members)
bill = c.post(P + "/recurring-bills/", json={"name": "Miete", "amount_rappen": 300000, "day_of_month": 1, "paid_by_user_id": str(A)}, headers=H.auth(tA)).json()
r = c.post(P + f"/recurring-bills/{bill['id']}/book", headers=H.auth(tA)); print("book#1", r.status_code)
show("after rent booked")
# 2. Ben records groceries 100.00 even for all
r = c.post(P + "/expenses/", json={"description": "Migros", "amount_rappen": 10000, "paid_by_user_id": str(B), "split_type": "even"}, headers=H.auth(tB)); print("groceries", r.status_code)
show("after groceries")
# 3. Carla leaves
r = c.post(P + "/leave", headers=H.auth(tC)); print("carla leaves", r.status_code)
show("after Carla left")
# 4. Remaining members record all suggested settlements (incl. ex-member Carla's payments recorded by Anna)
b, s, u = bal()
for frm, to, amt in s:
    ids = {"Anna": A, "Ben": B, "Carla": C}
    r = c.post(P + "/settlements/", json={"from_user_id": str(ids[frm]), "to_user_id": str(ids[to]), "amount_rappen": amt}, headers=H.auth(tA))
    print(f"  settle {frm}->{to} {amt}: {r.status_code} {r.text[:120] if r.status_code>=300 else ''}")
show("after recording all suggestions")
# 5. Recurring bill: re-booking in same month blocked
r = c.post(P + f"/recurring-bills/{bill['id']}/book", headers=H.auth(tA)); print("book#2 same month", r.status_code, r.json().get("detail",{}).get("code") if r.status_code>=300 else "")
# 6. Delete the booked rent expense, then book again (re-book allowed?)
exps = c.get(P + "/expenses/", headers=H.auth(tA)).json()
rent = [e for e in exps if e["recurring_bill_id"] == bill["id"]][0]
print("rent shares participants:", sorted(name[s_["user_id"]] for s_ in rent["shares"]))
r = c.delete(P + f"/expenses/{rent['id']}", headers=H.auth(tB)); print("Ben deletes Anna's rent expense:", r.status_code)
show("after Ben deleted rent expense (post-settlement)")
r = c.post(P + f"/recurring-bills/{bill['id']}/book", headers=H.auth(tA)); print("re-book after delete", r.status_code)
exps = c.get(P + "/expenses/", headers=H.auth(tA)).json()
rent2 = [e for e in exps if e["recurring_bill_id"] == bill["id"]]
if rent2: print("rebooked rent participants:", sorted(name[s_["user_id"]] for s_ in rent2[0]["shares"]))
show("after re-book (2 members)")
# 7. Finance summary / dashboard / budget consistency
fs = c.get(P + "/finance-summary", headers=H.auth(tA)).json(); print("finance-summary total_spent", fs["total_spent_rappen"], "pending", [(x["name"], x["is_booked_this_month"]) for x in fs["pending_bills"]])
db_ = c.get(P + "/dashboard", headers=H.auth(tA)); d = db_.json()
print("dashboard keys", list(d.keys()))
print("dashboard finance-ish:", {k: v for k, v in d.items() if "fin" in k.lower() or "bal" in k.lower() or "budget" in k.lower() or "saldo" in k.lower()})
# 8. Settlement history still references ex-member Carla; Carla can no longer see anything
r = c.get(P + "/expenses/balances", headers=H.auth(tC)); print("Carla reads balances after leaving:", r.status_code)
# 9. Bill default payer leaves: Anna (payer) leaves -> booking next time?
s = H.session()
from app.models import RecurringBill
print("bill payer still Anna:", str(s.get(RecurringBill, bill["id"] if False else __import__('uuid').UUID(bill["id"])).paid_by_user_id) == str(A)); s.close()
r = c.post(P + "/leave", headers=H.auth(tA)); print("Anna leaves", r.status_code)
r = c.get(P + "/members", headers=H.auth(tB)).json(); print("members now", [(name.get(m.get("user_id")), m.get("role")) for m in r])
# delete current month booking to simulate next month booking by Ben with default payer
exps = c.get(P + "/expenses/", headers=H.auth(tB)).json()
for e in exps:
    if e["recurring_bill_id"] == bill["id"]: c.delete(P + f"/expenses/{e['id']}", headers=H.auth(tB))
r = c.post(P + f"/recurring-bills/{bill['id']}/book", headers=H.auth(tB)); print("Ben books with ex-member default payer:", r.status_code, r.text[:200])
bl = c.get(P + "/recurring-bills/", headers=H.auth(tB)).json(); print("bill list shows payer:", name.get(bl[0]["paid_by_user_id"]))
