# Haushalt-App — Aktueller Projektstand

**Stand:** 2026-08-06 (aktualisiert)
**Autor:** Tech Lead (automatisch generiert)

---

## 1. Projektübersicht

Eine Haushalt-App für gemeinsame Einkaufslisten, Todos, wiederkehrende Putzpläne mit Ämtli-Rotation und Ausgaben-Teilung mit Ausgleichszahlungen innerhalb eines Haushalts. Multi-User, Echtzeit-Sync via WebSocket, Mobile-First UI, zweisprachig (DE/EN).

| Aspekt | Technologie |
|---|---|
| Backend | Python 3.12+, FastAPI 0.141, SQLAlchemy, Alembic |
| Datenbank | PostgreSQL (via psycopg2) |
| Realtime | Socket.IO (python-socketio) |
| Frontend | Vue 3.5, TypeScript 7, Vite 8, Pinia 4 |
| Auth | JWT (Bearer Token), bcrypt-Hashing |
| i18n | vue-i18n, 205 Keys (DE + EN), Build-gesicherter Key-Sync |
| UI | Custom Design-System (CSS Custom Properties), Mobile-First |

---

## 2. Architektur

```
┌─────────────────────────────────────────────────────┐
│                    Vue 3 Frontend                     │
│                                                       │
│  Views → Components → Pinia Stores → Repositories     │
│                           ↕                ↓           │
│                     Socket.IO        Axios (REST)      │
└──────────────────────┬────────────────────────────────┘
                       │
                HTTPS / WSS
                       │
┌──────────────────────▼────────────────────────────────┐
│                  FastAPI Backend                        │
│                                                        │
│  Routers (auth, shopping, todos, households,            │
│           expenses, settlements, chores)                │
│      ↓              ↓                                  │
│  SQLAlchemy    Socket.IO Server                        │
│      ↓                                                 │
│  PostgreSQL                                            │
└────────────────────────────────────────────────────────┘
```

---

## 3. Datei-Übersicht

### Backend (`backend/`)

| Datei | Zweck | Status |
|---|---|---|
| [`app/main.py`](../backend/app/main.py) | FastAPI-App, CORS, Router-Mount (auth, shopping, todos, households, expenses, settlements, chores), Socket.IO-Mount | ✅ Fertig |
| [`app/models.py`](../backend/app/models.py) | SQLAlchemy Models: Household (+timezone), User, HouseholdMember, ShoppingItem, Todo, Expense, ExpenseShare, Chore, ChoreAssignment | ✅ Fertig |
| [`app/database.py`](../backend/app/database.py) | DB-Session, Engine, Base | ✅ Fertig |
| [`app/socket_manager.py`](../backend/app/socket_manager.py) | Socket.IO Server, Auth, Room-Join, emit_to_household_sync | ✅ Fertig |
| [`app/core/config.py`](../backend/app/core/config.py) | Pydantic Settings (DB-URL, JWT-Secret, CORS) | ✅ Fertig |
| [`app/core/security.py`](../backend/app/core/security.py) | JWT-Erstellung, Passwort-Hashing/-Verify, Invite-Code-Generierung | ✅ Fertig |
| [`app/core/deps.py`](../backend/app/core/deps.py) | Dependencies: get_current_user, verify_household_access | ✅ Fertig |
| [`app/core/error_codes.py`](../backend/app/core/error_codes.py) | Maschinenlesbare Error-Codes (+ 6 Chore-Codes: CHORE_NOT_FOUND, CHORE_WEEKDAY_REQUIRED, CHORE_DAY_OF_MONTH_REQUIRED, CHORE_INVALID_ROTATION, CHORE_ASSIGNMENT_NOT_FOUND, CHORE_WINDOW_TOO_LARGE) | ✅ Fertig |
| [`app/routers/auth.py`](../backend/app/routers/auth.py) | POST /register, POST /login, GET /me | ✅ Fertig |
| [`app/routers/shopping.py`](../backend/app/routers/shopping.py) | CRUD Shopping-Items + Socket-Events | ✅ Fertig |
| [`app/routers/todos.py`](../backend/app/routers/todos.py) | CRUD Todos + Socket-Events | ✅ Fertig |
| [`app/routers/households.py`](../backend/app/routers/households.py) | GET /members, GET /invite-code, POST /join | ✅ Fertig |
| [`app/routers/expenses.py`](../backend/app/routers/expenses.py) | CRUD Expenses + Split-Logik (even/custom), Pydantic-Schemas inline | ✅ Fertig |
| [`app/routers/settlements.py`](../backend/app/routers/settlements.py) | CRUD Settlements (GET/POST/DELETE) + Socket-Events | ✅ Fertig |
| [`app/routers/chores.py`](../backend/app/routers/chores.py) | CRUD Chores + 4 Assignment-Endpoints + Socket-Events | ✅ Fertig |
| [`app/services/chore_scheduler.py`](../backend/app/services/chore_scheduler.py) | Lazy-Materialisierung, Kalender-basierte Rotation, Datumsberechnung (weekly/biweekly/monthly) | ✅ Fertig |
| `migrations/` | Alembic-Migrationen (8 Versionen) | ✅ Fertig |
| [`scripts/regenerate_invite_codes.py`](../backend/scripts/regenerate_invite_codes.py) | Dry-Run/Apply Script für Invite-Code-Migration | ✅ Fertig |

### Backend-Tests (`backend/tests/`)

| Datei | Abdeckung | Status |
|---|---|---|
| [`conftest.py`](../backend/tests/conftest.py) | SQLite in-memory DB (StaticPool), Multi-Tenant Fixtures (2 Households, 3 User), Socket-Mock | ✅ Fertig |
| [`test_auth_guard.py`](../backend/tests/test_auth_guard.py) | Kein Token → 401, Ungültiger Token → 401, Abgelaufener Token → 401 | ✅ Fertig |
| [`test_shopping_scoping.py`](../backend/tests/test_shopping_scoping.py) | Multi-Tenant Shopping: Eigene Items lesen ✅, Cross-Household GET/POST/PATCH/DELETE → 403 | ✅ Fertig |
| [`test_todo_scoping.py`](../backend/tests/test_todo_scoping.py) | Multi-Tenant Todos: Eigene Todos lesen ✅, Cross-Household GET/POST/PATCH/DELETE → 403 | ✅ Fertig |
| [`test_household_join.py`](../backend/tests/test_household_join.py) | Join mit gültigem Code → 200, Ungültiger Code → 404, Bereits Mitglied → 409, Case-insensitiv | ✅ Fertig |
| [`test_expense_scoping.py`](../backend/tests/test_expense_scoping.py) | Multi-Tenant Expenses: Eigene lesen ✅, Cross-Household GET/POST/PATCH/DELETE/Balances → 403 | ✅ Fertig |
| [`test_expense_splits.py`](../backend/tests/test_expense_splits.py) | split_evenly Unit-Tests, Even/Custom-Split API, Validierung (422), PATCH Reshare, DELETE | ✅ Fertig |
| [`test_expense_balances.py`](../backend/tests/test_expense_balances.py) | compute_settlements Unit-Tests (7), Balances-Endpoint Integration (3+1 Scoping) | ✅ Fertig |
| [`test_expense_events.py`](../backend/tests/test_expense_events.py) | Socket.IO Events: create/update/delete emittiert, failed=kein Event, Room-Check | ✅ Fertig |
| [`test_settlements.py`](../backend/tests/test_settlements.py) | CRUD, Scoping, Validierung, Balance-Integration, Socket-Events (23 Tests) | ✅ Fertig |
| [`test_chores.py`](../backend/tests/test_chores.py) | Scheduler-Unit-Tests, API-Tests, Socket-Events (28 Tests) | ✅ Fertig |
| [`test_chore_scoping.py`](../backend/tests/test_chore_scoping.py) | Cross-Household 403 auf alle 8 Endpoints (8 Tests) | ✅ Fertig |

### Frontend (`frontend/src/`)

| Datei | Zweck | Status |
|---|---|---|
| [`App.vue`](../frontend/src/App.vue) | App-Shell: Desktop Top-Bar, Mobile Bottom-Tab-Bar (5 Module: 🛒 🧹 ✅ 💰 🏠), Socket-Binding, Offline-Banner, Toasts | ✅ Fertig |
| [`main.ts`](../frontend/src/main.ts) | App-Bootstrap, Pinia, Router, i18n, Theme-CSS Import | ✅ Fertig |
| [`i18n.ts`](../frontend/src/i18n.ts) | vue-i18n Setup, detectLocale (localStorage → navigator.language → en) | ✅ Fertig |
| [`api/client.ts`](../frontend/src/api/client.ts) | Axios-Client mit JWT-Interceptor, 401-Handler | ✅ Fertig |
| [`types/index.ts`](../frontend/src/types/index.ts) | ShoppingItem, TodoItem, UserInfo, HouseholdInfo, HouseholdMemberInfo, MeResponse, ChoreInfo, ChoreAssignmentInfo, SettlementInfo | ✅ Fertig |
| **i18n** | | |
| [`locales/de.json`](../frontend/src/locales/de.json) | Deutsche Übersetzungen (205 Keys) | ✅ Fertig |
| [`locales/en.json`](../frontend/src/locales/en.json) | Englische Übersetzungen (205 Keys) | ✅ Fertig |
| [`scripts/check-locales.js`](../frontend/scripts/check-locales.js) | Build-Script: Prüft Key-Sync zwischen DE und EN | ✅ Fertig |
| **Design-System** | | |
| [`assets/theme.css`](../frontend/src/assets/theme.css) | Design-Token-System: Farben, Typografie, Spacing, Radii, Schatten, Transitions, Global Reset | ✅ Fertig |
| [`components/ui/BaseButton.vue`](../frontend/src/components/ui/BaseButton.vue) | Button: 4 Varianten (primary/secondary/danger/ghost), 2 Grössen, Loading-State | ✅ Fertig |
| [`components/ui/BaseInput.vue`](../frontend/src/components/ui/BaseInput.vue) | Input: Label, Error-State, v-model, iOS-Zoom-Prevention (16px) | ✅ Fertig |
| [`components/ui/BaseCard.vue`](../frontend/src/components/ui/BaseCard.vue) | Card: 3 Padding-Stufen, Surface-Background, Shadow | ✅ Fertig |
| [`components/ui/BaseEmptyState.vue`](../frontend/src/components/ui/BaseEmptyState.vue) | Empty-State: Icon + Titel + Subtitle, zentriert | ✅ Fertig |
| [`components/ui/BaseSpinner.vue`](../frontend/src/components/ui/BaseSpinner.vue) | CSS-only Spinner: 2 Grössen, accessible | ✅ Fertig |
| **Stores** | | |
| [`stores/auth.ts`](../frontend/src/stores/auth.ts) | Login, Register, Token-Persistenz, fetchMe, Household-Wechsel | ✅ Fertig |
| [`stores/shopping.ts`](../frontend/src/stores/shopping.ts) | Shopping CRUD, Optimistic Updates, Repository-Pattern, Race-Condition-Schutz | ✅ Fertig |
| [`stores/todos.ts`](../frontend/src/stores/todos.ts) | Todos CRUD, Optimistic Updates, Repository-Pattern, Race-Condition-Schutz | ✅ Fertig |
| [`stores/expenses.ts`](../frontend/src/stores/expenses.ts) | Expenses CRUD, Socket-Handler, debounced Balances-Refetch, Optimistic Delete | ✅ Fertig |
| [`stores/settlements.ts`](../frontend/src/stores/settlements.ts) | Settlements CRUD, Socket-Handler | ✅ Fertig |
| [`stores/chores.ts`](../frontend/src/stores/chores.ts) | Chores CRUD, Optimistic Updates, Toggle-Mutex, 5 Socket-Handler | ✅ Fertig |
| **Repositories** | | |
| [`repositories/shoppingRepository.ts`](../frontend/src/repositories/shoppingRepository.ts) | ShoppingRepository Interface + Online-Factory | ✅ Fertig |
| [`repositories/todosRepository.ts`](../frontend/src/repositories/todosRepository.ts) | TodosRepository Interface + Online-Factory | ✅ Fertig |
| [`repositories/householdsRepository.ts`](../frontend/src/repositories/householdsRepository.ts) | HouseholdsRepository Interface + Online-Factory (join, fetchInviteCode, fetchMembers) | ✅ Fertig |
| [`repositories/expensesRepository.ts`](../frontend/src/repositories/expensesRepository.ts) | ExpensesRepository Interface + Online-Factory (CRUD + getBalances) | ✅ Fertig |
| [`repositories/settlementsRepository.ts`](../frontend/src/repositories/settlementsRepository.ts) | SettlementsRepository Interface + Online-Factory | ✅ Fertig |
| [`repositories/choresRepository.ts`](../frontend/src/repositories/choresRepository.ts) | ChoresRepository Interface + Online-Factory | ✅ Fertig |
| **Utils** | | |
| [`utils/money.ts`](../frontend/src/utils/money.ts) | formatRappen (Intl.NumberFormat), parseAmountToRappen (String-basiert, kein Float) | ✅ Fertig |
| [`utils/apiErrors.ts`](../frontend/src/utils/apiErrors.ts) | Error-Code-Extraktion, i18n-Mapping für maschinenlesbare Backend-Codes | ✅ Fertig |
| **Composables** | | |
| [`composables/useSocket.ts`](../frontend/src/composables/useSocket.ts) | Socket.IO Client-Wrapper | ✅ Fertig |
| [`composables/useConnectivity.ts`](../frontend/src/composables/useConnectivity.ts) | Online/Offline-Erkennung (navigator.onLine) | ✅ Fertig |
| [`composables/useToast.ts`](../frontend/src/composables/useToast.ts) | App-weites Toast-System für Fehler-Feedback | ✅ Fertig |
| **Views** | | |
| [`views/LoginView.vue`](../frontend/src/views/LoginView.vue) | Login-Formular (BaseCard/BaseInput/BaseButton) | ✅ Fertig |
| [`views/RegisterView.vue`](../frontend/src/views/RegisterView.vue) | Registrierungs-Formular (BaseCard/BaseInput/BaseButton) | ✅ Fertig |
| [`views/ShoppingView.vue`](../frontend/src/views/ShoppingView.vue) | Shopping-Seite | ✅ Fertig |
| [`views/TodosView.vue`](../frontend/src/views/TodosView.vue) | Todos-Seite mit Aufgabenliste | ✅ Fertig |
| [`views/HouseholdView.vue`](../frontend/src/views/HouseholdView.vue) | Haushalt-Verwaltung: Invite-Code, Join, Mitglieder, Household-Wechsel, Mobile-Logout | ✅ Fertig |
| [`views/ExpensesView.vue`](../frontend/src/views/ExpensesView.vue) | Ausgaben-Seite: BalanceSummary + ExpenseList | ✅ Fertig |
| [`views/ChoresView.vue`](../frontend/src/views/ChoresView.vue) | Putzplan: "Diese Woche" (Assignments gruppiert nach Tag) + "Ämtli verwalten" (CRUD) | ✅ Fertig |
| **Komponenten** | | |
| [`components/ShoppingList.vue`](../frontend/src/components/ShoppingList.vue) | Shopping-Liste: Touch-optimiert, sticky Quick-Add, Error-Handling | ✅ Fertig |
| [`components/TodoList.vue`](../frontend/src/components/TodoList.vue) | Todo-Liste: Quick-Add, Detail-Edit, Zuweisung, Fälligkeitsdatum, Überfällig-Badge, Initialen-Chips | ✅ Fertig |
| [`components/ExpenseList.vue`](../frontend/src/components/ExpenseList.vue) | Expense-Liste: Sticky Add-Button, Datum/Bezahlt-von Meta, Edit-Dialog, Optimistic Delete | ✅ Fertig |
| [`components/BalanceSummary.vue`](../frontend/src/components/BalanceSummary.vue) | Saldo-Übersicht: Salden pro Mitglied, Ausgleichsvorschläge, Inline-Settlement-Erfassung | ✅ Fertig |
| [`components/ExpenseFormDialog.vue`](../frontend/src/components/ExpenseFormDialog.vue) | Expense-Formular-Dialog: Create/Edit, Even/Custom Split, Betrags-Validierung | ✅ Fertig |
| **Router** | | |
| [`router/index.ts`](../frontend/src/router/index.ts) | Routen: /login, /register, /shopping, /chores, /todos, /expenses, /household + Auth-Guard | ✅ Fertig |

---

## 4. API-Endpoints

| Method | Path | Auth | Beschreibung |
|---|---|---|---|
| POST | `/api/auth/register` | ❌ | User + Household erstellen |
| POST | `/api/auth/login` | ❌ | JWT zurückgeben |
| GET | `/api/auth/me` | ✅ | User-Info + Households |
| GET | `/api/households/{id}/members` | ✅ | Mitglieder-Liste |
| GET | `/api/households/{id}/invite-code` | ✅ | Invite-Code des Households |
| POST | `/api/households/join` | ✅ | Household per Invite-Code beitreten |
| **Shopping** | | | |
| GET | `/api/households/{id}/shopping-items/` | ✅ | Einkaufsliste |
| POST | `/api/households/{id}/shopping-items/` | ✅ | Item hinzufügen |
| PATCH | `/api/households/{id}/shopping-items/{item_id}` | ✅ | Item aktualisieren |
| DELETE | `/api/households/{id}/shopping-items/{item_id}` | ✅ | Item löschen |
| **Todos** | | | |
| GET | `/api/households/{id}/todos/` | ✅ | Todo-Liste |
| POST | `/api/households/{id}/todos/` | ✅ | Todo erstellen |
| PATCH | `/api/households/{id}/todos/{todo_id}` | ✅ | Todo aktualisieren |
| DELETE | `/api/households/{id}/todos/{todo_id}` | ✅ | Todo löschen |
| **Expenses** | | | |
| GET | `/api/households/{id}/expenses/` | ✅ | Ausgaben-Liste (sortiert nach Datum DESC, paginiert) |
| GET | `/api/households/{id}/expenses/balances` | ✅ | Salden + Settlement-Vorschläge (Greedy-Algorithmus) |
| POST | `/api/households/{id}/expenses/` | ✅ | Ausgabe erstellen (even/custom Split) |
| PATCH | `/api/households/{id}/expenses/{expense_id}` | ✅ | Ausgabe aktualisieren (optional Shares neu berechnen) |
| DELETE | `/api/households/{id}/expenses/{expense_id}` | ✅ | Ausgabe löschen (Shares via CASCADE) |
| **Settlements** | | | |
| GET | `/api/households/{id}/settlements/` | ✅ | Settlement-Liste |
| POST | `/api/households/{id}/settlements/` | ✅ | Settlement erstellen |
| DELETE | `/api/households/{id}/settlements/{sid}` | ✅ | Settlement löschen |
| **Chores** | | | |
| GET | `/api/households/{id}/chores/` | ✅ | Chore-Liste (inkl. inaktive) |
| POST | `/api/households/{id}/chores/` | ✅ | Chore erstellen (Validierung, anchor_date) |
| PATCH | `/api/households/{id}/chores/{cid}` | ✅ | Chore aktualisieren (Schedule-Änderung → zukünftige Assignments gelöscht) |
| DELETE | `/api/households/{id}/chores/{cid}` | ✅ | Chore + Assignments löschen |
| GET | `/api/households/{id}/chores/assignments` | ✅ | Assignments (triggert Materialisierung, Fenster max. 92d) |
| POST | `/api/households/{id}/chores/assignments/{aid}/complete` | ✅ | Assignment abhaken (idempotent) |
| POST | `/api/households/{id}/chores/assignments/{aid}/uncomplete` | ✅ | Abhaken rückgängig (idempotent) |
| PATCH | `/api/households/{id}/chores/assignments/{aid}` | ✅ | Reassign (User muss Mitglied sein) |
| **Health** | | | |
| GET | `/api/health` | ❌ | Health-Check |

### Socket.IO Events

| Event | Richtung | Payload |
|---|---|---|
| `join_household` | Client → Server | `{ household_id }` |
| `leave_household` | Client → Server | `{ household_id }` |
| **Shopping** | | |
| `shopping_item_created` | Server → Room | `ShoppingItem` |
| `shopping_item_updated` | Server → Room | `ShoppingItem` |
| `shopping_item_deleted` | Server → Room | `{ id }` |
| **Todos** | | |
| `todo_created` | Server → Room | `TodoItem` |
| `todo_updated` | Server → Room | `TodoItem` |
| `todo_deleted` | Server → Room | `{ id }` |
| **Expenses** | | |
| `expense_created` | Server → Room | `ExpenseResponse` (inkl. shares) |
| `expense_updated` | Server → Room | `ExpenseResponse` (inkl. shares) |
| `expense_deleted` | Server → Room | `{ id, household_id }` |
| **Settlements** | | |
| `settlement_created` | Server → Room | `SettlementResponse` |
| `settlement_deleted` | Server → Room | `{ id, household_id }` |
| **Chores** | | |
| `chore_created` | Server → Room | `ChoreResponse` |
| `chore_updated` | Server → Room | `ChoreResponse` |
| `chore_deleted` | Server → Room | `{ id, household_id }` |
| `chore_assignment_created` | Server → Room | `ChoreAssignmentResponse` |
| `chore_assignment_updated` | Server → Room | `ChoreAssignmentResponse` |

---

## 5. Datenmodell

```
┌──────────────┐    ┌───────────────────┐    ┌──────────────┐
│  Household   │    │ HouseholdMember   │    │    User      │
│──────────────│    │───────────────────│    │──────────────│
│ id (PK)      │◄──┤ household_id (FK) │    │ id (PK)      │
│ name         │    │ user_id (FK)      ├───►│ email        │
│ invite_code  │    │ role              │    │ password_hash│
│ timezone     │    │ joined_at         │    │ display_name │
│ created_at   │    └───────────────────┘    │ created_at   │
└──────┬───────┘                              └──────────────┘
       │
       ├──────────────────┬──────────────────┬──────────────────┐
       │                  │                  │                  │
┌──────▼───────┐  ┌───────▼────────┐  ┌──────▼───────┐  ┌──────▼───────┐
│ ShoppingItem │  │     Todo       │  │   Expense    │  │    Chore     │
│──────────────│  │────────────────│  │──────────────│  │──────────────│
│ id (PK)      │  │ id (PK)        │  │ id (PK)      │  │ id (PK)      │
│ household_id │  │ household_id   │  │ household_id │  │ household_id │
│ name         │  │ title          │  │ description  │  │ title        │
│ quantity     │  │ description    │  │ amount_rappen│  │ description  │
│ category     │  │ assigned_to_   │  │ currency     │  │ recurrence   │
│ is_checked   │  │   user_id      │  │ paid_by_     │  │ weekday      │
│ added_by_    │  │ due_date       │  │   user_id    │  │ day_of_month │
│   user_id    │  │ is_done        │  │ expense_date │  │ rotation_    │
│ created_at   │  │ created_by_    │  │ created_at   │  │   order (JSON│
│ checked_at   │  │   user_id      │  │ updated_at   │  │ next_rotation│
└──────────────┘  │ created_at     │  └──────┬───────┘  │   _index     │
                  │ done_at        │         │          │ anchor_date  │
                  └────────────────┘         │          │ active       │
                                             │          │ created_at   │
                                      ┌──────▼───────┐  │ created_by_  │
                                      │ ExpenseShare │  │   user_id    │
                                      │──────────────│  └──────┬───────┘
                                      │ id (PK)      │         │
                                      │ expense_id   │  ┌──────▼────────────┐
                                      │ household_id │  │ ChoreAssignment   │
                                      │ user_id      │  │───────────────────│
                                      │ amount_rappen│  │ id (PK)           │
                                      └──────────────┘  │ household_id      │
                                                        │ chore_id (FK)     │
┌──────────────┐                                        │ assigned_user_id  │
│  Settlement  │                                        │ due_date          │
│──────────────│                                        │ completed_at      │
│ id (PK)      │                                        │ completed_by_     │
│ household_id │                                        │   user_id         │
│ paid_by_     │                                        │ created_at        │
│   user_id    │                                        └───────────────────┘
│ paid_to_     │
│   user_id    │  Unique: (chore_id, due_date, assigned_user_id)
│ amount_rappen│  Index:  (household_id, due_date)
│ created_at   │
└──────────────┘

Invariante: SUM(expense_shares.amount_rappen) == expense.amount_rappen
(erzwungen im Service-Layer, nicht als DB-Constraint)

Household.timezone: Default "Europe/Zurich", verwendet für Chore-Datumsberechnung
```

---

## 6. Frontend-Architektur (Offline-Ready Pattern)

```
┌─────────────────────────────────────────────────────────┐
│  Vue Components (ShoppingList, TodoList, ChoresView...) │
│  - try/catch um Store-Actions                           │
│  - Toast-Feedback bei Rollback                          │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  Pinia Stores (shopping, todos, chores, expenses,       │
│                settlements)                              │
│  - Optimistic Updates (sofort im UI sichtbar)           │
│  - Rollback bei Server-Fehler                           │
│  - pendingTempIds (Socket-Duplikat-Schutz)              │
│  - pendingToggles (Rapid-Click-Mutex)                   │
│  - Socket-Handler: Idempotent, Server gewinnt           │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│  Repository Layer (Abstraktionsschicht)                  │
│  - ShoppingRepository Interface + Factory               │
│  - TodosRepository Interface + Factory                  │
│  - HouseholdsRepository Interface + Factory             │
│  - ExpensesRepository Interface + Factory               │
│  - SettlementsRepository Interface + Factory            │
│  - ChoresRepository Interface + Factory                 │
│  - JETZT: wraps Axios-Calls                             │
│  - PHASE 2: IndexedDB + SyncQueue einhängbar            │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐  ┌───────────┐  ┌──────────────┐
   │ Axios    │  │ Socket.IO │  │ PHASE 2:     │
   │ (REST)   │  │ (Events)  │  │ IndexedDB    │
   └─────────┘  └───────────┘  └──────────────┘
```

### UI-Architektur

```
┌───────────────────────────────────────────────────┐
│  App.vue (Shell)                                    │
│  ├── Desktop ≥768px: Sticky Top-Bar                 │
│  │   Brand | Nav-Links | Household-Select | Logout  │
│  ├── Mobile <768px: Bottom-Tab-Bar (5 Tabs)         │
│  │   🛒 Einkauf | 🧹 Putzplan | ✅ Aufgaben |       │
│  │   💰 Ausgaben | 🏠 Haushalt                      │
│  ├── Offline-Banner (wenn navigator.onLine=false)   │
│  └── Toast-Container                                │
│                                                     │
│  Design-System: theme.css (CSS Custom Properties)   │
│  - Farbe: Teal #2A9D8F (Primär)                    │
│  - Breakpoint: 768px                                │
│  - Content max-width: 640px (zentriert)             │
│  - Touch-Targets: ≥44×44px                          │
│  - Safe-Area: env(safe-area-inset-bottom)           │
│                                                     │
│  i18n: vue-i18n, detectLocale(), DE/EN              │
└───────────────────────────────────────────────────┘
```

---

## 7. Feature-Status

### ✅ Fertig

| Feature | Backend | Frontend | Echtzeit |
|---|---|---|---|
| User-Registrierung + Login | ✅ | ✅ | — |
| Household-Erstellung (bei Registrierung) | ✅ | ✅ | — |
| Household-Beitritt (Invite-Code) | ✅ POST /join | ✅ HouseholdView | — |
| Invite-Code anzeigen | ✅ GET /invite-code | ✅ HouseholdView | — |
| Household-Mitglieder anzeigen | ✅ GET /members | ✅ HouseholdView | — |
| Household-Wechsel (Multi-Household) | — | ✅ Dropdown in App-Shell | — |
| Navigation (5 Module) | — | ✅ Tab-Bar (Mobile) + Top-Bar (Desktop) | — |
| Einkaufsliste (CRUD) | ✅ | ✅ | ✅ Socket |
| Einkaufsliste — Optimistic Updates | — | ✅ | ✅ |
| Einkaufsliste — Error-Recovery (Toast) | — | ✅ | — |
| Todo-Modul (Backend CRUD) | ✅ | ✅ | ✅ Socket |
| Todo-Frontend-UI (Komplett) | — | ✅ Quick-Add, Detail-Edit, Zuweisung, Fälligkeitsdatum | — |
| Todo-Store (Optimistic Updates) | — | ✅ | ✅ |
| Expenses-Modul (CRUD + Split + Saldo) | ✅ | ✅ ExpensesView, ExpenseList, BalanceSummary, ExpenseFormDialog | ✅ Socket |
| Settlements-Modul | ✅ | ✅ | ✅ Socket |
| Chores-Modul (Putzplan + Rotation) | ✅ | ✅ | ✅ Socket |
| i18n (DE + EN, 205 Keys, Locale-Check) | ✅ | ✅ | — |
| Error-Code-System (maschinenlesbar) | ✅ | ✅ i18n-Mapping | — |
| Offline-Banner | — | ✅ | — |
| Toast-System | — | ✅ | — |
| Repository-Layer (Offline-Ready Seam) | — | ✅ (6 Repos) | — |
| Race-Condition-Schutz (Temp-IDs, Toggle-Mutex) | — | ✅ | — |
| Design-System (CSS Custom Properties) | — | ✅ theme.css + 5 UI-Komponenten | — |
| Mobile-First UI | — | ✅ Bottom-Tab-Bar, Touch-optimiert | — |
| Backend-Tests (Multi-Tenant + Auth) | ✅ 12 Testdateien, 118 Tests | — | — |

### ❌ Offen (nächste Schritte)

| Feature | Aufwand | Prio | Beschreibung |
|---|---|---|---|
| Household erstellen (zusätzlich) | Klein | 🟡 Mittel | Neuen Household erstellen (nicht nur bei Registrierung) |
| Push-Notifications für Chores | Mittel | 🔵 Niedrig | "Du bist dran"-Benachrichtigung |
| Rate-Limiting vor Public Launch | Klein | 🟡 Mittel | Endpoint-basiertes Rate-Limiting |
| Offline-Phase 2 (IndexedDB + SyncQueue) | Gross | 🔵 Niedrig | Lokale Persistenz, Sync-Queue, Conflict Resolution |
| PWA / Service Worker | Gross | 🔵 Niedrig | Offline-Shell, Cache-Strategie |
| Push-Notifications (Todos) | Mittel | 🔵 Niedrig | Reminder für `due_date` |
| Frontend-Tests | Mittel | 🟡 Mittel | Unit-Tests für Stores und Komponenten |
| Deployment (Azure/Docker) | Mittel | 🟡 Mittel | Produktiv-Deployment |
| FR/IT-Sprachen | Klein | 🔵 Niedrig | Locale-Erweiterung |
| Chores-Statistiken | Klein | 🔵 Niedrig | "Wer hat wie oft geputzt" |

---

## 8. Bekannte Einschränkungen

| Thema | Details | Prio |
|---|---|---|
| `updated_at` fehlt | Auf ShoppingItem und Todo — wird für Phase-2 Conflict Resolution gebraucht | Phase 2 |
| `navigator.onLine` unzuverlässig | Captive Portals, WiFi ohne Internet werden nicht erkannt | Phase 2 |
| Kein neuer Household erstellen | Nur bei Registrierung wird ein Household erstellt; Join geht aber | Feature |
| `deleteItem()` Rollback-Position | Bei paralleler Socket-Mutation kann Position abweichen (kosmetisch) | Gering |
| Keine Frontend-Tests | Stores und Komponenten haben keine Unit-Tests | Technische Schuld |
| Auth-Styles dupliziert | Login/Register haben identische Scoped-CSS-Blöcke (Shared-Auth-Component wäre Refactoring) | Gering |
| Emoji-/Icon-Sizes nicht tokenisiert | 48px, 22px Grössen sind hardcoded statt Design-Tokens | Gering |
| Toast-Transitions hardcoded | Nutzen hardcoded Durations statt Design-Tokens | Gering |

---

## 9. Dependencies

### Backend (Python)
| Package | Version | Zweck |
|---|---|---|
| FastAPI | 0.141.1 | Web-Framework |
| SQLAlchemy | (via requirements.txt) | ORM |
| Alembic | 1.18.5 | DB-Migrationen |
| psycopg2-binary | 2.9.12 | PostgreSQL-Driver |
| python-socketio | (via requirements.txt) | WebSocket |
| bcrypt | 4.0.1 | Passwort-Hashing |
| pydantic | 2.13.4 | Validierung |
| python-jose / PyJWT | (via requirements.txt) | JWT |
| pytest | (via requirements.txt) | Testing |

### Frontend (Node.js)
| Package | Version | Zweck |
|---|---|---|
| Vue | 3.5.40 | UI-Framework |
| Pinia | 4.0.2 | State Management |
| Vue Router | 5.2.0 | Routing |
| vue-i18n | (via package.json) | Internationalisierung |
| Axios | 1.19.0 | HTTP-Client |
| socket.io-client | 4.8.3 | WebSocket-Client |
| TypeScript | 7.0.2 | Typisierung |
| Vite | 8.2.0 | Build-Tool |

---

## 10. Abgeschlossene Epics

### Epic 1: UI/UX-Überarbeitung — Design-System + Mobile-First ✅
- **Abgeschlossen:** 05.08.2026
- **Umfang:** Design-Token-System, 5 Basis-Komponenten, App-Shell mit Mobile Tab-Bar + Desktop Top-Bar, alle Views migriert
- **Review:** UI-Polish-Review durchlaufen, 13 Findings behoben
- **Details:** siehe [`.zoocode/todo.md`](../.zoocode/todo.md)

### Epic 2: Todo-Frontend + Household-Beitritt ✅
- **Abgeschlossen:** 05.08.2026
- **Umfang:** TodosView + TodoList (556 Zeilen), HouseholdView mit Join/Invite/Members, Backend Join-Endpoint + Tests
- **Tests:** 5 Backend-Testdateien (Auth-Guard, Shopping-Scoping, Todo-Scoping, Household-Join)

### Epic 3: Expenses-Modul (Ausgaben-Teilung) ✅
- **Abgeschlossen:** 05.08.2026
- **Schritt 1: Datenmodell + Migration** ✅
  - `Expense` + `ExpenseShare` Models, Alembic-Migration `61637c8c98fb`, Rappen-Integer-Konvention
- **Schritt 2: CRUD-API + Split-Logik** ✅
  - Pydantic-Schemas (inline), Service-Funktionen (`split_evenly`, `validate_custom_shares`, `assert_users_in_household`)
  - 4 REST-Endpunkte (GET/POST/PATCH/DELETE), even/custom Split, 44 Tests gesamt (21 neue)
- **Schritt 3: Saldo-Endpoint + Settlement** ✅
  - `GET /balances` mit SQL-Aggregation, `compute_settlements()` Greedy-Algorithmus
  - `BalancesResponse` (balances + settlements + unassigned_rappen), 56 Tests gesamt (12 neue)
- **Schritt 4: Socket.IO-Events** ✅
  - `expense_created/updated/deleted` Events, identisches Pattern wie Shopping/Todos
  - Kein `balances_updated`-Event (Frontend refetcht stattdessen), 61 Tests gesamt (5 neue)
- **Schritt 5a: Frontend-Datenschicht** ✅
  - Types, Repository, Pinia Store (Composition API), Socket-Handler in App.vue, Money-Helper
  - `vue-tsc --noEmit` erfolgreich, kein Optimistic-Update bei Create (serverseitiger Split)
- **Schritt 5b: Vue-Views + Routing** ✅
  - ExpensesView, ExpenseList, BalanceSummary, ExpenseFormDialog
  - Route `/expenses`, Navigation (4 Tabs), Members im Expenses-Store
  - Even/Custom-Split UI, Betragsvalidierung via `parseAmountToRappen`, Optimistic Delete

### Epic 4: Settlements (Ausgleichszahlungen) ✅
- **Abgeschlossen:** 2026-08-05
- **Umfang:** Settlement-Model + CRUD-API (3 Endpoints) + Frontend (Store, Repository, Inline-Erfassung in BalanceSummary)
- **Tests:** test_settlements.py (23 Tests, Scoping + CRUD + Events + Balance-Integration)

### Epic 5: i18n (Internationalisierung DE/EN) ✅
- **Abgeschlossen:** 2026-08-06
- **Umfang:** vue-i18n, detectLocale (localStorage → navigator.language → en), 205 Keys in de.json + en.json
- **Build-Absicherung:** `check-locales.js` prüft Key-Sync, in Build-Pipeline integriert
- **Error-Codes:** Maschinenlesbare Codes (backend) → i18n-Keys (frontend)

### Epic 6: Chores-Modul (Putzplan mit Ämtli-Rotation) ✅
- **Abgeschlossen:** 2026-08-06
- **Design-Entscheidungen:**
  - Kalender-basierte Rotation (nicht erledigungsbasiert)
  - Lazy-Materialisierung (kein Cron/Background-Job)
  - Household-Zeitzone (Default: Europe/Zurich)
  - Recurrence: weekly/biweekly/monthly (bewusst simpel)
- **Backend:**
  - Models: Chore, ChoreAssignment, Household.timezone
  - Service: `chore_scheduler.py` (Datumsberechnung, Rotation, Materialisierung mit Savepoint-Safety)
  - API: 8 Endpoints (CRUD Chores + 4 Assignment-Endpoints)
  - Migration: `d5f2a8e3b7c1` (+ Postgres Enum-Fix)
- **Frontend:**
  - ChoresView.vue: "Diese Woche" (Assignments gruppiert nach Tag) + "Ämtli verwalten" (CRUD)
  - Store mit Optimistic Updates, Toggle-Mutex, 5 Socket-Handler
  - Route /chores, 🧹-Tab in Navigation (5 Module)
- **Tests:** 36 neue Tests (28 API/Scheduler + 8 Scoping), Gesamt: 118
- **Manuelle Akzeptanz:** Chore "wöchentlich montags" mit 2-User-Rotation angelegt → Assignment mit korrektem User, Abhaken live sichtbar, Sprachwechsel DE↔EN vollständig
