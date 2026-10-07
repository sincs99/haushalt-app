"""Testdaten für den Mobile-Layout-Audit (qa/mobile-audit.cjs).

Legt über die API einen Haushalt mit zwei Mitgliedern, einen Nutzer ohne
Haushalt und pro Modul Daten mit Grenzfällen an (lange Namen, Umlaute,
30 Einkaufsartikel in 5 Geschäften, grosse Beträge, Termine über
Mitternacht, Rezept mit 30 Zutaten, Tags).

Voraussetzung: leere Datenbank, Backend auf :8000 mit RATELIMIT_ENABLED=false
(Registrierung ist sonst auf 3/Stunde begrenzt).

    python qa/seed-testdata.py qa/mobile/seed.json
"""
import json, sys, datetime as dt, io
import requests

B = "http://localhost:8000"
S = requests.Session()
today = dt.date.today()


def call(method, path, token=None, **kw):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = S.request(method, B + path, headers=h, **kw)
    if r.status_code >= 400:
        print("ERR", method, path, r.status_code, r.text[:300], file=sys.stderr)
        r.raise_for_status()
    return r.json() if r.text else None


def login(email):
    r = requests.post(B + "/api/auth/login", data={"username": email, "password": "Testpasswort123!"})
    r.raise_for_status()
    return r.json()["access_token"]


reg = call("post", "/api/auth/register", json={
    "email": "anna@example.ch", "password": "Testpasswort123!",
    "display_name": "Anna-Lena Müller-Lüdenscheidt",
    "household_name": "WG Zürichbergstrasse 123 – Dachgeschoss links"})
tok = login("anna@example.ch")
me = call("get", "/api/auth/me", tok)
h0 = me["households"][0]
hid = h0.get("id") or h0.get("household_id")
code = call("get", f"/api/households/{hid}/invite-code", tok)["invite_code"]
print("invite", code)
call("post", "/api/auth/register", json={
    "email": "bjoern@example.ch", "password": "Testpasswort123!",
    "display_name": "Björn Österreicher", "invite_code": code})
tok2 = login("bjoern@example.ch")
# third user without household (leaves own)
call("post", "/api/auth/register", json={
    "email": "nohh@example.ch", "password": "Testpasswort123!",
    "display_name": "Ohne Haushalt", "household_name": "Temp"})
tok3 = login("nohh@example.ch")
h3 = call("get", "/api/auth/me", tok3)["households"][0]
h3 = h3.get("id") or h3.get("household_id")
call("post", f"/api/households/{h3}/leave", tok3)

members = call("get", f"/api/households/{hid}/members", tok)
uid = [m for m in members if m["display_name"].startswith("Anna")][0]["id"]
uid2 = [m for m in members if m["display_name"].startswith("Björn")][0]["id"]
H = f"/api/households/{hid}"

# --- Shopping
l1 = call("post", H + "/shopping-lists/", tok, json={"name": "Wocheneinkauf Grossverteiler & Bioladen"})
l2 = call("post", H + "/shopping-lists/", tok, json={"name": "Baumarkt"})
call("post", H + "/shopping-lists/", tok, json={"name": "Apotheke"})
stores = ["Migros Zürich HB", "Coop City Bahnhofstrasse", "Denner", "Bioladen „Grüne Wiese“", None]
names = ["Milch", "Vollkornbrot vom Bäcker (ungeschnitten, mit Sonnenblumenkernen)", "Äpfel Gala", "Rüebli", "Käse Gruyère AOP rezent",
         "Eier (Freiland)", "Tomaten", "Olivenöl extra vergine", "Teigwaren Spaghettoni No. 5", "Reis Basmati",
         "Joghurt Nature", "Butter", "Mehl Typ 405", "Zucker", "Salz", "Pfeffer schwarz gemahlen", "Kaffeebohnen",
         "Tee Pfefferminze", "Orangensaft frisch gepresst", "Mineralwasser mit Kohlensäure 6×1.5 l", "Spülmittel",
         "Toilettenpapier 3-lagig Recycling 24 Rollen", "Zahnpasta", "Shampoo", "Waschmittel Colorwäsche",
         "Bananen", "Zwiebeln", "Knoblauch", "Petersilie glatt", "Schokolade Crémant 70%"]
for i, n in enumerate(names):
    call("post", H + "/shopping-items/", tok, json={
        "name": n, "list_id": l1["id"], "quantity": ["1", "2 kg", "500 g", "3 Stück", "1 Packung à 12", None][i % 6],
        "store": stores[i % len(stores)], "assigned_to_user_id": uid2 if i % 7 == 0 else None})
for n in ["Schrauben M4×20", "Wandfarbe Weiss matt 10 l"]:
    call("post", H + "/shopping-items/", tok, json={"name": n, "list_id": l2["id"], "store": "Jumbo Baumarkt Dietlikon"})

# --- Todos
for i, t in enumerate([
    "Steuererklärung 2025 ausfüllen und alle Belege für die Krankenkasse zusammensuchen",
    "Velo in den Service bringen", "Kündigung Swisscom", "Fenster putzen", "Geschenk für Grossmutter",
    "Wohnungsabnahme vorbereiten: Löcher spachteln, Backofen reinigen, Kalk entfernen"]):
    due = (dt.datetime.combine(today, dt.time(9)) + dt.timedelta(days=i - 2)).isoformat() + "Z"
    call("post", H + "/todos/", tok, json={"title": t, "description": "Längere Beschreibung mit Details." if i % 2 else None,
                                         "due_date": due, "assigned_to_user_id": [uid, uid2, None][i % 3],
                                         "tags": ["Finanzen", "Dringend", "Wohnung-Übergabe"][: i % 4]})

# --- Chores
for i, c in enumerate(["Badezimmer gründlich putzen inkl. Dusche entkalken", "Staubsaugen", "Altpapier & Karton bündeln", "Kühlschrank ausmisten"]):
    rec = ["weekly", "biweekly", "monthly", "weekly"][i]
    body = {"title": c, "recurrence": rec, "rotation_order": [uid, uid2] if i % 2 == 0 else [uid2, uid]}
    if rec == "monthly":
        body["day_of_month"] = 15
    else:
        body["weekday"] = i
    call("post", H + "/chores/", tok, json=body)

# --- Expenses
exp = [("Monatsmiete Oktober inkl. Nebenkosten", 245000_00, uid), ("Migros", 87_45, uid2), ("Neues Sofa (Occasion)", 1_299_95, uid),
       ("Internet", 49_90, uid2), ("Pizza", 32_00, uid), ("Ferienwohnung Engadin Skiferien Februar", 3_456_80, uid2)]
for i, (d, a, p) in enumerate(exp * 2):
    call("post", H + "/expenses/", tok, json={"description": d, "amount_rappen": a, "paid_by_user_id": p,
                                             "split_type": "even", "expense_date": (today - dt.timedelta(days=i * 3)).isoformat(),
                                             "category": ["Wohnen", "Lebensmittel", "Freizeit"][i % 3]})
call("post", H + "/settlements/", tok, json={"from_user_id": uid2, "to_user_id": uid, "amount_rappen": 500_00, "note": "Twint"})
call("put", H + "/budget", tok, json={"month": today.replace(day=1).isoformat(), "amount_rappen": 2_500_00})
call("post", H + "/recurring-bills/", tok, json={"name": "Krankenkasse Grundversicherung + Zusatz", "amount_rappen": 1_234_55, "day_of_month": 25, "paid_by_user_id": uid})
call("post", H + "/recurring-bills/", tok, json={"name": "Serafe", "amount_rappen": 335_00, "day_of_month": 1})

# --- Calendar
cals = call("get", H + "/calendars/", tok)
cal = cals[0]["id"] if cals else call("post", H + "/calendars/", tok, json={"name": "Familie", "color": "#3F827A"})["id"]
call("post", H + "/calendars/", tok, json={"name": "Arbeit & Schichtdienst", "color": "#9C6E79"})
tz = lambda d, h, m=0: dt.datetime.combine(d, dt.time(h, m)).isoformat()
call("post", H + "/events/", tok, json={"title": "Geburtstagsparty bei Björn (bis spät in die Nacht)", "starts_at": tz(today, 20),
                                       "ends_at": tz(today + dt.timedelta(days=1), 2, 30), "calendar_id": cal, "participant_ids": [uid, uid2]})
call("post", H + "/events/", tok, json={"title": "Zahnarzt", "starts_at": tz(today, 8), "ends_at": tz(today, 9), "calendar_id": cal})
call("post", H + "/events/", tok, json={"title": "Ferien", "starts_at": tz(today + dt.timedelta(days=3), 0), "all_day": True, "calendar_id": cal})
for k in range(4):
    call("post", H + "/events/", tok, json={"title": f"Termin {k+1} mit sehr langem Titel zum Testen", "starts_at": tz(today, 10 + k), "calendar_id": cal})
call("post", H + "/polls/", tok, json={"question": "Wann machen wir den Frühlingsputz im ganzen Haus?",
                                      "options": [{"label": "Samstag Vormittag", "starts_at": tz(today + dt.timedelta(days=5), 9)},
                                                  {"label": "Sonntag Nachmittag nach dem Brunch", "starts_at": tz(today + dt.timedelta(days=6), 14)}]})

# --- Pets
pet = call("post", H + "/pets/", tok, json={"name": "Prinzessin Mausi von Schnurrhausen", "breed": "Europäisch Kurzhaar",
                                           "birthdate": "2019-04-01", "weight_grams": 4350, "chip_number": "756098100123456",
                                           "insurance": "Epona Tierversicherung Premium", "vet_name": "Tierarztpraxis Dr. med. vet. Grünenfelder",
                                           "food_notes": "Morgens Nassfutter, abends Trockenfutter (nierenschonend).",
                                           "health_entries": [{"title": "Impfung", "subtitle": "Katzenschnupfen + Seuche fällig", "severity": "yellow"}]})
call("post", H + "/pets/", tok, json={"name": "Kater"})
call("post", H + f"/pets/{pet['id']}/medications", tok, json={"name": "Semintra 4 mg/ml", "dosage": "0.9 ml", "schedule": "täglich morgens"})
call("post", H + f"/pets/{pet['id']}/care-tasks/", tok, json={"name": "Krallen schneiden und Fell bürsten", "interval_days": 14, "next_due_at": today.isoformat()})
call("post", H + f"/pets/{pet['id']}/feedings", tok, json={"slot": "morning"})

# --- Plants
pl = call("post", H + "/plants/", tok, json={"name": "Monstera deliciosa „Thai Constellation“ im Wohnzimmer", "species": "Monstera deliciosa var. variegata",
                                            "location": "Wohnzimmer, Südfenster neben dem Bücherregal", "notes": "Nicht zu nass halten."})
call("post", H + "/plants/", tok, json={"name": "Basilikum", "location": "Küche"})
call("post", H + "/plants/", tok, json={"name": "Ficus", "location": "Büro"})
call("post", H + f"/plants/{pl['id']}/care-tasks/", tok, json={"care_type": "water", "interval_days": 7, "next_due_at": (today - dt.timedelta(days=2)).isoformat()})
call("post", H + f"/plants/{pl['id']}/care-tasks/", tok, json={"care_type": "fertilize", "interval_days": 30})
call("post", H + f"/plants/{pl['id']}/care-tasks/", tok, json={"care_type": "other", "label": "Blätter abstauben und auf Schädlinge kontrollieren", "interval_days": 21})

# --- Food
ing = [f"{q} {n}" for q, n in zip(["200 g", "1", "2 EL", "500 ml", "1 Prise", "3", "250 g", "1 Bund", "100 g", "2"] * 3,
                                     ["Mehl", "Zwiebel", "Olivenöl", "Gemüsebouillon", "Salz", "Knoblauchzehen", "Champignons", "Petersilie",
                                      "Parmesan gerieben", "Eier"] * 3)]
r1 = call("post", H + "/recipes/", tok, json={"name": "Risotto ai funghi porcini mit getrüffeltem Parmesan und Rucola", "servings": 4,
                                             "cost_rappen": 2450, "duration_min": 45, "ingredients": ing, "steps": [f"Schritt {i}: Rühren und warten." for i in range(1, 12)],
                                             "tags": ["Vegetarisch", "Italienisch", "Wochenende", "Aufwendig"], "is_favorite": True})
r2 = call("post", H + "/recipes/", tok, json={"name": "Älplermagronen", "servings": 2, "ingredients": ["Magronen", "Kartoffeln", "Käse"], "tags": ["Schweiz"]})
for i in range(7):
    d = today + dt.timedelta(days=i - today.weekday())
    body = {"recipe_id": [r1, r2][i % 2]["id"]} if i % 3 else {"free_text": "Resten vom Vortag aufwärmen oder Pizza bestellen"}
    call("put", H + f"/meal-plan/{d.isoformat()}", tok, json=body)

# --- Notes
call("post", H + "/notes/", tok, json={"title": "WLAN-Passwort & Router-Zugangsdaten für Gäste", "body": "SSID: WG-Zuerichberg-5GHz\nPasswort: Sehr-lang-und-ohne-Leerzeichen-1234567890abcdef", "tag": "Wichtig", "pinned": True})
for i in range(5):
    call("post", H + "/notes/", tok, json={"title": f"Notiz {i+1}", "body": "Lorem ipsum dolor sit amet. " * (i + 1), "tag": ["Rezepte", None, "Ideen"][i % 3]})

# --- Documents (upload a tiny pdf)
pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
files = [("files", ("Mietvertrag.pdf", io.BytesIO(pdf), "application/pdf"))]
r = S.post(B + H + "/documents/upload", headers={"Authorization": f"Bearer {tok}"}, files=files,
           data={"title": "Mietvertrag Wohnung Zürichbergstrasse 123 inkl. Anhang Hausordnung", "category": "contract",
                 "document_date": "2024-03-01", "expiry_date": (today + dt.timedelta(days=20)).isoformat()})
print("doc upload", r.status_code, r.text[:200])
for t in ["Garantie Waschmaschine", "Rechnung Zahnarzt"]:
    S.post(B + H + "/documents/upload", headers={"Authorization": f"Bearer {tok}"},
           files=[("files", ("x.pdf", io.BytesIO(pdf), "application/pdf"))], data={"title": t, "category": "warranty"})

# --- Tags
tag = call("post", H + "/tags/", tok, json={"label": "Futterschale Küche – Mausi füttern", "target_type": "pet", "target_id": pet["id"], "action": "pet.feed"})
call("post", H + "/tags/", tok, json={"label": "Einkaufsliste", "target_type": "shopping_list", "target_id": l1["id"], "action": "shopping_list.open"})
call("post", H + "/tags/", tok, json={"label": "Monstera giessen", "target_type": "plant", "target_id": pl["id"], "action": "plant.water"})

out = {"hid": hid, "pet": pet["id"], "plant": pl["id"], "tag": tag, "invite": code}
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(json.dumps(out)[:500])
