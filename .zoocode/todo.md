# Epic 5: Mehrere Kalender (TimeTree-Style)

## Ziel
Frei definierbare Kalender pro Haushalt (z.B. Katzen / Arbeit / Privat) mit Farbe, statt der hartcodierten `category`-Liste. Filter-Chips in der Kalenderansicht.

---

## 5.1 Backend

> **⚠️ API-ÄNDERUNG FÜR FRONTEND (2026-08-10):**
> - **Events:** Feld `category: str` wurde durch `calendar_id: uuid` ersetzt (Create, Update, Response, Dashboard)
> - **Polls DecideRequest:** Feld `event_category: str` wurde durch `calendar_id: uuid` ersetzt
> - **Dashboard:** `DashboardEventItem.category` → `DashboardEventItem.calendar_id`
> - **Neuer Endpoint:** `GET/POST/PATCH/DELETE /api/households/{id}/calendars/` (CRUD für Kalender)
> - Schemas: `CalendarCreate(name, color, position)`, `CalendarUpdate(name?, color?, position?)`, `CalendarResponse(id, household_id, name, color, position, created_at)`
> - **BUGFIX (2026-08-10):** `POST /api/households/` erstellt jetzt automatisch einen Default-Kalender "Allgemein" (color `#5B8DEF`, position 0). Frontend kann beim Haushalt-Erstellen davon ausgehen, dass mindestens 1 Kalender existiert.

### 5.1.1 Calendar Model + Event Model Update ✅
**Modus:** `flask-backend`
**Dateien:** `backend/app/models.py`

- [x] Neues Model `Calendar`:
  ```python
  class Calendar(Base):
      __tablename__ = "calendars"
      __table_args__ = (
          Index("ix_calendars_household", "household_id"),
      )
      id: UUID PK, default uuid4
      household_id: UUID FK → households.id, NOT NULL, ondelete CASCADE
      name: String(50), NOT NULL
      color: String(7), NOT NULL  # Hex z.B. "#8A9B6E"
      position: Integer, NOT NULL, default 0
      created_at: DateTime(tz), default utcnow
  ```
- [x] Relationship in `Household`: `calendars: list["Calendar"]` mit cascade
- [x] `Calendar` relationship: `household` back_populates, `events` back_populates
- [x] `Event` Model ändern:
  - Neues Feld: `calendar_id: UUID FK → calendars.id, NOT NULL, ondelete CASCADE`
  - Relationship: `calendar: Mapped["Calendar"]`
  - `CheckConstraint("ck_event_category_valid")` → ENTFERNT
  - Spalte `category` → ENTFERNT aus Model
- [x] Import von `Calendar` in `conftest.py` hinzufügen

### 5.1.2 Alembic Migration (dreistufig, eine Revision) ✅
**Modus:** `flask-backend` (da es um Python-Code geht, nicht um Azure SQL Infrastruktur)
**Datei:** `backend/migrations/versions/p1q2r3s4t5u6_add_calendars_replace_category.py`

Dreistufige Migration in EINER Revision:
1. **Schema up (Phase 1):**
   - `calendars`-Tabelle anlegen
   - `events.calendar_id` als NULLABLE UUID FK hinzufügen
2. **Datenmigration (Phase 2):**
   - Pro Haushalt: für jede in dessen Events vorkommende `category` einen Kalender anlegen
   - Name = category kapitalisiert (z.B. "arbeit" → "Arbeit")
   - Farben aus 7er-Palette rotierend:
     ```python
     PALETTE = ["#5B8DEF", "#F4A261", "#6E9273", "#9C6E79", "#E76F51", "#C09A62", "#8B8B8B"]
     ```
   - `calendar_id` in Events backfüllen basierend auf category + household
   - Haushalte ohne Events: Default-Kalender "Allgemein" mit Farbe `#5B8DEF`
3. **Schema up (Phase 3):**
   - `calendar_id` auf NOT NULL setzen
   - `CheckConstraint ck_event_category_valid` droppen
   - Spalte `category` droppen

**downgrade():**
- Spalte `category` String(50) wieder hinzufügen
- `category` aus Kalendername backfüllen (lowercase, best effort)
- `ck_event_category_valid` CheckConstraint wieder anlegen
- `events.calendar_id` droppen
- `calendars`-Tabelle droppen

### 5.1.3 Neuer calendars.py Router + Error Codes
**Modus:** `flask-backend`
**Dateien:** `backend/app/routers/calendars.py`, `backend/app/core/error_codes.py`

Neue Error Codes in `error_codes.py`:
```python
CALENDAR_NOT_FOUND = "CALENDAR_NOT_FOUND"
LAST_CALENDAR = "LAST_CALENDAR"
CALENDAR_NOT_EMPTY = "CALENDAR_NOT_EMPTY"
CALENDAR_MISMATCH = "CALENDAR_MISMATCH"
```

Router `calendars.py`:
- Prefix: `/api/households/{household_id}/calendars`
- Tags: `["calendars"]`

Endpoints:
- `GET /` → Liste aller Kalender des Haushalts, sortiert nach `position`
- `POST /` → Kalender erstellen (Pflicht: name, color; Optional: position)
  - Socket: `calendar_created`
- `PATCH /{calendar_id}` → Kalender umbenennen/Farbe/Position ändern
  - Socket: `calendar_updated`
- `DELETE /{calendar_id}` → Kalender löschen
  - **Validierung 1:** Wenn nur 1 Kalender existiert → `422 LAST_CALENDAR`
  - **Validierung 2:** Wenn Events im Kalender existieren → `422 CALENDAR_NOT_EMPTY`
  - Socket: `calendar_deleted`

Schemas:
```python
class CalendarCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str = Field(..., min_length=7, max_length=7, pattern=r'^#[0-9A-Fa-f]{6}$')
    position: int = 0

class CalendarUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=50)
    color: str | None = Field(None, min_length=7, max_length=7, pattern=r'^#[0-9A-Fa-f]{6}$')
    position: int | None = None

class CalendarResponse(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    color: str
    position: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
```

### 5.1.4 events.py Router anpassen
**Modus:** `flask-backend`
**Datei:** `backend/app/routers/events.py`

- [ ] `ALLOWED_CATEGORIES` dict → ENTFERNEN
- [ ] `EventCreate`: `category` Feld → ersetzen durch `calendar_id: uuid.UUID`
  - `validate_category` Validator → ENTFERNEN
  - Neuer Validator: Kalender gehört zum Haushalt (im Endpoint, nicht im Schema)
- [ ] `EventUpdate`: `category` → `calendar_id: uuid.UUID | None = None`
  - Validator entfernen
- [ ] `EventResponse`: `category: str` → `calendar_id: uuid.UUID`
- [ ] `create_event`: Validierung calendar_id → Kalender laden, prüfen ob `calendar.household_id == household_id`, sonst `422 CALENDAR_MISMATCH`
- [ ] `update_event`: Analog calendar_id Validierung wenn gesendet
- [ ] Import `Calendar` Model hinzufügen

### 5.1.5 main.py + conftest.py Updates
**Modus:** `flask-backend`

`backend/app/main.py`:
- [ ] Import: `from app.routers import ... calendars`
- [ ] `app.include_router(calendars.router)` hinzufügen

`backend/tests/conftest.py`:
- [ ] Import `Calendar` in Zeile 41
- [ ] Mock für `app.routers.calendars.emit_to_household_sync` in `_mock_socket_emit`
- [ ] Fixture `calendar_a` (für household_a, Name="Allgemein", Farbe="#5B8DEF")
- [ ] Fixture `calendar_b` (für household_b, Name="Allgemein", Farbe="#5B8DEF")
- [ ] Fixture `event_a` anpassen: `category` → `calendar_id=calendar_a.id`
- [ ] Fixture `event_b` anpassen: `category` → `calendar_id=calendar_b.id`

### 5.1.6 Tests
**Modus:** `flask-backend`

`backend/tests/test_calendar_scoping.py`:
- [ ] Positiv: User A kann eigene Kalender lesen
- [ ] Negativ: User A kann Kalender von Household B nicht lesen (403)
- [ ] Positiv: User A kann Kalender erstellen
- [ ] Negativ: User A kann Kalender in Household B nicht erstellen (403)
- [ ] Positiv: User A kann Kalender umbenennen
- [ ] Negativ: Letzten Kalender löschen → 422 LAST_CALENDAR
- [ ] Negativ: Kalender mit Events löschen → 422 CALENDAR_NOT_EMPTY
- [ ] Positiv: Leeren Kalender löschen (wenn >1 existiert)

`backend/tests/test_event_scoping.py`:
- [ ] `test_user_a_cannot_create_in_other_household` → `calendar_id` statt `category`
- [ ] Neuer Test: Event mit calendar_id aus anderem Haushalt → 422 CALENDAR_MISMATCH

### 5.1.7 Tests grün prüfen
**Modus:** `debug-troubleshooter`
- [ ] `pytest backend/tests/` ausführen und alle Fehler beheben

---

## 5.2 Frontend

### 5.2.1 Types + Repository + Store
**Modus:** `vue-frontend`

`frontend/src/types/index.ts`:
- [ ] `EventCategory` Type → ENTFERNEN
- [ ] Neuer Type:
  ```typescript
  export interface CalendarInfo {
    id: string
    household_id: string
    name: string
    color: string      // Hex "#RRGGBB"
    position: number
    created_at: string
  }
  export interface CalendarCreatePayload {
    name: string
    color: string
    position?: number
  }
  export interface CalendarUpdatePayload {
    name?: string
    color?: string
    position?: number
  }
  ```
- [ ] `CalendarEvent`: `category: EventCategory` → `calendar_id: string`
- [ ] `CalendarEventCreatePayload`: `category?` → `calendar_id: string` (Pflichtfeld!)
- [ ] `CalendarEventUpdatePayload` analog
- [ ] `DashboardEventItem`: `category: string` → `calendar_id: string` (falls Dashboard betroffen)

`frontend/src/repositories/calendarRepository.ts`:
- [ ] Neue Methoden für Calendar-CRUD hinzufügen:
  ```typescript
  fetchCalendars(householdId: string): Promise<CalendarInfo[]>
  createCalendar(householdId: string, data: CalendarCreatePayload): Promise<CalendarInfo>
  updateCalendar(householdId: string, calendarId: string, data: CalendarUpdatePayload): Promise<CalendarInfo>
  deleteCalendar(householdId: string, calendarId: string): Promise<void>
  ```

`frontend/src/stores/calendar.ts`:
- [ ] State: `calendars: ref<CalendarInfo[]>([])`
- [ ] Actions: `fetchCalendars()`, `addCalendar()`, `updateCalendar()`, `deleteCalendar()`
- [ ] Socket-Handler: `handleCalendarCreated`, `handleCalendarUpdated`, `handleCalendarDeleted`
- [ ] Helper: `getCalendarColor(calendarId)` → string
- [ ] Optimistic Updates wie bei Events

### 5.2.2 CalendarView.vue – Filter + Farben + Formular
**Modus:** `vue-frontend`
**Datei:** `frontend/src/views/CalendarView.vue`

- [ ] Filter-Chips oben (nach PillTabs):
  - Alle Kalender als Multi-Select Chips
  - Chip-Hintergrund = Kalenderfarbe (mit weißem Text)
  - Auswahl in `localStorage` persistieren (Key: `calendar-filter-{householdId}`)
  - Events filtern basierend auf aktiven Kalender-Chips
- [ ] Event-Karte: Farbbalken (`event-card__bar`) → Kalenderfarbe statt categoryColor
- [ ] Category-Dots im Week-Strip → Kalenderfarben
- [ ] Formular: `category`-Chips → Kalender-Auswahl (Pflichtfeld)
  - Default = zuletzt genutzter Kalender (localStorage)
- [ ] `getCategoryLabel()` → ersetzt durch Kalendername
- [ ] `categoryDotsForDay()` → Kalenderfarben nutzen
- [ ] Decide-Dialog: `event_category` → `calendar_id`
- [ ] Socket-Listener für `calendar_*` Events registrieren
- [ ] `onMounted`: `store.fetchCalendars()` aufrufen

### 5.2.3 Verwaltungs-Dialog „Kalender verwalten"
**Modus:** `vue-frontend`
**Datei:** `frontend/src/views/CalendarView.vue` (oder eigene Komponente)

- [ ] Icon-Button im PageHeader (z.B. PhGear oder PhListDashes)
- [ ] Dialog öffnen mit Liste aller Kalender
- [ ] Pro Kalender:
  - Name (editierbar)
  - Farbe (Color-Picker oder Palette)
  - Löschen-Button (mit LAST_CALENDAR / CALENDAR_NOT_EMPTY Fehlerhandling)
- [ ] „Neuen Kalender hinzufügen" Button
- [ ] Drag & Drop für Reihenfolge (optional, v1 erstmal ohne)

### 5.2.4 Locales Migration
**Modus:** `vue-frontend`
**Dateien:** `frontend/src/locales/de.json`, `frontend/src/locales/en.json`

- [ ] Alte Keys entfernen: `calendar.category.*` (falls vorhanden)
- [ ] Neue Keys hinzufügen:
  ```json
  "calendars": {
    "manage": "Kalender verwalten",
    "add": "Neuer Kalender",
    "name": "Name",
    "color": "Farbe",
    "delete": "Kalender löschen",
    "deleteConfirm": "Diesen Kalender wirklich löschen?",
    "lastCalendar": "Der letzte Kalender kann nicht gelöscht werden.",
    "notEmpty": "Der Kalender enthält noch Events. Verschiebe oder lösche diese zuerst.",
    "created": "Kalender erstellt",
    "updated": "Kalender aktualisiert",
    "deleted": "Kalender gelöscht",
    "selectCalendar": "Kalender auswählen",
    "allCalendars": "Alle",
    "default": "Allgemein"
  }
  ```
- [ ] `calendar.categoryLabel` → `calendar.calendarLabel` (im Formular)
- [ ] `npm run check:locales` muss grün sein

### 5.2.5 categoryColors.ts Refactoring
**Modus:** `vue-frontend`
**Datei:** `frontend/src/utils/categoryColors.ts`

- [ ] Datei entfernen oder zu `calendarDefaults.ts` umbauen
- [ ] Default-Palette exportieren (für Kalender-Erstellungsvorschläge):
  ```typescript
  export const DEFAULT_CALENDAR_PALETTE = [
    '#5B8DEF', '#F4A261', '#6E9273', '#9C6E79',
    '#E76F51', '#C09A62', '#8B8B8B',
  ]
  ```
- [ ] Alle Imports von `categoryColors` in CalendarView ersetzen

---

## Reviews (nach Abschluss aller Implementierungen)

### Business-Logic Review
**Modus:** `business-logic-reviewer`
- Prüfung der Kalender-Löschlogik (LAST_CALENDAR, CALENDAR_NOT_EMPTY)
- Prüfung der Datenmigration (category → calendar mapping)
- Prüfung der calendar_id Validierung in Events

### Security Review
**Modus:** `security-review`
- Scoping: Kalender nur im eigenen Haushalt CRUD-bar
- CALENDAR_MISMATCH: Cross-Household calendar_id in Events verhindern
- Migration: Keine Datenleaks bei Downgrade

---

## Abhängigkeiten (Reihenfolge)
1. **5.1.1** → 5.1.2 → 5.1.3 → 5.1.4 → 5.1.5 → 5.1.6 → 5.1.7
2. **5.2.1** (kann parallel zu 5.1.5 starten) → 5.2.2 → 5.2.3 → 5.2.4 → 5.2.5
3. Reviews erst nach 5.1.7 + 5.2.5
