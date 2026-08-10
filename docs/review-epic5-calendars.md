# 🧠 Business-Logic Review: Epic 5 – Mehrere Kalender (TimeTree-Style)

**Datum:** 2026-08-10  
**Reviewer:** Business Logic Reviewer  
**Status:** Review abgeschlossen – **1 Blocker, 3 Major, 3 Minor, 2 Empfehlungen**

---

## Fachliches Ziel

Ablösung der hartkodierten Event-Kategorien (`arbeit`, `katzen`, `haushalt`, etc.) durch frei definierbare Kalender pro Haushalt. Jeder Kalender hat Name, Hex-Farbe und Position. Events referenzieren statt einer `category`-Spalte nun eine `calendar_id`. Frontend bietet Filter-Chips, Kalender-Management und farbliche Zuordnung.

---

## Geprüfte Regeln

| Regel | Datei | Ergebnis |
|-------|-------|----------|
| `LAST_CALENDAR`: Letzter Kalender nicht löschbar | [`calendars.py`](backend/app/routers/calendars.py:178) | ✅ Korrekt |
| `CALENDAR_NOT_EMPTY`: Kalender mit Events blockiert | [`calendars.py`](backend/app/routers/calendars.py:190) | ✅ Korrekt |
| `CALENDAR_MISMATCH`: Cross-Household calendar_id verhindert | [`events.py`](backend/app/routers/events.py:132) | ✅ Korrekt |
| `CALENDAR_MISMATCH` bei Event-Update | [`events.py`](backend/app/routers/events.py:214) | ✅ Korrekt |
| `CALENDAR_MISMATCH` bei Poll-Decide | [`polls.py`](backend/app/routers/polls.py:346) | ✅ Korrekt |
| Hex-Farb-Validierung (Regex `#RRGGBB`) | [`calendars.py`](backend/app/routers/calendars.py:33) | ✅ Korrekt |
| Migration: NULL-Kategorie-Handling | [`migration`](backend/migrations/versions/p1q2r3s4t5u6_add_calendars_replace_category.py:103) | ⚠️ Fragil |
| Default-Kalender bei Haushalt-Erstellung | [`households.py`](backend/app/routers/households.py:401) | 🔴 FEHLT |
| Filter-Chips: mind. 1 aktiv | [`CalendarView.vue`](frontend/src/views/CalendarView.vue:71) | ✅ Korrekt |
| Optimistic Updates mit Rollback | [`calendar.ts`](frontend/src/stores/calendar.ts:78) | ✅ Korrekt |

---

## Erkannte Fehler

### 🔴 BUG-1 (BLOCKER): Kein Default-Kalender bei neuer Haushalt-Erstellung

**Ort:** [`create_household()`](backend/app/routers/households.py:401)

**Problem:** Wenn ein Benutzer einen **neuen Haushalt erstellt**, wird kein Default-Kalender angelegt. Die Datenmigration erstellt nur Kalender für **bestehende Haushalte** (mit oder ohne Events). Neue Haushalte nach der Migration starten mit **0 Kalendern**.

**Auswirkungen:**
- Event-Erstellung ist unmöglich (Backend erfordert `calendar_id`, Frontend hat `store.calendars[0]?.id` → `undefined`)
- Poll-Decide schlägt fehl (`decideCalendarId.value = store.calendars[0]?.id ?? ''` → leerer String → Backend-Validierung schlägt fehl)
- Die `LAST_CALENDAR`-Regel ist bedeutungslos, da der Zustand "0 Kalender" nie verhindert wird
- Frontend zeigt keine Filter-Chips (`v-if="store.calendars.length > 0"` → keine Chips)

**Empfohlener Fix:**
```python
# In create_household(), nach membership-Erstellung:
from app.models import Calendar
default_cal = Calendar(
    household_id=household.id,
    name="Allgemein",
    color="#5B8DEF",
    position=0,
)
db.add(default_cal)
```

**Testfall:**
```
GEGEBEN: Ein User erstellt einen neuen Haushalt
WENN: Der Haushalt erstellt wurde
DANN: Existiert genau 1 Kalender "Allgemein" mit Farbe "#5B8DEF"
UND: Der User kann sofort Events erstellen
```

---

### 🟠 BUG-2 (MAJOR): Stale Filter-IDs nach Kalender-Löschung via Socket

**Ort:** [`CalendarView.vue`](frontend/src/views/CalendarView.vue:52) + [`calendar.ts`](frontend/src/stores/calendar.ts:172)

**Problem:** Wenn ein anderes Haushaltsmitglied einen Kalender löscht, empfängt das Frontend das Socket-Event `calendar_deleted` und entfernt den Kalender aus `store.calendars`. Die `activeCalendarIds` in [`CalendarView.vue`](frontend/src/views/CalendarView.vue:52) enthalten aber weiterhin die gelöschte ID.

**Auswirkungen:**
- Events des gelöschten Kalenders werden gefiltert (`filteredEvents` matcht auf die gelöschte ID) – diese Events verschwinden still
- Der Filter-Chip für den gelöschten Kalender wird nicht mehr gerendert (da `store.calendars` die Daten nicht mehr hat), aber die ID bleibt in `activeCalendarIds`
- localStorage enthält veraltete IDs

**Empfohlener Fix:** Watcher auf `store.calendars`, der `activeCalendarIds` bereinigt:
```typescript
watch(
  () => store.calendars,
  (cals) => {
    const validIds = new Set(cals.map(c => c.id))
    const cleaned = activeCalendarIds.value.filter(id => validIds.has(id))
    if (cleaned.length === 0 && cals.length > 0) {
      cleaned.push(cals[0].id) // Mindestens 1 aktiv
    }
    activeCalendarIds.value = cleaned
    localStorage.setItem(STORAGE_KEY.value, JSON.stringify(cleaned))
  },
  { deep: true },
)
```

---

### 🟠 BUG-3 (MAJOR): Migration `capitalize()` vs `INITCAP()` – Potentielles Matching-Problem

**Ort:** [`migration`](backend/migrations/versions/p1q2r3s4t5u6_add_calendars_replace_category.py:84) (Zeile 84 + 96-101)

**Problem:** Kalender werden mit **Python `capitalize()`** erstellt (Zeile 84), aber der Backfill verwendet **PostgreSQL `INITCAP()`** (Zeile 100).

| Kategorie | `capitalize()` | `INITCAP()` | Match? |
|-----------|----------------|-------------|--------|
| `arbeit` | `Arbeit` | `Arbeit` | ✅ |
| `essen` | `Essen` | `Essen` | ✅ |
| `ARBEIT` (Edge Case) | `Arbeit` | `Arbeit` | ✅ |
| `multi word` (hypothetisch) | `Multi word` | `Multi Word` | ❌ |

**Bewertung:** Da die alten Kategorien per CheckConstraint auf 7 feste Lowercase-Werte beschränkt waren (`ck_event_category_valid`), sollten `capitalize()` und `INITCAP()` immer identisch sein. **Kein aktiver Bug**, aber der Code ist fragil bei möglichen Datenbank-Inkonsistenzen (z.B. manuell eingefügte Werte die den CheckConstraint umgehen).

**Risiko:** Niedrig – nur relevant bei korrupten Daten.

---

### 🟠 BUG-4 (MAJOR): Kalender-Löschung blockiert statt Events-Verschiebung – Schlechte UX

**Ort:** [`calendars.py`](backend/app/routers/calendars.py:190)

**Problem (fachlich):** Aktuell wird die Löschung eines Kalenders blockiert, wenn er noch Events enthält (`CALENDAR_NOT_EMPTY`). Der Benutzer muss **manuell jedes Event** in einen anderen Kalender verschieben, bevor er löschen kann.

**Business-Impact:**
- Bei einem Kalender mit 50+ Events ist das extrem umständlich
- Der User versteht möglicherweise nicht, warum die Löschung fehlschlägt (nur ein Toast-Error)
- Es gibt im Frontend **keine Anzeige**, wie viele Events betroffen sind

**Empfehlung:** Zwei Optionen anbieten:
1. **"Verschieben + Löschen"**: Dialog mit Dropdown "Events verschieben nach → [Kalender wählen]"
2. **"Alles löschen"**: Kalender inklusive aller Events löschen (mit Warnhinweis)

Minimaler Fix: Zumindest die Anzahl betroffener Events im Error-Response zurückgeben:
```python
detail=error_detail(
    ErrorCode.CALENDAR_NOT_EMPTY, 
    f"Calendar still has {event_count} events"
)
```

---

### 🟡 BUG-5 (MINOR): Decide-Dialog nutzt nicht den zuletzt verwendeten Kalender

**Ort:** [`CalendarView.vue`](frontend/src/views/CalendarView.vue:475)

**Problem:** Der [`openDecideDialog()`](frontend/src/views/CalendarView.vue:461) setzt `decideCalendarId` immer auf `store.calendars[0]?.id`, während [`openCreateDialog()`](frontend/src/views/CalendarView.vue:307) den zuletzt verwendeten Kalender aus `localStorage` liest:

```typescript
// Create-Dialog (gut):
formCalendarId.value = localStorage.getItem('last-calendar-' + authStore.currentHouseholdId) 
                       || store.calendars[0]?.id || ''

// Decide-Dialog (inkonsistent):
decideCalendarId.value = store.calendars[0]?.id ?? ''
```

**Fix:** Gleiche Logik wie im Create-Dialog verwenden.

---

### 🟡 BUG-6 (MINOR): Neuer Kalender wird nicht zuverlässig zum Filter hinzugefügt

**Ort:** [`CalendarView.vue`](frontend/src/views/CalendarView.vue:514)

**Problem:** Nach `handleAddCalendar()` wird `store.calendars[store.calendars.length - 1]` als neuer Kalender angenommen. Durch den Optimistic-Update-Flow (Temp-ID → Server-ID) und mögliche Socket-Race-Conditions ist der letzte Eintrag in `store.calendars` nicht notwendigerweise der gerade erstellte.

**Fix:** Die `addCalendar()`-Funktion sollte den erstellten Kalender zurückgeben:
```typescript
const created = await store.addCalendar({...})
if (created && !activeCalendarIds.value.includes(created.id)) {
  activeCalendarIds.value.push(created.id)
}
```

---

### 🟡 BUG-7 (MINOR): Kein UniqueConstraint auf Kalender-Name pro Haushalt

**Ort:** [`models.py`](backend/app/models.py:523)

**Problem:** Zwei Kalender im selben Haushalt können denselben Namen haben (z.B. zweimal "Arbeit"). Dies ist kein technischer Bug, aber verwirrend für Benutzer, besonders bei den Filter-Chips, wo dann zwei identische Chips erscheinen.

**Empfehlung:** Entweder UniqueConstraint `(household_id, name)` oder zumindest Frontend-Warnung bei Duplikat-Namen.

---

## Risiken (User/Business)

| Risiko | Schwere | Beschreibung |
|--------|---------|-------------|
| Neue Haushalte komplett blockiert | 🔴 HOCH | Ohne BUG-1-Fix kann kein neuer Haushalt Events/Polls nutzen |
| Datenverlust-Gefühl | 🟠 MITTEL | BUG-2: Events verschwinden still nach Kalender-Löschung |
| Usability-Hürde | 🟠 MITTEL | BUG-4: Kalender mit vielen Events ist nicht löschbar |
| Inkonsistente UX | 🟡 NIEDRIG | BUG-5: Decide-Dialog "vergisst" letzten Kalender |
| Model-Cascade vs. API-Check | 🟡 NIEDRIG | `ondelete='CASCADE'` auf FK vs. `CALENDAR_NOT_EMPTY`-Check |

---

## Positive Befunde ✅

1. **Cross-Household-Scoping ist wasserdicht:** Calendar-Mismatch wird bei Event-Create, Event-Update UND Poll-Decide geprüft. Tests decken alle drei Pfade ab.

2. **Optimistic Updates mit Rollback sind sauber implementiert:** Sowohl für Kalender als auch für Events gibt es korrekte Snapshot/Rollback-Logik.

3. **Socket-Handler sind idempotent:** Duplikat-Schutz bei Calendar-Created, Event-Created. Server gewinnt immer.

4. **Migration ist dreistufig und korrekt strukturiert:** Schema → Daten → Schema-Finalisierung. Downgrade-Pfad existiert.

5. **Error-Codes sind maschinenlesbar:** Frontend mappt `LAST_CALENDAR`, `CALENDAR_NOT_EMPTY`, `CALENDAR_MISMATCH` korrekt auf i18n-Strings.

6. **Haushaltswechsel wird behandelt:** `watch()` auf `authStore.currentHouseholdId` lädt Kalender neu und re-initialisiert Filter.

7. **Farbvalidierung ist robust:** Regex `^#[0-9A-Fa-f]{6}$` im Backend + nativer HTML-Color-Picker im Frontend.

---

## Empfohlene Verbesserungen

### E-1: Kalender-Limit pro Haushalt

Aktuell gibt es kein Maximum für Kalender pro Haushalt. Ein User könnte theoretisch hunderte erstellen. Empfehlung: Limit von z.B. 20 Kalendern mit Error-Code `CALENDAR_LIMIT_REACHED`.

### E-2: Position-Management

Kalender-Positionen werden nicht automatisch verwaltet. Beim Erstellen ist der Default `0`, was dazu führt, dass alle neuen Kalender die Position 0 haben. Die Sortierung fällt dann auf `created_at` zurück, was funktioniert, aber explizites Drag-and-Drop-Reordering wäre benutzerfreundlicher. Mindestens sollte die Default-Position automatisch `MAX(position) + 1` sein.

---

## Testfälle / Akzeptanzkriterien

### T-1: Neuer Haushalt hat Default-Kalender (für BUG-1)
```
GEGEBEN: Ein neuer User registriert sich und erstellt einen Haushalt
WENN: Der Haushalt erfolgreich erstellt wurde
DANN: GET /api/households/{id}/calendars/ liefert genau 1 Kalender
UND: Dieser Kalender heißt "Allgemein"
UND: Event-Erstellung mit dieser calendar_id funktioniert
```

### T-2: Kalender-Löschung via Socket bereinigt Frontend-Filter (für BUG-2)
```
GEGEBEN: User A und User B sind im selben Haushalt
UND: Es existieren Kalender "Arbeit" und "Privat"
UND: User A hat beide Kalender im Filter aktiv
WENN: User B löscht den leeren Kalender "Privat"
DANN: User A sieht nur noch den Filter-Chip "Arbeit"
UND: activeCalendarIds enthält nur noch die ID von "Arbeit"
UND: localStorage ist aktualisiert
```

### T-3: Kalender mit Events – Verschieben statt Blockieren (für BUG-4)
```
GEGEBEN: Kalender "Arbeit" hat 10 Events
UND: Es existiert mindestens ein weiterer Kalender "Privat"
WENN: User versucht "Arbeit" zu löschen
DANN: Dialog fragt "10 Events verschieben nach: [Dropdown] oder alles löschen?"
UND: Bei "Verschieben" werden Events nach "Privat" verschoben
UND: Kalender "Arbeit" wird gelöscht
```

### T-4: Cross-Household Calendar-Mismatch bei Poll-Decide
```
GEGEBEN: User ist in Haushalt A und Haushalt B
UND: Poll existiert in Haushalt A
WENN: User versucht Poll zu entscheiden mit calendar_id aus Haushalt B
DANN: 422 CALENDAR_MISMATCH
```

### T-5: Alle Kalender ausgefiltert ist unmöglich
```
GEGEBEN: Haushalt hat 2 Kalender, beide aktiv im Filter
WENN: User klickt auf den vorletzten aktiven Filter-Chip
DANN: Chip wird deaktiviert (1 bleibt aktiv)
WENN: User klickt auf den letzten aktiven Filter-Chip
DANN: Chip bleibt aktiv (keine Aktion, da min. 1 nötig)
```

---

## Zusammenfassung

| Kategorie | Anzahl |
|-----------|--------|
| 🔴 Blocker | 1 (BUG-1: Kein Default-Kalender) |
| 🟠 Major | 3 (BUG-2, BUG-3, BUG-4) |
| 🟡 Minor | 3 (BUG-5, BUG-6, BUG-7) |
| ✅ Positiv | 7 Punkte |
| 💡 Empfehlung | 2 (E-1, E-2) |

**Priorität:** BUG-1 muss **vor dem Release** behoben werden, da neue Haushalte sonst komplett dysfunktional sind. BUG-2 und BUG-4 sollten zeitnah folgen.
