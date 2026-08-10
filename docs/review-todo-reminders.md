# Business-Logik-Review: Mehrere Erinnerungen pro Aufgabe (Todo-Reminders)

**Datum:** 2026-08-10  
**Reviewer-Modus:** 🧠 Business Logic Reviewer  
**Scope:** `TodoReminder` Model, CRUD-Endpoints, Dashboard-Query, Tests  

---

## 1. Fachliches Ziel

Benutzer sollen pro Todo bis zu 5 Erinnerungen (`remind_at`) anlegen können, die im Dashboard als "Upcoming Reminders" angezeigt werden. Erinnerungen werden bei Todo-Löschung automatisch entfernt (Cascade). Das Feature dient als Vorbereitung für Push-Notifications (`notified_at`-Feld).

---

## 2. Geprüfte Regeln & Zusammenfassung

| Regel | Status | Bewertung |
|---|---|---|
| Max 5 Reminders pro Todo | ⚠️ Teilweise | Applikations-Logik OK, kein DB-Constraint |
| `remind_at` Validierung | ❌ Fehlt | Vergangenheit erlaubt |
| Cascade-Löschung (Todo→Reminders) | ✅ OK | SQLAlchemy + FK `ondelete=CASCADE` |
| Dashboard-Query Filter | ⚠️ Teilweise | Erledigte Todos nicht gefiltert |
| Sortierung `remind_at ASC` | ✅ OK | Model-Level `order_by` + Dashboard-Query |
| IDOR-Schutz | ✅ OK | `verify_household_access` + FK-Prüfung |
| Socket-Events | ✅ OK | `todo_updated` mit vollständigem Todo |
| Error Codes | ✅ OK | `TOO_MANY_REMINDERS`, `REMINDER_NOT_FOUND` |

---

## 3. Findings

### F-01 — Race Condition beim Max-5-Limit ⬛ Schweregrad: HOCH

**Datei:** [`create_reminder()`](backend/app/routers/todos.py:307)  
**Zeilen 327–332:**
```python
# 2. Max 5 prüfen
if len(todo.reminders) >= 5:
    raise HTTPException(
        status_code=422,
        detail=error_detail(ErrorCode.TOO_MANY_REMINDERS, ...),
    )
```

**Problem:** Die Prüfung `len(todo.reminders) >= 5` erfolgt auf Applikationsebene mittels geladener Collection — ohne DB-Lock oder atomare DB-Prüfung. Bei zwei gleichzeitigen POST-Requests:

1. Request A liest: 4 Reminders → erlaubt
2. Request B liest: 4 Reminders → erlaubt  
3. Beide schreiben → **6 Reminders vorhanden**

**Risiko:** Datenintegritätsverletzung. Das Limit 5 ist eine reine Business-Regel ohne DB-Absicherung.

**Empfehlung:**  
- **Option A (bevorzugt):** Atomarer `SELECT COUNT(*) ... FOR UPDATE` vor dem INSERT:
  ```python
  count = db.query(func.count(TodoReminder.id)).filter(
      TodoReminder.todo_id == todo_id
  ).with_for_update().scalar()
  if count >= 5:
      raise HTTPException(422, ...)
  ```
- **Option B:** DB-Level Trigger oder CHECK-Constraint (komplex in PostgreSQL).
- **Option C (Minimum):** `UNIQUE(todo_id, remind_at)` als partielle Absicherung.

---

### F-02 — Keine Validierung von `remind_at` in der Vergangenheit ⬛ Schweregrad: HOCH

**Datei:** [`ReminderCreate`](backend/app/routers/todos.py:30)  
```python
class ReminderCreate(BaseModel):
    remind_at: datetime
```

**Problem:** Es gibt keine Validierung, dass `remind_at` in der Zukunft liegt. Ein Benutzer kann einen Reminder für `2020-01-01` erstellen. Dieser erscheint nie im Dashboard (Filter `remind_at > now`) und bleibt als "tote Daten" in der DB.

**Risiko:**
- Benutzer erstellen unbemerkt nutzlose Reminders und verbrauchen ihre 5 Slots
- Verwirrung: "Ich habe einen Reminder gesetzt, aber er erscheint nirgendwo"
- Datenqualitätsproblem

**Empfehlung:**
```python
class ReminderCreate(BaseModel):
    remind_at: datetime

    @field_validator("remind_at")
    @classmethod
    def remind_at_must_be_future(cls, v: datetime) -> datetime:
        if v <= datetime.now(timezone.utc):
            raise ValueError("remind_at must be in the future")
        return v
```

Optional: Mindestens 1 Minute in der Zukunft (Puffer gegen Latenzen).

---

### F-03 — Dashboard zeigt Reminders für erledigte Todos ⬛ Schweregrad: MITTEL

**Datei:** [`get_dashboard()`](backend/app/routers/dashboard.py:290)  
```python
upcoming_reminders_query = (
    db.query(TodoReminder, Todo.title.label("todo_title"))
    .join(Todo, TodoReminder.todo_id == Todo.id)
    .filter(
        TodoReminder.household_id == household_id,
        TodoReminder.remind_at > now,
        TodoReminder.notified_at.is_(None),
    )
    ...
)
```

**Problem:** Der Filter enthält **keinen** Check auf `Todo.is_done == False`. Wenn ein Todo erledigt wird (`is_done=True`), bleiben dessen Reminders aktiv und erscheinen weiter im Dashboard als "Upcoming Reminders".

**Risiko:** Benutzer sehen Erinnerungen für Aufgaben, die bereits erledigt sind. Das ist verwirrend und kontraproduktiv.

**Empfehlung:**
```python
.filter(
    TodoReminder.household_id == household_id,
    TodoReminder.remind_at > now,
    TodoReminder.notified_at.is_(None),
    Todo.is_done == False,  # ← NEU
)
```

Alternative: Reminders automatisch bei `is_done=True` als `notified_at=now` markieren (semantisch: "erledigt = benachrichtigt").

---

### F-04 — Keine Bereinigung bei Todo-Erledigung ⬛ Schweregrad: MITTEL

**Datei:** [`update_todo()`](backend/app/routers/todos.py:193)  
```python
if "is_done" in update_data:
    if update_data["is_done"] is True:
        item.done_at = datetime.now(timezone.utc)
    else:
        item.done_at = None
```

**Problem:** Wenn ein Todo auf `is_done=True` gesetzt wird, bleiben alle zugehörigen Reminders aktiv bestehen. Es gibt keine Logik, die Reminders bei Erledigung bereinigt oder markiert.

**Risiko:**
- Verbunden mit F-03: Reminders für erledigte Todos im Dashboard
- Zukünftiges Push-Notification-System würde Benachrichtigungen für erledigte Todos senden
- Bei "Reopen" (`is_done=False→True→False`) entstehen inkonsistente Zustände

**Empfehlung:** Bei `is_done=True` alle offenen Reminders (`notified_at IS NULL`) markieren:
```python
if update_data["is_done"] is True:
    item.done_at = datetime.now(timezone.utc)
    # Offene Reminders als "erledigt" markieren
    db.query(TodoReminder).filter(
        TodoReminder.todo_id == todo_id,
        TodoReminder.notified_at.is_(None),
    ).update({"notified_at": datetime.now(timezone.utc)})
```

---

### F-05 — Kein Schutz gegen doppelte `remind_at`-Zeitpunkte ⬛ Schweregrad: NIEDRIG

**Datei:** [`create_reminder()`](backend/app/routers/todos.py:307)

**Problem:** Zwei identische `remind_at`-Zeitpunkte für dasselbe Todo sind erlaubt. Ein Benutzer kann versehentlich 5× den gleichen Zeitpunkt eintragen (z.B. durch Doppelklick im Frontend).

**Risiko:**
- Verschwendung von Reminder-Slots
- Push-System würde 5 identische Benachrichtigungen senden
- Schlechte UX

**Empfehlung:**
- **Option A (DB-Level):** `UniqueConstraint("todo_id", "remind_at")` in Migration + Model
- **Option B (App-Level):** Prüfung vor INSERT:
  ```python
  exists = db.query(TodoReminder).filter(
      TodoReminder.todo_id == todo_id,
      TodoReminder.remind_at == body.remind_at,
  ).first()
  if exists:
      raise HTTPException(409, "Duplicate reminder time")
  ```

---

### F-06 — Reminder für erledigtes Todo erstellbar ⬛ Schweregrad: NIEDRIG

**Datei:** [`create_reminder()`](backend/app/routers/todos.py:307)

**Problem:** Der Endpoint prüft nicht, ob das Todo bereits `is_done=True` ist. Ein Benutzer kann Reminders für erledigte Aufgaben hinzufügen — fachlich sinnlos.

**Empfehlung:**
```python
if todo.is_done:
    raise HTTPException(
        status_code=422,
        detail=error_detail("TODO_ALREADY_DONE", "Cannot add reminder to completed todo"),
    )
```

---

### F-07 — `delete_reminder`: IDOR-Vektor über `reminder_id` aus anderem Todo ⬛ Schweregrad: NIEDRIG (aktuell abgesichert)

**Datei:** [`delete_reminder()`](backend/app/routers/todos.py:354)  
```python
reminder = db.get(TodoReminder, reminder_id)
if not reminder or reminder.todo_id != todo_id:
    raise HTTPException(404, ...)
```

**Bewertung:** ✅ Korrekt. Die Prüfung `reminder.todo_id != todo_id` verhindert, dass ein Reminder aus einem anderen Todo gelöscht wird. Zusätzlich wird das Todo mit `household_id`-Filter geladen, sodass Cross-Household-Zugriff nicht möglich ist.

**Hinweis:** Die `household_id` des Reminders selbst wird **nicht** direkt geprüft — der Schutz erfolgt indirekt über die Todo→Household-Kette. Das ist funktional korrekt, aber ein `assert reminder.household_id == household_id` wäre als Defense-in-Depth sinnvoll.

---

## 4. Positiv-Befunde (korrekt implementiert)

| Aspekt | Details |
|---|---|
| **Cascade-Löschung** | `cascade="all, delete-orphan"` auf `Todo.reminders` + `ondelete='CASCADE'` auf FK in Migration → Doppelt abgesichert ✅ |
| **Sortierung** | `order_by="TodoReminder.remind_at"` im Model-Relationship → automatisch ASC in `TodoResponse` und `list_todos` ✅ |
| **Socket-Events** | POST + DELETE emittieren `todo_updated` mit `_todo_response(todo)` (inkl. aller Reminders) ✅ |
| **Cross-Tenant-Schutz** | `verify_household_access` als Dependency + `Todo.household_id == household_id` Filter ✅ |
| **Dashboard-Index** | `ix_todo_reminders_household_remind` auf `(household_id, remind_at)` → effiziente Dashboard-Query ✅ |
| **Household-Cascade** | `Household.todo_reminders` mit `cascade="all, delete-orphan"` → Household-Löschung räumt auf ✅ |
| **Error Codes** | `TOO_MANY_REMINDERS` und `REMINDER_NOT_FOUND` konsistent definiert ✅ |

---

## 5. Testabdeckung — Analyse

### Vorhandene Tests (8 Tests) ✅

| Test | Prüft |
|---|---|
| `test_create_reminder_success` | Happy Path POST → 201 |
| `test_create_reminder_cross_tenant_403` | Cross-Household → 403 |
| `test_delete_reminder_success` | Happy Path DELETE → 204 |
| `test_delete_reminder_cross_tenant_403` | Cross-Household → 403 |
| `test_max_5_reminders_422` | Limit-Überschreitung → 422 |
| `test_reminder_not_found_404` | Fake Reminder-ID → 404 |
| `test_list_todos_includes_reminders` | GET /todos enthält `reminders[]` |
| `test_reminders_sorted_asc` | Sortierung `remind_at ASC` |

### Fehlende Tests ❌

| Fehlender Test | Bezug zu Finding |
|---|---|
| Reminder für erledigtes Todo | F-06 |
| Reminder in der Vergangenheit | F-02 |
| Doppelter `remind_at`-Zeitpunkt | F-05 |
| 5 Reminders → einen löschen → erneut hinzufügen (Slot-Freigabe) | Edge Case |
| Todo löschen → Reminders weg (Cascade verifizieren) | Cascade |
| Dashboard: Reminder für erledigtes Todo nicht angezeigt | F-03 |
| Dashboard: `upcoming_reminders` Grundfunktion | Dashboard |
| Socket-Event bei create_reminder enthält alle Reminders | Socket |

---

## 6. Edge-Case-Analyse

### Todo mit genau 5 Reminders → einen löschen → wieder hinzufügen
**Erwartung:** Sollte funktionieren.  
**Analyse:** Ja, funktioniert korrekt. Nach DELETE wird `todo.reminders` neu geladen (`db.refresh`), und beim nächsten POST wird `len(todo.reminders)` wieder mit `selectinload` frisch geladen → 4 Reminders → erlaubt. ✅

### Reminder für ein bereits erledigtes Todo
**Erwartung:** Sollte abgelehnt werden.  
**Analyse:** Wird **nicht** geprüft → Finding F-06. ⚠️

### Zwei identische `remind_at`-Zeitpunkte
**Erwartung:** Sollte verhindert oder zumindest gewarnt werden.  
**Analyse:** Wird **nicht** geprüft → Finding F-05. ⚠️

### Todo-Reopen (`is_done: true → false`)
**Analyse:** Wenn Reminders bei Erledigung als `notified_at != NULL` markiert wurden (Empfehlung F-04), bleiben sie nach Reopen als "bereits notifiziert" bestehen. Der Benutzer müsste neue Reminders erstellen. Das ist akzeptabel und sogar gewünscht (alte Zeiten sind i.d.R. veraltet).

---

## 7. Priorisierte Empfehlungen

| Prio | Finding | Aufwand | Impact |
|---|---|---|---|
| 🔴 P1 | F-02: `remind_at` Zukunfts-Validierung | Klein (5 Zeilen) | Verhindert nutzlose Reminders |
| 🔴 P1 | F-03: Dashboard-Filter `Todo.is_done == False` | Klein (1 Zeile) | Verhindert verwirrende UX |
| 🟡 P2 | F-01: Race Condition Max-5 mit `FOR UPDATE` | Mittel (10 Zeilen) | Datenintegrität unter Last |
| 🟡 P2 | F-04: Reminders bei Erledigung markieren | Mittel (5 Zeilen) | Push-Vorbereitung |
| 🟢 P3 | F-06: Kein Reminder für erledigtes Todo | Klein (3 Zeilen) | Fachliche Konsistenz |
| 🟢 P3 | F-05: Doppelte Zeitpunkte verhindern | Mittel (DB + App) | Datenqualität |

---

## 8. Vorgeschlagene Testfälle (Akzeptanzkriterien)

```python
# T-01: Reminder in der Vergangenheit → 422
def test_reminder_in_past_rejected():
    remind_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    resp = client.post(..., json={"remind_at": remind_at})
    assert resp.status_code == 422

# T-02: Reminder für erledigtes Todo → 422
def test_reminder_on_done_todo_rejected():
    # Todo als erledigt markieren
    client.patch(..., json={"is_done": True})
    resp = client.post(...reminders/, json={"remind_at": future})
    assert resp.status_code == 422

# T-03: Dashboard filtert erledigte Todos
def test_dashboard_no_reminders_for_done_todos():
    # Reminder erstellen, Todo erledigen, Dashboard laden
    resp = client.get(.../dashboard)
    assert len(resp.json()["upcoming_reminders"]) == 0

# T-04: Slot-Freigabe nach Löschen
def test_slot_freed_after_delete():
    # 5 Reminders erstellen, einen löschen, neuen erstellen → 201
    assert resp.status_code == 201

# T-05: Cascade-Löschung
def test_cascade_delete_todo_removes_reminders():
    # Todo mit Reminders löschen, Reminder direkt in DB prüfen
    assert db.query(TodoReminder).filter_by(todo_id=todo_id).count() == 0

# T-06: Doppelte remind_at abgelehnt (nach Fix)
def test_duplicate_remind_at_rejected():
    same_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    client.post(..., json={"remind_at": same_time})
    resp = client.post(..., json={"remind_at": same_time})
    assert resp.status_code == 409
```

---

## 9. Gesamtbewertung

**Status: ⚠️ Bedingt produktionsreif**

Die Grundimplementierung ist solide: Datenmodell sauber, Cascade korrekt, Sortierung konsistent, IDOR-Schutz vorhanden, Socket-Events vollständig. Die zwei kritischsten Lücken — fehlende Zukunfts-Validierung (F-02) und Dashboard-Filter für erledigte Todos (F-03) — sind mit minimalem Aufwand zu beheben und sollten **vor Go-Live** adressiert werden. Die Race Condition (F-01) ist unter normaler Haushaltslast unkritisch, aber für saubere Architektur empfehlenswert.
