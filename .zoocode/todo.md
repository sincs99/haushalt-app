# Epic: Notizen-Modul (Notes Module)

## Übersicht
Kompletter Slice für ein Notizen-Modul: Backend (Model, CRUD-API, Socket-Events, Tests) + Frontend (Vue-View mit Pinned-Sektion, Quick-Add, Edit-Dialog, Echtzeit-Sync).

---

## Phase 1: Backend

### 1.1 Model `Note` + Household-Relationship + Migration
**Datei:** `backend/app/models.py`
- Neues Model `Note` mit Feldern:
  - `id`: UUID PK (wie alle anderen Models)
  - `household_id`: UUID FK → households.id, NOT NULL, ondelete CASCADE
  - `title`: String(150), NOT NULL
  - `body`: Text, NOT NULL, default=""
  - `tag`: String(50), nullable
  - `pinned`: Boolean, default False
  - `created_by_user_id`: UUID FK → users.id, nullable (für gelöschte User)
  - `created_at`: DateTime(timezone=True), default utcnow
  - `updated_at`: DateTime(timezone=True), default utcnow, onupdate utcnow
- In `Household`-Klasse: `notes` Relationship hinzufügen (cascade="all, delete-orphan")

**Datei:** `backend/migrations/versions/l6m7n8o9p0q1_add_notes_module.py`
- Alembic-Migration für `notes`-Tabelle
- Index auf `household_id`

### 1.2 Router `notes.py` (CRUD + Socket-Events)
**Datei:** `backend/app/routers/notes.py`
- Pattern: Exakt wie `todos.py` — Pydantic-Schemas inline, verify_household_access
- Schemas:
  - `NoteCreate`: title (1-150), body (optional, max 5000), tag (optional, max 50), pinned (optional, default false)
  - `NoteUpdate`: alle Felder optional (partial update)
  - `NoteResponse`: alle Felder, model_config from_attributes
- Endpoints:
  - `GET /api/households/{household_id}/notes/` → Liste, sortiert: pinned DESC, created_at DESC
  - `POST /api/households/{household_id}/notes/` → Erstellen, emit `note_created`
  - `PATCH /api/households/{household_id}/notes/{note_id}` → Update, emit `note_updated`
  - `DELETE /api/households/{household_id}/notes/{note_id}` → Löschen, emit `note_deleted`

**Datei:** `backend/app/main.py`
- Import `notes` Router
- `app.include_router(notes.router)` hinzufügen

### 1.3 Test-Fixtures + Scoping-Tests
**Datei:** `backend/tests/conftest.py`
- Import `Note` in Model-Import-Zeile
- Socket-Mock: `app.routers.notes.emit_to_household_sync` patchen
- Fixtures: `note_a(db, household_a, user_a)` und `note_b(db, household_b, user_b)`

**Datei:** `backend/tests/test_note_scoping.py`
- Pattern: Exakt wie `test_todo_scoping.py`
- Tests:
  1. `test_user_a_can_read_own_notes` (GET → 200, eigene Note enthalten)
  2. `test_user_a_cannot_read_other_household_notes` (GET → 403)
  3. `test_user_a_cannot_create_in_other_household` (POST → 403)
  4. `test_user_a_cannot_patch_other_household_note` (PATCH → 403)
  5. `test_user_a_cannot_delete_other_household_note` (DELETE → 403)

---

## Phase 2: Frontend

### 2.1 TypeScript-Typen
**Datei:** `frontend/src/types/index.ts`
```ts
export interface NoteItem {
  id: string
  household_id: string
  title: string
  body: string
  tag: string | null
  pinned: boolean
  created_by_user_id: string | null
  created_at: string
  updated_at: string
}
```

### 2.2 Repository
**Datei:** `frontend/src/repositories/notesRepository.ts`
- Pattern: Exakt wie `todosRepository.ts`
- Methoden: `fetchAll`, `create`, `update`, `remove`

### 2.3 Store
**Datei:** `frontend/src/stores/notes.ts`
- Pattern: Wie `todos.ts` mit optimistic UI + Socket-Handlern
- State: `items: NoteItem[]`, `loading: boolean`
- Actions: `fetchNotes`, `addNote`, `updateNote`, `deleteNote`, `togglePin`
- Socket-Handler: `handleNoteCreated`, `handleNoteUpdated`, `handleNoteDeleted`
- Computed-Helper: `pinnedNotes`, `unpinnedNotes`

### 2.4 View `NotesView.vue`
**Datei:** `frontend/src/views/NotesView.vue`
- Layout:
  1. PageHeader "Notizen"
  2. Schnellnotiz-Feld: Input "Notiz schreiben…" → Titel = erste Zeile
  3. Sektion "Angepinnt" (nur wenn pinned Notes vorhanden):
     - Karten mit `background: var(--acc-soft)` Tönung
     - Titel, Body-Preview (erste Zeile), Tag-Chip, Pin-Icon
  4. Sektion "Alle Notizen":
     - Karten: Titel, erste Textzeile, Meta (Autor-Avatar · Datum), Tag-Chip
  5. Edit-Dialog (BaseDialog):
     - Title-Input, Body-Textarea, Tag-Input, Pin-Toggle
     - Speichern/Löschen-Buttons
- Socket-Events: on mount `note_created`/`note_updated`/`note_deleted` registrieren

### 2.5 Router + MoreSheet + i18n
**Datei:** `frontend/src/router/index.ts`
- Route `/notes` → `NotesView.vue`, meta: requiresAuth

**Datei:** `frontend/src/components/MoreSheet.vue`
- Notes-Eintrag: `disabled: false`, `action: () => navigate('/notes')`

**Datei:** `frontend/src/locales/de.json` + `en.json`
- Neuer Abschnitt `notes`:
  - title, addPlaceholder, emptyTitle, emptySubtitle, pinnedSection, allSection,
    editTitle, titleLabel, bodyLabel, tagLabel, tagPlaceholder, pinLabel,
    deleteConfirm, addError, saveError, deleteError
- `moreSheet.notesSub` aktualisieren (nicht mehr "Bald verfügbar")

---

## ⚡ API-Schema Update (Backend fertig – 2026-08-08)

> **Für Frontend-Entwickler:** Die Notes-API ist vollständig implementiert und getestet.

### Neue Endpoints:
| Methode | Pfad | Beschreibung |
|---------|------|-------------|
| `GET` | `/api/households/{household_id}/notes/` | Liste aller Notizen (sortiert: pinned DESC, created_at DESC) |
| `POST` | `/api/households/{household_id}/notes/` | Neue Notiz erstellen (201) |
| `PATCH` | `/api/households/{household_id}/notes/{note_id}` | Notiz teilweise aktualisieren |
| `DELETE` | `/api/households/{household_id}/notes/{note_id}` | Notiz löschen (204) |

### Request-Body `POST` (`NoteCreate`):
```json
{ "title": "string (1-150, required)", "body": "string (max 5000, default '')", "tag": "string|null (max 50)", "pinned": "bool (default false)" }
```

### Request-Body `PATCH` (`NoteUpdate`):
Alle Felder optional (partial update), gleiche Validierung.

### Response (`NoteResponse`):
```json
{ "id": "uuid", "household_id": "uuid", "title": "string", "body": "string", "tag": "string|null", "pinned": "bool", "created_by_user_id": "uuid|null", "created_at": "datetime", "updated_at": "datetime" }
```

### Socket-Events:
- `note_created` → vollständiges NoteResponse-Objekt
- `note_updated` → vollständiges NoteResponse-Objekt
- `note_deleted` → `{"id": "uuid-string"}`

---

## Phase 3: Review & Abnahme
- [x] `pytest` grün (insbes. test_note_scoping.py)
- [ ] Frontend TypeScript-Check grün
- [ ] Pin/Unpin synct in Echtzeit über Socket
- [x] Business-Logic-Review: Scoping, Validierung, Edge-Cases

---

## API-Änderungen für Frontend (2026-08-08)

> **Betrifft:** Notes-Modul — 4 Bugfixes aus Business-Logic-Review

1. **404-Responses enthalten jetzt strukturierte Error-Codes:**
   `detail` ist nun `{"code": "NOTE_NOT_FOUND", "message": "..."}` statt ein einfacher String.
   → Frontend sollte `errors.NOTE_NOT_FOUND` in i18n-Dateien (`de.json`, `en.json`) ergänzen.

2. **Tag-Feld: Leere Strings werden serverseitig zu `null` normalisiert.**
   Ein `tag: ""` oder `tag: "  "` wird vom Backend automatisch zu `null`.
   → Kein Frontend-Handlungsbedarf, aber gut zu wissen für Validierungslogik.

3. **`NoteUpdate.tag` hat jetzt `max_length=50`** (war vorher unbeschränkt).
   → Frontend sollte ein `maxlength=50` auf Tag-Inputs setzen.
