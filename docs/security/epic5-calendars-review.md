# 🔒 Security Review: Epic 5 – Mehrere Kalender (TimeTree-Style)

**Datum:** 2026-08-10  
**Reviewer:** Security Review Agent  
**Scope:** Neue Calendar-Entity, Calendar-CRUD-Router, calendar_id-Integration in Events/Polls/Dashboard, Datenmigration, Frontend  
**Gesamtbewertung:** ✅ **BESTANDEN** — Keine kritischen oder hohen Sicherheitslücken gefunden

---

## Zusammenfassung

| Schweregrad | Anzahl | Status |
|-------------|--------|--------|
| 🔴 Kritisch | 0 | — |
| 🟠 Hoch | 0 | — |
| 🟡 Mittel | 2 | Offen |
| 🟢 Gering | 3 | Offen |
| ℹ️ Info | 2 | Zur Kenntnis |

Das Calendar-Feature ist **sicherheitstechnisch solide** implementiert. Multi-Tenant-Scoping ist durchgehend korrekt, Input-Validierung ist strikt, und alle Endpoints sind durch `verify_household_access` geschützt. Die gefundenen Punkte betreffen Migration-Robustheit und Testabdeckung.

---

## 1. Multi-Tenant Scoping ✅

### 1.1 Calendar CRUD (`calendars.py`)

| Endpoint | Scoping | Bewertung |
|----------|---------|-----------|
| `GET /calendars/` | [`verify_household_access`](backend/app/core/deps.py:32) + [`Calendar.household_id == household_id`](backend/app/routers/calendars.py:94) | ✅ Korrekt |
| `POST /calendars/` | [`verify_household_access`](backend/app/core/deps.py:32) + [`household_id` aus URL-Pfad](backend/app/routers/calendars.py:111) | ✅ Korrekt |
| `PATCH /calendars/{id}` | [`verify_household_access`](backend/app/core/deps.py:32) + [`cal.household_id != household_id`](backend/app/routers/calendars.py:140) | ✅ Korrekt |
| `DELETE /calendars/{id}` | [`verify_household_access`](backend/app/core/deps.py:32) + [`cal.household_id != household_id`](backend/app/routers/calendars.py:172) | ✅ Korrekt |

**Pattern korrekt:** Calendar wird per `db.get(Calendar, calendar_id)` geladen und dann mit `cal.household_id != household_id` gegen Cross-Tenant-Zugriff geprüft. Nicht gefundene oder fremde Kalender ergeben einheitlich `404 CALENDAR_NOT_FOUND` — kein Information Leak über Existenz.

### 1.2 CALENDAR_MISMATCH (Cross-Household calendar_id in Events)

| Endpoint | Prüfung | Bewertung |
|----------|---------|-----------|
| [`POST /events/`](backend/app/routers/events.py:132-138) | `calendar.household_id != household_id` → 422 CALENDAR_MISMATCH | ✅ Korrekt |
| [`PATCH /events/{id}`](backend/app/routers/events.py:214-220) | `calendar.household_id != household_id` → 422 CALENDAR_MISMATCH | ✅ Korrekt |
| [`POST /polls/{id}/decide`](backend/app/routers/polls.py:346-351) | `calendar.household_id != household_id` → 422 CALENDAR_MISMATCH | ✅ Korrekt |

**Urteil:** Ein User kann NICHT ein Event mit einer `calendar_id` aus einem fremden Haushalt erstellen oder einem fremden Kalender zuweisen. Die Validierung erfolgt serverseitig vor dem DB-Write.

### 1.3 Dashboard (`dashboard.py`)

[`DashboardEventItem`](backend/app/routers/dashboard.py:73-78) enthält `calendar_id` als Read-Only-Feld. Die Abfrage filtert korrekt per [`Event.household_id == household_id`](backend/app/routers/dashboard.py:238). ✅ Kein Cross-Tenant-Risiko.

### 1.4 Tests

[`test_calendar_scoping.py`](backend/tests/test_calendar_scoping.py) enthält:
- ✅ Positiv: Eigene Kalender lesen (Zeile 17)
- ✅ Negativ: Fremde Kalender lesen → 403 (Zeile 34)
- ✅ Positiv: Eigenen Kalender erstellen (Zeile 50)
- ✅ Negativ: In fremdem Haushalt erstellen → 403 (Zeile 73)
- ✅ Positiv: Eigenen Kalender updaten (Zeile 93)
- ✅ Geschäftslogik: Letzten Kalender löschen → 422 (Zeile 111)
- ✅ Geschäftslogik: Kalender mit Events löschen → 422 (Zeile 127)
- ✅ Validierung: Ungültige Hex-Farbe → 422 (Zeile 178)

---

## 2. Input-Validierung ✅

### 2.1 `name` Feld

| Schicht | Validierung | Bewertung |
|---------|-------------|-----------|
| Pydantic ([`CalendarCreate`](backend/app/routers/calendars.py:20)) | `min_length=1, max_length=50` | ✅ |
| Pydantic ([`name_must_not_be_blank`](backend/app/routers/calendars.py:24-29)) | `.strip()` + Blank-Check | ✅ |
| DB ([`Calendar.name`](backend/app/models.py:535)) | `String(50), nullable=False` | ✅ |

Doppelte Absicherung (Pydantic + DB-Constraint). Whitespace-only Names werden abgefangen.

### 2.2 `color` Feld

| Schicht | Validierung | Bewertung |
|---------|-------------|-----------|
| Pydantic ([`CalendarCreate.color`](backend/app/routers/calendars.py:21)) | `max_length=7` | ✅ |
| Pydantic ([`validate_hex_color`](backend/app/routers/calendars.py:31-36)) | Regex `^#[0-9A-Fa-f]{6}$` | ✅ Strikt |
| DB ([`Calendar.color`](backend/app/models.py:536)) | `String(7), nullable=False` | ✅ |

**Regex-Analyse:** `^#[0-9A-Fa-f]{6}$` ist **sicher** — exakt 7 Zeichen, nur Hex-Digits nach `#`. Keine ReDoS-Gefahr (kein Backtracking). Werte wie `#000000;background:url(...)` oder ähnliche CSS-Injection-Versuche werden abgelehnt.

### 2.3 `position` Feld

| Schicht | Validierung | Bewertung |
|---------|-------------|-----------|
| Pydantic ([`CalendarCreate.position`](backend/app/routers/calendars.py:22)) | `ge=0` (≥ 0) | ✅ |
| DB ([`Calendar.position`](backend/app/models.py:537)) | `Integer, server_default="0"` | ✅ |

Negative Werte werden korrekt abgefangen. Keine Obergrenze definiert (s. L-2).

### 2.4 `calendar_id` (UUID)

| Stelle | Typ | Bewertung |
|--------|-----|-----------|
| [`EventCreate.calendar_id`](backend/app/routers/events.py:24) | `uuid.UUID` | ✅ Pydantic validiert Format |
| [`DecideRequest.calendar_id`](backend/app/routers/polls.py:82) | `uuid.UUID` | ✅ |
| URL-Path-Parameter | `uuid.UUID` | ✅ FastAPI validiert automatisch |

UUID-Typ wird durchgehend korrekt erzwungen. Kein String-Bypass möglich.

---

## 3. Autorisierung ✅

### 3.1 verify_household_access

Alle Calendar-Endpoints verwenden [`verify_household_access`](backend/app/core/deps.py:32-46) als Dependency:
- JWT-Token → User-ID extrahieren
- Membership-Check: `HouseholdMember.filter_by(household_id=..., user_id=...)`
- Kein Membership → 403 `NOT_HOUSEHOLD_MEMBER`

### 3.2 Admin-Gating

Aktuell kann **jedes Haushaltsmitglied** Kalender erstellen, umbenennen, umfärben und löschen. Es gibt kein Admin-Gating via [`verify_household_admin`](backend/app/core/deps.py:49-58).

**Bewertung:** Dies ist eine bewusste Designentscheidung, die zum TimeTree-Modell passt (gleichberechtigte Mitglieder). Die Löschung ist durch zwei Business-Rules geschützt:
1. [Letzter Kalender kann nicht gelöscht werden](backend/app/routers/calendars.py:178-188)
2. [Kalender mit Events kann nicht gelöscht werden](backend/app/routers/calendars.py:190-200)

→ Siehe L-1 für Empfehlung.

---

## 4. Datenmigration

### 4.1 Upgrade ✅

Die [3-Phasen-Migration](backend/migrations/versions/p1q2r3s4t5u6_add_calendars_replace_category.py:25-121) ist korrekt implementiert:
1. **Schema**: Tabelle + nullable FK erstellen
2. **Daten**: Kalender pro Haushalt aus `DISTINCT category` anlegen, `calendar_id` backfüllen
3. **Finalisieren**: `NOT NULL`, alte Spalte/Constraint droppen

Der [Fallback](backend/migrations/versions/p1q2r3s4t5u6_add_calendars_replace_category.py:105-111) für Events ohne Kategorie-Match verhindert Orphaned Records. ✅

### 4.2 Downgrade ⚠️ (M-1)

Siehe Finding M-1 unten.

---

## 5. Frontend-Sicherheit ✅

### 5.1 CSS-Injection via `:style`

`cal.color` wird an mehreren Stellen als CSS-Wert verwendet:

| Stelle | Code | Risiko |
|--------|------|--------|
| [Filter-Chips](frontend/src/views/CalendarView.vue:654-656) | `:style="{ background: cal.color, borderColor: cal.color }"` | Keines |
| [Event-Card-Bar](frontend/src/views/CalendarView.vue:761) | `:style="{ background: store.getCalendarColor(...) }"` | Keines |
| [Week-Dots](frontend/src/views/CalendarView.vue:693) | `:style="{ background: color }"` | Keines |
| [Category-Dots](frontend/src/views/CalendarView.vue:947) | `:style="{ background: cal.color }"` | Keines |

**Doppelte Absicherung:**
1. **Backend**: Regex `^#[0-9A-Fa-f]{6}$` lässt NUR valide 7-Zeichen Hex-Farben durch
2. **Vue**: Object-Syntax für `:style` bindet Werte als CSS-Property-Values — keine Injection von zusätzlichen Properties oder `url()`-Aufrufen möglich

### 5.2 XSS via `cal.name`

Alle Ausgaben verwenden Vue-Mustache-Syntax (`{{ cal.name }}`) oder Text-Content. Vue escaped HTML automatisch. ✅ Kein `v-html` im Einsatz.

### 5.3 localStorage

| Key | Inhalt | Sensibel? |
|-----|--------|-----------|
| `calendar-filter-${householdId}` | Array von Calendar-UUIDs | ❌ Nein |
| `last-calendar-${householdId}` | Einzelne Calendar-UUID | ❌ Nein |

Keine sensitiven Daten in localStorage.

---

## 6. Socket-Event-Sicherheit ✅

### 6.1 Server-seitig

- [`emit_to_household_sync`](backend/app/socket_manager.py:135-150) emittiert per `room=f"household_{household_id}"` — Events gehen NUR an Clients im richtigen Room
- [`join_household`](backend/app/socket_manager.py:61-104) prüft Membership per DB-Query vor Room-Join
- [`connect`](backend/app/socket_manager.py:33-57) validiert JWT bei Verbindungsaufbau

Calendar-Events (`calendar_created`, `calendar_updated`, `calendar_deleted`) werden ausschließlich nach erfolgreichen CRUD-Operationen mit der korrekten `household_id` emittiert. ✅

### 6.2 Client-seitig

[`handleCalendarCreated`](frontend/src/stores/calendar.ts:156-163), [`handleCalendarUpdated`](frontend/src/stores/calendar.ts:165-170), [`handleCalendarDeleted`](frontend/src/stores/calendar.ts:172-174) akzeptieren eingehende Daten ohne zusätzliche Validierung. Dies ist **akzeptabel**, da:
- Socket-Verbindung ist JWT-authentifiziert
- Room-Join ist membership-geprüft
- Server emittiert nur an den korrekten Room
→ Kein praktischer Angriffsvektor (s. L-3).

---

## Findings

### 🟡 M-1: Downgrade-Migration schlägt bei Custom-Kalendernamen fehl

**Datei:** [`p1q2r3s4t5u6_add_calendars_replace_category.py`](backend/migrations/versions/p1q2r3s4t5u6_add_calendars_replace_category.py:124-154)  
**Schweregrad:** Mittel  
**Kategorie:** Datenmigration / Availability

**Problem:** Die [Downgrade-Funktion](backend/migrations/versions/p1q2r3s4t5u6_add_calendars_replace_category.py:142-146) stellt einen `CheckConstraint` wieder her:
```sql
category IN ('arbeit','katzen','haushalt','freunde','geburtstage','essen','sonstiges')
```
Wenn User nach dem Upgrade Kalender mit Custom-Namen erstellt haben (z.B. "Sport", "Familie"), wird `LOWER(c.name)` zu Werten wie `'sport'` führen, die nicht im Constraint enthalten sind. Die Migration **bricht ab**.

**Auswirkung:** Downgrade unmöglich ohne manuellen Eingriff. Kein Datenverlust, aber Service-Impact bei Rollback.

**Empfehlung:**
```python
# Vor CheckConstraint-Erstellung: Unbekannte Kategorien auf Fallback setzen
connection.execute(sa.text(
    "UPDATE events SET category = 'sonstiges' "
    "WHERE category NOT IN ('arbeit','katzen','haushalt','freunde','geburtstage','essen','sonstiges')"
))
```

---

### 🟡 M-2: Fehlender Scoping-Test für CALENDAR_MISMATCH bei Event-Erstellung

**Datei:** [`test_calendar_scoping.py`](backend/tests/test_calendar_scoping.py)  
**Schweregrad:** Mittel  
**Kategorie:** Testabdeckung

**Problem:** Es existiert kein Test, der verifiziert:
1. Event-Erstellung mit `calendar_id` aus einem fremden Haushalt → 422 CALENDAR_MISMATCH
2. Event-Update mit fremder `calendar_id` → 422 CALENDAR_MISMATCH
3. Poll-Decide mit fremder `calendar_id` → 422 CALENDAR_MISMATCH

Der Code implementiert diese Checks korrekt, aber ohne Tests könnte ein Refactoring sie versehentlich entfernen.

**Empfehlung:** Drei Tests hinzufügen:
```python
def test_create_event_with_foreign_calendar_rejected(client, household_a, token_a, calendar_b):
    """POST Event mit calendar_id aus Household B → 422 CALENDAR_MISMATCH."""
    resp = client.post(
        f"/api/households/{household_a.id}/events/",
        headers={"Authorization": f"Bearer {token_a}"},
        json={
            "title": "Test",
            "starts_at": "2026-08-10T10:00:00",
            "calendar_id": str(calendar_b.id),
        },
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "CALENDAR_MISMATCH"
```

---

### 🟢 L-1: Kein Admin-Gating für Kalender-Löschung

**Datei:** [`calendars.py`](backend/app/routers/calendars.py:164-209)  
**Schweregrad:** Gering  
**Kategorie:** Authorization / Design

**Beobachtung:** Jedes Haushaltsmitglied kann Kalender erstellen, umbenennen und löschen. Obwohl dies zum TimeTree-Modell passt, könnte ein böswilliges Mitglied alle Kalender umbenennen oder (bis auf den letzten) löschen.

**Mitigierende Faktoren:**
- Letzter Kalender ist geschützt (`LAST_CALENDAR`)
- Kalender mit Events sind geschützt (`CALENDAR_NOT_EMPTY`)
- Der Haushalt-Admin kann das Mitglied entfernen

**Empfehlung (optional):** Kalender-Löschung auf Admin beschränken, Erstellung/Umbenennung für alle Mitglieder belassen.

---

### 🟢 L-2: Kein Maximalwert für `position`-Feld

**Datei:** [`calendars.py`](backend/app/routers/calendars.py:22)  
**Schweregrad:** Gering  
**Kategorie:** Input-Validierung

**Beobachtung:** `position: int = Field(default=0, ge=0)` hat keine Obergrenze. Ein Client könnte `position: 2147483647` oder höher senden. Bei SQL `INTEGER` (4 Byte, max 2.147.483.647) wäre dies am Limit.

**Empfehlung:** `le=9999` ergänzen:
```python
position: int = Field(default=0, ge=0, le=9999)
```

---

### 🟢 L-3: Client-seitige Socket-Handler ohne Household-Validierung

**Datei:** [`calendar.ts`](frontend/src/stores/calendar.ts:156-174)  
**Schweregrad:** Gering  
**Kategorie:** Defense in Depth

**Beobachtung:** Socket-Handler wie [`handleCalendarCreated`](frontend/src/stores/calendar.ts:156) prüfen nicht, ob `cal.household_id` mit dem aktuellen Haushalt übereinstimmt.

**Mitigierende Faktoren:**
- Server emittiert nur an den korrekten Room
- Room-Join erfordert Membership-Check

**Empfehlung (optional, Defense-in-Depth):**
```typescript
function handleCalendarCreated(cal: CalendarInfo) {
  const authStore = useAuthStore()
  if (cal.household_id !== authStore.currentHouseholdId) return  // Guard
  // ... rest
}
```

---

### ℹ️ I-1: `.env.example` mit Platzhalter-Secret

**Datei:** [`.env.example`](.env.example:2)  
**Kategorie:** Best Practice

`JWT_SECRET_KEY=please-change-this-secret-in-production-min-32-chars` ist korrekt als offensichtlicher Platzhalter gekennzeichnet. ✅ Kein Handlungsbedarf.

---

### ℹ️ I-2: CORS konfigurierbar, nicht wildcard

**Datei:** [`main.py`](backend/app/main.py:11)  
**Kategorie:** Best Practice

CORS-Origins werden aus `settings.cors_origins` geladen (komma-separiert). Kein `*` Wildcard im Default. ✅

---

## Prüfmatrix

| Prüfpunkt | Ergebnis |
|-----------|----------|
| User A kann Kalender von Haushalt B NICHT lesen | ✅ 403 via `verify_household_access` |
| User A kann Kalender in Haushalt B NICHT erstellen | ✅ 403 via `verify_household_access` |
| User A kann Kalender von Haushalt B NICHT ändern | ✅ 404 via `household_id`-Check |
| User A kann Kalender von Haushalt B NICHT löschen | ✅ 404 via `household_id`-Check |
| User A kann Event mit fremder calendar_id NICHT erstellen | ✅ 422 CALENDAR_MISMATCH |
| User A kann Event auf fremde calendar_id NICHT umziehen | ✅ 422 CALENDAR_MISMATCH |
| User A kann Poll mit fremder calendar_id NICHT entscheiden | ✅ 422 CALENDAR_MISMATCH |
| SQL-Injection in name/color/position | ✅ Pydantic + SQLAlchemy ORM |
| XSS via calendar.name im Frontend | ✅ Vue Mustache-Escaping |
| CSS-Injection via calendar.color | ✅ Regex + Vue Object-Style |
| Socket-Events an falschen Haushalt | ✅ Room-basierte Isolation |
| Hardcoded Secrets | ✅ Keine gefunden |
| Fehlermeldungen leaken Interna | ✅ Strukturierte ErrorCodes, keine Stack-Traces |

---

## Empfohlene Maßnahmen (priorisiert)

| # | Finding | Aufwand | Priorität |
|---|---------|---------|-----------|
| 1 | M-1: Downgrade-Fallback in Migration | 5 min | Vor nächstem Release |
| 2 | M-2: CALENDAR_MISMATCH-Tests ergänzen | 15 min | Vor nächstem Release |
| 3 | L-2: `position` max-Wert | 1 min | Nice-to-have |
| 4 | L-1: Admin-Gating für Löschung | 5 min | Optional (Designentscheidung) |
| 5 | L-3: Client-side Guard | 5 min | Optional (Defense-in-Depth) |
