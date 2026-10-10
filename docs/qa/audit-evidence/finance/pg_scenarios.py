"""Deterministic finance scenarios against REST API on PostgreSQL.
Run: $S/venv/bin/python pg_scenarios.py
"""
import sys, uuid, json, datetime as dt
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("finance_scen")
c = H.client()
from sqlalchemy import text


def E(hid): return f"/api/households/{hid}/expenses/"
def S(hid): return f"/api/households/{hid}/settlements/"
def B(hid): return f"/api/households/{hid}/recurring-bills/"

def bal(hid, tok):
    r = c.get(f"/api/households/{hid}/expenses/balances", headers=H.auth(tok)); assert r.status_code == 200, r.text
    return r.json()

def saldi(hid, tok):
    return {b["user_id"]: b["saldo_rappen"] for b in bal(hid, tok)["balances"]}

def show(title, *a):
    print(f"\n=== {title}"); [print("   ", x) for x in a]

def names(users, ns):
    return {str(u): n for u, n in zip(users, ns)}

# ---------------------------------------------------------------- 1 delete expense of someone else erases debt
ns = ["Anna", "Ben"]
hid, U, T = H.household(ns); nm = names(U, ns)
r = c.post(E(hid), json={"description": "Miete", "amount_rappen": 200000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0]))
eid = r.json()["id"]
before = saldi(hid, T[0])
r = c.delete(E(hid) + eid, headers=H.auth(T[1]))  # Ben (debtor) deletes Anna's expense
after = saldi(hid, T[0])
show("1 debtor deletes creditor's expense", f"delete status={r.status_code}",
     f"before={ {nm[k]: v for k, v in before.items()} }", f"after={ {nm[k]: v for k, v in after.items()} }")

# ---------------------------------------------------------------- 2 settlement then expense edited/deleted -> flips
hid, U, T = H.household(ns); nm = names(U, ns)
eid = c.post(E(hid), json={"description": "Einkauf", "amount_rappen": 10000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0])).json()["id"]
s = bal(hid, T[0])["settlements"][0]
r = c.post(S(hid), json={"from_user_id": s["from_user_id"], "to_user_id": s["to_user_id"], "amount_rappen": s["amount_rappen"]}, headers=H.auth(T[1]))
z = saldi(hid, T[0])
r2 = c.patch(E(hid) + eid, json={"amount_rappen": 6000}, headers=H.auth(T[1]))
b2 = bal(hid, T[0])
r3 = c.delete(E(hid) + eid, headers=H.auth(T[1]))
b3 = bal(hid, T[0])
show("2 edit/delete after settlement", f"after settle saldi={list(z.values())}",
     f"patch amount 100->60 status={r2.status_code} saldi={ {nm[x['user_id']]: x['saldo_rappen'] for x in b2['balances']} } suggestions={[(nm[t['from_user_id']], nm[t['to_user_id']], t['amount_rappen']) for t in b2['settlements']]}",
     f"delete status={r3.status_code} saldi={ {nm[x['user_id']]: x['saldo_rappen'] for x in b3['balances']} } suggestions={[(nm[t['from_user_id']], nm[t['to_user_id']], t['amount_rappen']) for t in b3['settlements']]}",
     f"warning/flag in response? patch keys={sorted(r2.json().keys())}")

# ---------------------------------------------------------------- 3 overpayment settlement accepted
hid, U, T = H.household(ns); nm = names(U, ns)
c.post(E(hid), json={"description": "x", "amount_rappen": 1000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0]))
r = c.post(S(hid), json={"from_user_id": str(U[1]), "to_user_id": str(U[0]), "amount_rappen": 99999}, headers=H.auth(T[1]))
show("3 overpaying settlement (debt 5.00, pay 999.99)", f"status={r.status_code}", f"saldi={ {nm[k]: v for k, v in saldi(hid, T[0]).items()} }")
r = c.post(S(hid), json={"from_user_id": str(U[0]), "to_user_id": str(U[1]), "amount_rappen": 500}, headers=H.auth(T[1]))
show("3b settlement with no debt at all (creditor pays debtor)", f"status={r.status_code}")

# ---------------------------------------------------------------- 4 sequential double recording of the same payment
hid, U, T = H.household(ns); nm = names(U, ns)
c.post(E(hid), json={"description": "x", "amount_rappen": 5000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0]))
sug = bal(hid, T[0])["settlements"][0]  # both users looked at the same suggestion
p = {"from_user_id": sug["from_user_id"], "to_user_id": sug["to_user_id"], "amount_rappen": sug["amount_rappen"]}
r1 = c.post(S(hid), json=p, headers=H.auth(T[0])); r2 = c.post(S(hid), json=p, headers=H.auth(T[1]))
b = bal(hid, T[0])
show("4 debtor+creditor both record the same suggested payment", f"statuses={r1.status_code},{r2.status_code}",
     f"saldi={ {nm[x['user_id']]: x['saldo_rappen'] for x in b['balances']} }",
     f"new suggestion={[(nm[t['from_user_id']], nm[t['to_user_id']], t['amount_rappen']) for t in b['settlements']]}")

# ---------------------------------------------------------------- 5 stale full-payload edit = lost update
hid, U, T = H.household(ns); nm = names(U, ns)
e = c.post(E(hid), json={"description": "Coop", "amount_rappen": 10000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0])).json()
stale = dict(e)  # Anna opens edit dialog
r = c.patch(E(hid) + e["id"], json={"amount_rappen": 25000}, headers=H.auth(T[1]))  # Ben corrects amount
# Anna saves description change with full payload (as ExpenseFormDialog does)
payload = {"description": "Coop Wocheneinkauf", "amount_rappen": stale["amount_rappen"], "paid_by_user_id": stale["paid_by_user_id"],
           "expense_date": stale["expense_date"], "split_type": "even", "participant_ids": [s["user_id"] for s in stale["shares"]]}
r2 = c.patch(E(hid) + e["id"], json=payload, headers=H.auth(T[0]))
show("5 lost update (UI sends full payload, no version)", f"Ben patch={r.status_code} amount=25000; Anna stale patch={r2.status_code} -> final amount={r2.json()['amount_rappen']}")

# ---------------------------------------------------------------- 6 PATCH semantics: split_type=even w/o participants expands to all members; participant_ids=[]
ns3 = ["Anna", "Ben", "Carla"]
hid, U, T = H.household(ns3); nm = names(U, ns3)
e = c.post(E(hid), json={"description": "Pizza", "amount_rappen": 3000, "paid_by_user_id": str(U[0]), "split_type": "even", "participant_ids": [str(U[0]), str(U[1])]}, headers=H.auth(T[0])).json()
r = c.patch(E(hid) + e["id"], json={"split_type": "even", "description": "Pizza!"}, headers=H.auth(T[0]))
show("6a PATCH {split_type:even, description} on a 2-of-3 even expense", f"status={r.status_code} shares={[(nm[s['user_id']], s['amount_rappen']) for s in r.json()['shares']]}")
r = c.post(E(hid), json={"description": "Empty", "amount_rappen": 3000, "paid_by_user_id": str(U[0]), "split_type": "even", "participant_ids": []}, headers=H.auth(T[0]))
show("6b create even with participant_ids=[]", f"status={r.status_code} shares={[(nm[s['user_id']], s['amount_rappen']) for s in r.json().get('shares', [])]}")

# ---------------------------------------------------------------- 7 amount bounds (Integer column)
from fastapi.testclient import TestClient
from app.main import app
craw = TestClient(app, raise_server_exceptions=False)
for amt in (2**31 - 1, 2**31, 10**12):
    r = craw.post(E(hid), json={"description": "big", "amount_rappen": amt, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0]))
    show(f"7 create expense amount={amt}", f"status={r.status_code} body={r.text[:120]}")
for path, body in ((E(hid), {"description": "big", "amount_rappen": 2**31, "paid_by_user_id": str(U[0]), "split_type": "even"}),
                   (S(hid), {"from_user_id": str(U[1]), "to_user_id": str(U[0]), "amount_rappen": 2**31}),):
    r = craw.post(path, json=body, headers=H.auth(T[0]))
    show(f"7b (no raise) POST {path.split('/')[-2]} amount=2^31", f"status={r.status_code} body={r.text[:100]}")
r = craw.put(f"/api/households/{hid}/budget", json={"month": "2026-10-01", "amount_rappen": 2**31}, headers=H.auth(T[0]))
show("7c budget amount=2^31", f"status={r.status_code}")
r = craw.post(B(hid), json={"name": "x", "amount_rappen": 2**31, "day_of_month": 1}, headers=H.auth(T[0]))
show("7d bill amount=2^31", f"status={r.status_code}")
# balance aggregation overflow? 2 expenses of 2^31-1
hidx, Ux, Tx = H.household(["A", "B"])
for _ in range(2):
    craw.post(E(hidx), json={"description": "max", "amount_rappen": 2**31 - 1, "paid_by_user_id": str(Ux[0]), "split_type": "even"}, headers=H.auth(Tx[0]))
r = craw.get(f"/api/households/{hidx}/expenses/balances", headers=H.auth(Tx[0]))
r2 = craw.get(f"/api/households/{hidx}/finance-summary", headers=H.auth(Tx[0]))
show("7e sum over int32 max", f"balances {r.status_code} {r.text[:200]}", f"summary {r2.status_code} total={r2.json().get('total_spent_rappen') if r2.status_code==200 else r2.text[:100]}")

# ---------------------------------------------------------------- 8 recurring bill: delete booked expense, rebook; undo-style recreate then book
hid, U, T = H.household(ns); nm = names(U, ns)
bill = c.post(B(hid), json={"name": "Internet", "amount_rappen": 6000, "day_of_month": 15, "paid_by_user_id": str(U[0])}, headers=H.auth(T[0])).json()
ex = c.post(B(hid) + bill["id"] + "/book", headers=H.auth(T[0])).json()
r = c.delete(E(hid) + ex["id"], headers=H.auth(T[0]))
r2 = c.post(B(hid) + bill["id"] + "/book", headers=H.auth(T[0]))
show("8a delete booked expense then rebook", f"delete={r.status_code} rebook={r2.status_code}")
# frontend undo of deletion re-creates the expense WITHOUT recurring_bill_id/booked_month (ExpensesView handleDeleteExpense undo)
ex2 = r2.json()
c.delete(E(hid) + ex2["id"], headers=H.auth(T[0]))
undo = c.post(E(hid), json={"description": ex2["description"], "amount_rappen": ex2["amount_rappen"], "currency": ex2["currency"],
                            "paid_by_user_id": ex2["paid_by_user_id"], "expense_date": ex2["expense_date"], "split_type": "even",
                            "participant_ids": [s["user_id"] for s in ex2["shares"]]}, headers=H.auth(T[0]))
summ = c.get(f"/api/households/{hid}/finance-summary", headers=H.auth(T[0])).json()
pend = [(p["name"], p["is_booked_this_month"]) for p in summ["pending_bills"]]
r3 = c.post(B(hid) + bill["id"] + "/book", headers=H.auth(T[1]))
summ2 = c.get(f"/api/households/{hid}/finance-summary", headers=H.auth(T[0])).json()
lst = c.get(E(hid), headers=H.auth(T[0])).json()
show("8b delete booked expense -> Undo (re-create) -> bill shows unbooked -> book again",
     f"undo create={undo.status_code} recurring_bill_id={undo.json()['recurring_bill_id']}", f"pending after undo={pend}",
     f"second book={r3.status_code}", f"expenses named Internet this month={sum(1 for e in lst if e['description']=='Internet')} total_spent={summ2['total_spent_rappen']}")

# ---------------------------------------------------------------- 9 booking: inactive, member joined later, payer left
hid, U, T = H.household(ns); nm = names(U, ns)
bill = c.post(B(hid), json={"name": "Strom", "amount_rappen": 10001, "day_of_month": 28, "paid_by_user_id": str(U[1])}, headers=H.auth(T[0])).json()
cid, ctok = H.add_member(hid, "Carla")
r = c.post(f"/api/households/{hid}/leave", headers=H.auth(T[1]))  # default payer leaves
r1 = c.post(B(hid) + bill["id"] + "/book", headers=H.auth(T[0]))
r2 = c.post(B(hid) + bill["id"] + "/book", json={"paid_by_user_id": str(U[0])}, headers=H.auth(T[0]))
nm[str(cid)] = "Carla"
show("9 book after default payer left; Carla joined after bill creation",
     f"leave={r.status_code} book w/o payer={r1.status_code} {r1.json().get('detail',{}) if r1.status_code!=201 else ''}",
     f"book with override={r2.status_code} expense_date={r2.json().get('expense_date')} shares={[(nm.get(s['user_id']), s['amount_rappen']) for s in r2.json().get('shares', [])]}")
c.patch(B(hid) + bill["id"], json={"active": False}, headers=H.auth(T[0]))
r = c.post(B(hid) + bill["id"] + "/book", json={"paid_by_user_id": str(U[0])}, headers=H.auth(T[0]))
show("9b book inactive", f"status={r.status_code}")
r = c.post(B(hid), json={"name": "c", "amount_rappen": 100, "day_of_month": 3, "split_type": "custom"}, headers=H.auth(T[0]))
show("9c create bill split_type=custom (E-5: no effect)", f"status={r.status_code} split_type={r.json().get('split_type')}")

# ---------------------------------------------------------------- 10 ex-member: undo recreate of expense with ex-member fails; edit works
hid, U, T = H.household(ns3); nm = names(U, ns3)
e = c.post(E(hid), json={"description": "Ferien", "amount_rappen": 30000, "paid_by_user_id": str(U[2]), "split_type": "even"}, headers=H.auth(T[0])).json()
c.post(f"/api/households/{hid}/leave", headers=H.auth(T[2]))
b0 = bal(hid, T[0])
r = c.delete(E(hid) + e["id"], headers=H.auth(T[0]))
undo = c.post(E(hid), json={"description": e["description"], "amount_rappen": e["amount_rappen"], "paid_by_user_id": e["paid_by_user_id"],
                            "expense_date": e["expense_date"], "split_type": "even", "participant_ids": [s["user_id"] for s in e["shares"]]}, headers=H.auth(T[0]))
b1 = bal(hid, T[0])
show("10 remaining member deletes ex-member Carla's expense (Carla was owed 200), Undo",
     f"before={ {nm[x['user_id']]: x['saldo_rappen'] for x in b0['balances']} }", f"delete={r.status_code} undo={undo.status_code} {str(undo.json().get('detail'))[:100]}",
     f"after={ {nm[x['user_id']]: x['saldo_rappen'] for x in b1['balances']} }")

# ---------------------------------------------------------------- 11 user deletion (no API path) - simulate DB delete to show FK effects
hid, U, T = H.household(ns3); nm = names(U, ns3)
c.post(E(hid), json={"description": "A", "amount_rappen": 9000, "paid_by_user_id": str(U[0]), "split_type": "even"}, headers=H.auth(T[0]))
c.post(E(hid), json={"description": "C", "amount_rappen": 3000, "paid_by_user_id": str(U[2]), "split_type": "even"}, headers=H.auth(T[0]))
c.post(S(hid), json={"from_user_id": str(U[1]), "to_user_id": str(U[2]), "amount_rappen": 500}, headers=H.auth(T[0]))
b0 = bal(hid, T[0])
s = H.session(); s.execute(text("DELETE FROM household_members WHERE user_id=:u"), {"u": U[2]}); s.execute(text("DELETE FROM users WHERE id=:u"), {"u": U[2]}); s.commit()
mm = s.execute(text("SELECT e.description, e.amount_rappen, COALESCE(SUM(sh.amount_rappen),0) FROM expenses e LEFT JOIN expense_shares sh ON sh.expense_id=e.id WHERE e.household_id=:h GROUP BY e.id"), {"h": hid}).all(); s.close()
b1 = bal(hid, T[0])
show("11 SIMULATED hard delete of user Carla (no API path exists)",
     f"before sum(saldi)={sum(x['saldo_rappen'] for x in b0['balances'])} unassigned={b0['unassigned_rappen']}",
     f"after  sum(saldi)={sum(x['saldo_rappen'] for x in b1['balances'])} unassigned={b1['unassigned_rappen']} saldi={[(nm.get(x['user_id']), x['saldo_rappen']) for x in b1['balances']]}",
     f"expense amount vs sum(shares) after: {mm}")

# ---------------------------------------------------------------- 12 summary vs balances vs dashboard; month boundaries
hid, U, T = H.household(ns, tz="Pacific/Kiritimati"); nm = names(U, ns)
for d, a in (("2026-12-31", 100), ("2027-01-01", 200), ("2028-02-29", 300), ("2028-03-01", 400), ("2028-02-01", 500)):
    c.post(E(hid), json={"description": d, "amount_rappen": a, "paid_by_user_id": str(U[0]), "split_type": "even", "expense_date": d}, headers=H.auth(T[0]))
c.post(S(hid), json={"from_user_id": str(U[1]), "to_user_id": str(U[0]), "amount_rappen": 50, "settled_date": "2028-02-10"}, headers=H.auth(T[0]))
out = []
for m in ("2026-12-01", "2027-01-01", "2028-02-01", "2028-03-01"):
    out.append((m, c.get(f"/api/households/{hid}/finance-summary", params={"month": m}, headers=H.auth(T[0])).json()["total_spent_rappen"]))
dash = c.get(f"/api/households/{hid}/dashboard", headers=H.auth(T[1])).json()["finance"]
show("12 month boundaries + dashboard saldo", f"totals={out} (expect 100,200,800,400; settlements excluded)",
     f"dashboard Ben saldo={dash['saldo_rappen']} vs balances={saldi(hid, T[0])[str(U[1])]}")

# ---------------------------------------------------------------- 13 edit/delete expense from far past; expense_date range
r = c.post(E(hid), json={"description": "y1", "amount_rappen": 1, "paid_by_user_id": str(U[0]), "split_type": "even", "expense_date": "0001-01-01"}, headers=H.auth(T[0]))
r2 = c.post(E(hid), json={"description": "y9999", "amount_rappen": 1, "paid_by_user_id": str(U[0]), "split_type": "even", "expense_date": "9999-12-31"}, headers=H.auth(T[0]))
show("13 expense_date extremes", f"0001-01-01 -> {r.status_code}; 9999-12-31 -> {r2.status_code}")
r = craw.get(f"/api/households/{hid}/finance-summary", params={"month": "9999-12-01"}, headers=H.auth(T[0]))
show("13b finance-summary month=9999-12-01", f"status={r.status_code}")

# ---------------------------------------------------------------- 14 settlement deletion by non-party; ex-member settlement
hid, U, T = H.household(ns3); nm = names(U, ns3)
st_ = c.post(S(hid), json={"from_user_id": str(U[0]), "to_user_id": str(U[1]), "amount_rappen": 700}, headers=H.auth(T[0])).json()
r = c.delete(S(hid) + st_["id"], headers=H.auth(T[2]))
show("14 Carla (not a party) deletes Anna->Ben settlement", f"status={r.status_code}")
print("\nDONE")
