# 🔒 Security Review: Todo-Reminders

**Datum:** 2026-08-10  
**Reviewer:** Security-Review Agent  
**Scope:** Reminder-CRUD, Dashboard-Integration, Frontend  
**Status:** ✅ Abgeschlossen — 1 mittleres, 2 geringe Findings

---

## Geprüfte Dateien

| Schicht | Datei | Relevanz |
|---------|-------|----------|
| Model | `backend/app/models.py` (Z. 239–265) | `TodoReminder` Datenmodell |
| Router | `backend/app/routers/todos.py` (Z. 322–405) | `create_reminder()`, `delete_reminder()` |
| Dashboard | `backend/app/routers/dashboard.py` (Z. 290–312) | `upcoming_reminders` Query |
| Deps | `backend/app/core/deps.py` | `verify_household_access` |
| Tests | `backend/tests/test_todo_reminders.py` | 8 Tests inkl. Cross-Tenant |
| Frontend | `frontend/src/repositories/todosRepository.ts` | API-Calls |
| Frontend | `frontend/src/stores/todos.ts` | Store-Actions |
| Frontend | `frontend/src/components/TodoList.vue` | Reminder-UI |

---

## 1. Multi-Tenant-Scoping (IDOR) — ✅ Bestanden

### create_reminder (POST `/{todo_id}/reminders/`)

| Prüfpunkt | Status | Evidenz |
|-----------|--------|---------|
| `verify_household_access` Dependency | ✅ | `todos.py:327` |
| Todo-Query filtert auf `household_id` | ✅ | `todos.py:334` — `Todo.household_id == household_id` |
| Reminder bekommt `household_id` aus URL-Path | ✅ | `todos.py:352` — `household_id=household_id` |
| Cross-Tenant-Test vorhanden | ✅ | `test_todo_reminders.py:33–40` → 403 |

**Bewertung:** User A kann **keinen** Reminder in Household B erstellen. Die URL-`household_id` wird sowohl für die Membership-Prüfung als auch für den Todo-Lookup und die Reminder-Erstellung verwendet.

### delete_reminder (DELETE `/{todo_id}/reminders/{reminder_id}`)

| Prüfpunkt | Status | Evidenz |
|-----------|--------|---------|
| `verify_household_access` Dependency | ✅ | `todos.py:375` |
| Todo-Query filtert auf `household_id` | ✅ | `todos.py:381–382` — `Todo.household_id == household_id` |
| Reminder validiert gegen `todo_id` | ✅ | `todos.py:392` — `reminder.todo_id != todo_id` |
| Cross-Tenant-Test vorhanden | ✅ | `test_todo_reminders.py:57–62` → 403 |

**Bewertung:** Die Validierungskette `household_id → todo → reminder` ist korrekt. Selbst wenn ein Angreifer eine gültige `reminder_id` aus einem anderen Haushalt rät, schlägt die Prüfung `reminder.todo_id != todo_id` fehl, weil das Todo bereits gegen die `household_id` validiert wurde.

### Dashboard upcoming_reminders

| Prüfpunkt | Status | Evidenz |
|-----------|--------|---------|
| `verify_household_access` Dependency | ✅ | `dashboard.py:127` |
| Query filtert auf `TodoReminder.household_id` | ✅ | `dashboard.py:294` |
| Zusätzlicher Join-Filter auf `Todo.is_done` | ✅ | `dashboard.py:297` (F-03 Fix) |

### list_todos (GET `/`) — Reminders in Response

| Prüfpunkt | Status | Evidenz |
|-----------|--------|---------|
| Todo-Query filtert auf `household_id` | ✅ | `todos.py:162` |
| `selectinload(Todo.reminders)` lädt nur zugehörige Reminders | ✅ | ORM-Eigenschaft, keine Cross-Tenant-Leak-Gefahr |

---

## 2. Autorisierung — ✅ Bestanden

| Endpoint | Auth-Dependency | Status |
|----------|----------------|--------|
| `POST /{todo_id}/reminders/` | `verify_household_access` | ✅ |
| `DELETE /{todo_id}/reminders/{reminder_id}` | `verify_household_access` | ✅ |
| `GET /dashboard` (Reminders) | `verify_household_access` | ✅ |
| `GET /todos/` (inkl. Reminders) | `verify_household_access` | ✅ |

**IDOR via `reminder_id`:** Nicht möglich. Der Angreifer müsste gleichzeitig eine gültige `household_id` (wo er Mitglied ist), eine dazu passende `todo_id` UND eine `reminder_id` die zu diesem Todo gehört, kennen. Die Ketten-Validierung verhindert Cross-Tenant-Zugriff.

---

## 3. Input-Validierung

### 3.1 `remind_at` Zukunfts-Validierung — ✅ Bestanden

```python
# todos.py:33-43 — ReminderCreate
@field_validator("remind_at")
@classmethod
def remind_at_must_be_future(cls, v: datetime) -> datetime:
    if v.tzinfo is None:
        v = v.replace(tzinfo=tz.utc)
    if v <= datetime.now(timezone.utc):
        raise ValueError("remind_at must be in the future")
    return v
```

- Pydantic v2 `field_validator` wird bei **jeder** Deserialisierung ausgeführt → nicht umgehbar
- Naive Datetimes (ohne Timezone) werden korrekt als UTC behandelt ✅
- Test `test_todo_reminders.py:17` verifiziert funktionalen Pfad

### 3.2 Max-5-Limit — ⚠️ Finding S-01

```python
# todos.py:344-348
if len(todo.reminders) >= 5:
    raise HTTPException(status_code=422, ...)
```

**Siehe Finding S-01 weiter unten.**

### 3.3 Fehlende Obergrenze für `remind_at` — ℹ️ Finding S-03

**Siehe Finding S-03 weiter unten.**

---

## 4. Datenexposition — ✅ Bestanden

### TodoReminderResponse (`todos.py:20–27`)

| Feld | Exponiert | Sensitivität |
|------|-----------|--------------|
| `id` | ✅ | Keine — UUID |
| `todo_id` | ✅ | Keine — für Frontend-Zuordnung nötig |
| `remind_at` | ✅ | Keine — funktional benötigt |
| `notified_at` | ✅ | Keine — UI-Status |
| `created_at` | ✅ | Keine — Audit |
| **`household_id`** | **❌ Nicht exponiert** | **✅ Korrekt ausgeschlossen** |

### DashboardReminderItem (`dashboard.py:94–98`)

| Feld | Exponiert | Bewertung |
|------|-----------|-----------|
| `id` | ✅ | Minimal nötig |
| `todo_id` | ✅ | Für Navigation |
| `todo_title` | ✅ | UX-relevant |
| `remind_at` | ✅ | Funktional |

### Frontend-Typen (`types/index.ts:39–45`)

Das `TodoReminder`-Interface matched exakt die Backend-Response — keine überflüssigen Felder.

**Bewertung:** Minimale Datenexposition. Keine internen IDs (`household_id`) oder sensible Felder werden preisgegeben.

---

## 5. Rate Limiting — ⚠️ Finding S-02

Es existiert **kein Rate-Limiting** im gesamten Backend (kein `slowapi`, kein Custom-Middleware). Für die Reminder-Endpoints bedeutet das:

**Siehe Finding S-02 weiter unten.**

---

## 6. SQL-Injection / ORM-Sicherheit — ✅ Bestanden

| Query | Methode | Sicher |
|-------|---------|--------|
| Todo-Lookup in `create_reminder` | `db.query(Todo).filter(...)` | ✅ ORM |
| Todo-Lookup in `delete_reminder` | `db.query(Todo).filter(...)` | ✅ ORM |
| Reminder-Lookup in `delete_reminder` | `db.get(TodoReminder, reminder_id)` | ✅ ORM PK-Lookup |
| Dashboard-Query | `db.query(TodoReminder).join(Todo).filter(...)` | ✅ ORM |

- Alle Path-Parameter sind als `uuid.UUID` typisiert → FastAPI validiert das Format **vor** Erreichen der Route
- **Kein Raw-SQL** gefunden
- **Keine String-Konkatenation** in Queries

---

## 7. Zusätzliche Prüfungen

### Cascade-Deletes ✅

| FK-Beziehung | ondelete | Bewertung |
|-------------|----------|-----------|
| `TodoReminder.todo_id → todos.id` | `CASCADE` | ✅ Reminder wird gelöscht wenn Todo gelöscht |
| `TodoReminder.household_id → households.id` | `CASCADE` | ✅ Cleanup bei Haushalt-Löschung |
| `Todo.reminders` Relationship | `cascade="all, delete-orphan"` | ✅ ORM-Level Cleanup |

### F-04 Fix: Bereinigung bei Erledigung ✅

```python
# todos.py:234-237
if update_data["is_done"] is True:
    item.done_at = datetime.now(timezone.utc)
    for reminder in item.reminders:
        if reminder.notified_at is None:
            reminder.notified_at = datetime.now(timezone.utc)
```

Offene Reminders werden als `notified` markiert, wenn das Todo erledigt wird. Dies verhindert Phantom-Benachrichtigungen.

### Fehlerbehandlung ✅

- Strukturierte Error-Codes via `error_detail()` → kein Leaken von Interna
- 404 statt 403 bei "nicht gefunden" (korrekt — verhindert Enumeration)

---

## Findings

### S-01: Race Condition beim Max-5-Limit (Mittel ⚠️)

| | |
|---|---|
| **Schweregrad** | Mittel |
| **Kategorie** | Input-Validierung / Business Logic |
| **Datei** | [`create_reminder()`](backend/app/routers/todos.py:344) |
| **Beschreibung** | Das Max-5-Limit wird applikationsseitig geprüft (`len(todo.reminders) >= 5`), aber es gibt keinen DB-Level-Constraint. Bei zwei gleichzeitigen Requests (Race Condition) könnten beide 4 Reminders lesen und je einen 5. erstellen → Ergebnis: 6 Reminders. |
| **Risiko** | Gering in der Praxis (Haushalts-App, wenige Concurrent-User), aber prinzipiell ausnutzbar. |
| **Empfehlung** | **Option A (empfohlen):** DB-Level CHECK-Constraint oder Trigger hinzufügen. **Option B:** Pessimistisches Locking mit `SELECT ... FOR UPDATE` auf das Todo beim Reminder-Erstellen. **Option C (pragmatisch):** Akzeptieren — der Impact ist minimal (6 statt 5 Reminders). |

### S-02: Kein Rate-Limiting auf Reminder-Endpoints (Gering ℹ️)

| | |
|---|---|
| **Schweregrad** | Gering (im Kontext der Gesamtapp: Mittel) |
| **Kategorie** | Rate Limiting / DoS-Schutz |
| **Datei** | [`create_reminder()`](backend/app/routers/todos.py:322), [`delete_reminder()`](backend/app/routers/todos.py:370) |
| **Beschreibung** | Es gibt kein Rate-Limiting im gesamten Backend. Ein authentifizierter User könnte in schneller Folge Reminders erstellen/löschen/erstellen (Churn). Das Max-5-Limit begrenzt zwar die Gesamtzahl pro Todo, aber der Churn verursacht DB-Writes und Socket-Events. |
| **Risiko** | Gering — erfordert Authentifizierung, und der Impact ist auf das eigene Household beschränkt. |
| **Empfehlung** | **Globale Empfehlung:** `slowapi` oder ähnliches Rate-Limiting für alle mutierenden Endpoints einführen (z.B. 60 req/min pro User). Dies ist kein Reminder-spezifisches Problem, sondern betrifft die gesamte App. |

### S-03: Fehlende Obergrenze für `remind_at` (Gering ℹ️)

| | |
|---|---|
| **Schweregrad** | Gering |
| **Kategorie** | Input-Validierung |
| **Datei** | [`ReminderCreate`](backend/app/routers/todos.py:30) |
| **Beschreibung** | Der `remind_at`-Validator prüft nur, dass das Datum in der Zukunft liegt. Es gibt keine Obergrenze — ein User könnte `remind_at: "9999-12-31T23:59:59Z"` senden. |
| **Risiko** | Minimal — verursacht keine Sicherheitslücke, nur potenziell unsinnige Daten. |
| **Empfehlung** | Obergrenze von z.B. 2 Jahren hinzufügen: `if v > datetime.now(timezone.utc) + timedelta(days=730): raise ValueError(...)` |

---

## Zusammenfassung

| Prüfbereich | Ergebnis | Details |
|------------|----------|---------|
| **Multi-Tenant-Scoping (IDOR)** | ✅ Bestanden | Dreifach-Validierung: Membership → Todo → Reminder |
| **Autorisierung** | ✅ Bestanden | Alle Endpoints durch `verify_household_access` geschützt |
| **Input-Validierung** | ⚠️ 2 Findings | S-01 Race Condition (Mittel), S-03 Obergrenze (Gering) |
| **Datenexposition** | ✅ Bestanden | `household_id` nicht exponiert, minimale Response |
| **Rate Limiting** | ℹ️ 1 Finding | S-02 Kein Rate-Limiting (Gering/Global) |
| **SQL-Injection** | ✅ Bestanden | Ausschließlich ORM-Queries, UUID-typisierte Params |
| **Testabdeckung** | ✅ Gut | 8 Tests, inkl. Cross-Tenant POST/DELETE |

### Gesamtbewertung: **Gut** 🟢

Die Reminder-Implementierung ist sicherheitstechnisch solide. Die `verify_household_access`-Dependency wird konsistent eingesetzt, und die Ketten-Validierung (`household → todo → reminder`) verhindert IDOR-Angriffe effektiv. Die drei Findings sind niedrig priorisiert und erfordern keine sofortige Behebung vor einem Release.

**Empfohlene Priorität für Fixes:**
1. S-01 (Race Condition) — Vor Skalierung auf viele User beheben
2. S-02 (Rate Limiting) — Als globales Thema in einem eigenen Epic adressieren
3. S-03 (Obergrenze) — Kann jederzeit nachgerüstet werden
