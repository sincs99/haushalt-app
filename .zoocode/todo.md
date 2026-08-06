# Putzplan (Chores) — Implementierungsplan

**Epic:** Wiederkehrende Haushaltsaufgaben mit automatischer Ämtli-Rotation
**Stand:** 2026-08-06
**Tech Lead:** Orchestrator

---

## Aufgabe 0: Rest-Fixes aus Review

- [x] `useSocket.ts` → `hasConnectedBefore = false` in `disconnect()` (bereits erledigt)
- [x] `i18n.ts` → `detectLocale()`: Fallback `return 'de'` → `return 'en'`
- [x] `package.json` → Script `"check:locales"` + Build absichern
- [x] Commit: "fix: detectLocale fallback + build locale check"
- [x] `npx vue-tsc --noEmit` grün

## Aufgabe 1: Datenmodell + Migration

- [x] `models.py`: Household.timezone (String(50), server_default="Europe/Zurich")
- [x] `models.py`: Chore Model (id, household_id, title, description, recurrence Enum, weekday, day_of_month, rotation_order JSON, next_rotation_index, anchor_date, active, created_at, created_by_user_id)
- [x] `models.py`: ChoreAssignment Model (id, household_id, chore_id, assigned_user_id, due_date, completed_at, completed_by_user_id, created_at, UniqueConstraint, Index)
- [x] `models.py`: Relationships auf Household (chores, chore_assignments)
- [x] Alembic-Migration erzeugen (SQLite-kompatibel, Enum wie expense_split_type)
- [x] pytest in backend/ grün
- [x] Commit: "feat(models): add Chore + ChoreAssignment + Household.timezone"

## Aufgabe 2: Rotations- und Generierungslogik

- [x] `services/chore_scheduler.py`: today_in_tz(tz_name) → date
- [x] `services/chore_scheduler.py`: next_due_dates(chore, from_date, until_date) → list[date]
  - weekly: passender weekday
  - biweekly: Parität über Wochendifferenz zu anchor_date
  - monthly: day_of_month mit Clamping
- [x] `services/chore_scheduler.py`: materialize_due_assignments(db, household) → list[ChoreAssignment]
  - Lazy-Materialisierung, Savepoint + IntegrityError-Handling
  - Rotation: überspringe ausgeschiedene Mitglieder
- [x] pytest grün
- [x] Commit: "feat(services): chore_scheduler with lazy materialization"

## Aufgabe 3: REST-API

- [x] `core/error_codes.py`: CHORE_NOT_FOUND, CHORE_WEEKDAY_REQUIRED, CHORE_DAY_OF_MONTH_REQUIRED, CHORE_INVALID_ROTATION, CHORE_ASSIGNMENT_NOT_FOUND, CHORE_WINDOW_TOO_LARGE
- [x] `routers/chores.py`: Router mit Prefix /api/households/{household_id}/chores
  - GET / → Liste aller Chores
  - POST / (201) → Validierung + anchor_date
  - PATCH /{chore_id} → inkl. Recurrence-Änderung (zukünftige Assignments löschen)
  - DELETE /{chore_id} (204) → CASCADE
  - GET /assignments → materialize + Fenster-Validierung
  - POST /assignments/{id}/complete → idempotent
  - POST /assignments/{id}/uncomplete → idempotent
  - PATCH /assignments/{id} → reassign
- [x] `main.py`: Router mounten
- [x] Socket-Events: chore_created, chore_updated, chore_deleted, chore_assignment_created, chore_assignment_updated
- [x] conftest.py: Socket-Mock für chores-Router ergänzen
- [x] pytest grün
- [x] Commit: "feat(api): chores REST endpoints with socket events"

## Aufgabe 4: Backend-Tests

- [x] `tests/test_chores.py`: Scheduler-Unit-Tests + API-Tests
  - weekly/biweekly/monthly Termine
  - Rotation (3 User, 5 Termine)
  - Doppelte Materialisierung idempotent
  - Ausgeschiedenes Mitglied → übersprungen
  - POST-Validierungen (weekday, day_of_month, rotation_order)
  - complete/uncomplete idempotent
  - PATCH recurrence → zukünftige Assignments gelöscht, erledigte behalten
  - Socket-Events verifiziert
- [x] `tests/test_chore_scoping.py`: Cross-Household → 403
- [x] pytest grün (alle Tests)
- [x] Commit: "test: comprehensive chore tests + scoping"

## Aufgabe 5: Frontend

### 5a: Types + Repository + Store
- [x] `types/index.ts`: ChoreInfo, ChoreAssignmentInfo, Payloads
- [x] `repositories/choresRepository.ts`: Interface + Online-Factory
- [x] `stores/chores.ts`: State, Actions, Socket-Handler (idempotent)
- [x] Commit: "feat(frontend): chores types, repository, store"

### 5b: View + Route + Navigation
- [x] `views/ChoresView.vue`: "Diese Woche" + "Ämtli verwalten"
- [x] `router/index.ts`: /chores Route
- [x] `App.vue`: Socket-Bindings, Reconnect-Refetch, Household-Wechsel-Reset
- [x] Navigation (Top-Bar + Bottom-Tab-Bar): 🧹 Putzplan Tab
- [x] Commit: "feat(frontend): ChoresView + navigation + socket bindings"

### 5c: i18n
- [x] `locales/de.json`: Alle neuen Strings (chores.*)
- [x] `locales/en.json`: Alle neuen Strings (chores.*)
- [x] `npm run check:locales` grün
- [x] Commit: "feat(i18n): chores translations DE/EN"

### 5d: TypeScript-Check
- [x] `npx vue-tsc --noEmit` grün

## Aufgabe 6: Manuelle Akzeptanz

- [x] In Commit-Message dokumentieren: Chore erstellt, Abhaken live, Sprachwechsel

## Aufgabe 7: Alembic gegen Postgres

- [x] `alembic upgrade head` gegen Docker-Postgres
- [x] Enum + Timezone-Spalte verifiziert

## Aufgabe 8: PROJECT-STATUS.md

- [x] Chores-Modul dokumentiert
- [x] Test-Count aktualisiert
- [x] Offene Punkte ergänzt
- [x] Commit: "docs: update PROJECT-STATUS.md with chores module"
