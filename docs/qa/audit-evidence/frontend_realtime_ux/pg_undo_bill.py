import sys
sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("fe_rt_3")
c = H.client(); hid, users, toks = H.household(["Anna","Ben"]); A = H.auth(toks[0]); b=f"/api/households/{hid}"
bill = c.post(f"{b}/recurring-bills/", json={"name":"Miete","amount_rappen":200000,"day_of_month":1,"paid_by_user_id":str(users[0])}, headers=A).json()
e = c.post(f"{b}/recurring-bills/{bill['id']}/book", json={}, headers=A); print("book", e.status_code); e=e.json()
print("delete expense", c.delete(f"{b}/expenses/{e['id']}", headers=A).status_code)
# UI undo = ExpensesView.handleDeleteExpense undo payload (no recurring_bill_id)
u = c.post(f"{b}/expenses/", json={"description":e['description'],"amount_rappen":e['amount_rappen'],"paid_by_user_id":e['paid_by_user_id'],"expense_date":e['expense_date'],"split_type":e['split_type'],"category":e.get('category'),"participant_ids":[s['user_id'] for s in e['shares']]}, headers=A)
print("undo re-create", u.status_code, "recurring_bill_id:", u.json().get('recurring_bill_id'))
s = c.get(f"{b}/finance-summary", headers=A).json()
print("summary pending bills:", [(p['name'], p['is_booked_this_month']) for p in s['pending_bills']])
e2 = c.post(f"{b}/recurring-bills/{bill['id']}/book", json={}, headers=A); print("book again", e2.status_code)
ex = c.get(f"{b}/expenses/", headers=A).json(); print("expenses 'Miete' this month:", sum(1 for x in ex if x['amount_rappen']==200000))
