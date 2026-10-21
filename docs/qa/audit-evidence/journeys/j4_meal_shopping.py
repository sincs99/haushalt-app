import sys; sys.path.insert(0, __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), ".."))
import pgharness as H
H.fresh_db("j4")
c = H.client()
hid, (A, B), (tA, tB) = H.household(["Anna", "Ben"])
P = f"/api/households/{hid}"; ha, hb = H.auth(tA), H.auth(tB)
# Two shopping lists: "Lebensmittel" (first) and "Wochenmarkt" (user's active list in UI)
l1 = c.post(P + "/shopping-lists/", json={"name": "Lebensmittel"}, headers=ha).json()
l2 = c.post(P + "/shopping-lists/", json={"name": "Wochenmarkt"}, headers=ha).json()
c.post(P + "/shopping-items/", json={"name": "Mehl", "list_id": l2["id"]}, headers=ha)
c.post(P + "/shopping-items/", json={"name": "Eier", "list_id": l1["id"]}, headers=ha)
r1 = c.post(P + "/recipes/", json={"name": "Zopf", "ingredients": ["500 g Mehl", "Eier", "Butter", "Butter"]}, headers=ha).json()
r2 = c.post(P + "/recipes/", json={"name": "Pasta", "ingredients": ["Pasta", "Tomaten"]}, headers=ha).json()
day = "2026-10-17"
# Anna plans Pasta manually for Saturday
print("manual plan:", c.put(P + f"/meal-plan/{day}", json={"recipe_id": r2["id"]}, headers=ha).status_code)
# Ben runs a meal poll for the same Saturday; it is decided -> overwrites Anna's plan?
poll = c.post(P + "/polls/", json={"question": "Samstag?", "poll_type": "meal", "meal_date": day, "options": [{"label": "Zopf", "recipe_id": r1["id"]}, {"label": "Pizza"}]}, headers=hb).json()
print("poll created", poll.get("status"), poll.get("decided_meal_date"))
opt = poll["options"][0]["id"]
c.post(P + f"/polls/{poll['id']}/vote", json={"option_id": opt}, headers=hb)
H.emits.clear()
r = c.post(P + f"/polls/{poll['id']}/meal-decide", json={"option_id": opt}, headers=hb); print("meal-decide", r.status_code)
print("emitted events:", [(a[1], a[2] if len(a) > 2 else None) for a, k in H.emits if a[1] == "meal_plan_updated"])
week = c.get(P + "/meal-plan/?week=" + day, headers=ha).json()
print("meal plan entry for day:", [(e["date"], e.get("recipe_id") == r1["id"] and "Zopf" or e.get("recipe_id") == r2["id"] and "Pasta" or e.get("free_text")) for e in week])
# vote after decision?
r = c.post(P + f"/polls/{poll['id']}/vote", json={"option_id": poll["options"][1]["id"]}, headers=ha); print("vote after decide:", r.status_code)
# add missing ingredients twice
entry = [e for e in week if e["date"] == day][0]
for i in range(2):
    r = c.post(P + f"/meal-plan/{entry['id']}/add-missing-to-shopping", json={}, headers=ha); print("add-missing", i, r.status_code, r.json())
items = c.get(P + "/shopping-items/?include_checked=true", headers=ha).json()
print("items:", sorted((i["name"], "L1" if i["list_id"] == l1["id"] else "L2") for i in items))
# Recipe deleted after scheduling
print("delete recipe:", c.delete(P + f"/recipes/{r1['id']}", headers=ha).status_code)
week = c.get(P + "/meal-plan/?week=" + day, headers=ha).json()
print("entry after recipe delete:", [(e["date"], e.get("recipe_id"), e.get("free_text")) for e in week])
