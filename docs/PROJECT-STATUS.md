# Haushalt-App — Aktueller Projektstand

**Stand:** 2026-08-12 (aktualisiert)
**Autor:** Tech Lead (automatisch generiert)

---

## 1. Projektübersicht

Eine Haushalt-App für gemeinsame Einkaufslisten, Todos, wiederkehrende Putzpläne mit Ämtli-Rotation und Ausgaben-Teilung mit Ausgleichszahlungen innerhalb eines Haushalts. Multi-User, Echtzeit-Sync via WebSocket, Mobile-First UI, zweisprachig (DE/EN).

| Aspekt | Technologie |
|---|---|
| Backend | Python 3.12+, FastAPI 0.141, SQLAlchemy, Alembic |
| Datenbank | PostgreSQL (via psycopg2) |
| Realtime | Socket.IO (python-socketio) |
| Frontend | Vue 3.5, TypeScript 5.8, Vite 8, Pinia 4 |
| Auth | JWT (Bearer Token), bcrypt-Hashing |
| i18n | vue-i18n, 615 Keys (DE + EN), Build-gesicherter Key-Sync |
| Icons | Phosphor Icons (`@phosphor-icons/vue`) — regular/fill/bold |
| UI | Custom Design-System (CSS Custom Properties, Nunito + Quicksand), Mobile-First |

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
| [`app/models.py`](../backend/app/models.py) | SQLAlchemy Models: Household (+timezone, +currency), User, HouseholdMember, ShoppingItem, Todo, Expense, ExpenseShare, Chore, ChoreAssignment | ✅ Fertig |
| [`app/database.py`](../backend/app/database.py) | DB-Session, Engine, Base | ✅ Fertig |
| [`app/socket_manager.py`](../backend/app/socket_manager.py) | Socket.IO Server, Auth, Room-Join, emit_to_household_sync | ✅ Fertig |
| [`app/core/config.py`](../backend/app/core/config.py) | Pydantic Settings (DB-URL, JWT-Secret, CORS) | ✅ Fertig |
| [`app/core/security.py`](../backend/app/core/security.py) | JWT-Erstellung, Passwort-Hashing/-Verify, Invite-Code-Generierung | ✅ Fertig |
| [`app/core/deps.py`](../backend/app/core/deps.py) | Dependencies: get_current_user, verify_household_access, verify_household_admin | ✅ Fertig |
| [`app/core/error_codes.py`](../backend/app/core/error_codes.py) | Maschinenlesbare Error-Codes (+ Chore-Codes + CURRENCY_MISMATCH, ADMIN_REQUIRED, CANNOT_REMOVE_ADMIN, CANNOT_REMOVE_SELF) | ✅ Fertig |
| [`app/routers/auth.py`](../backend/app/routers/auth.py) | POST /register (household_name ODER invite_code), POST /login, GET /me (inkl. household.currency) | ✅ Fertig |
| [`app/routers/shopping.py`](../backend/app/routers/shopping.py) | CRUD Shopping-Items + Shopping-Lists + Store-Verwaltung (GET /stores, POST /reassign-store) + Socket-Events | ✅ Fertig |
| [`app/routers/todos.py`](../backend/app/routers/todos.py) | CRUD Todos + Socket-Events | ✅ Fertig |
| [`app/routers/households.py`](../backend/app/routers/households.py) | GET /members (inkl. role), GET /invite-code, POST /join (+Event), POST / (create), PATCH (rename, Admin), POST /leave, DELETE /members/{user_id} | ✅ Fertig |
| [`app/routers/expenses.py`](../backend/app/routers/expenses.py) | CRUD Expenses + Split-Logik (even/custom), Pydantic-Schemas inline | ✅ Fertig |
| [`app/routers/settlements.py`](../backend/app/routers/settlements.py) | CRUD Settlements (GET/POST/DELETE) + Socket-Events | ✅ Fertig |
| [`app/routers/chores.py`](../backend/app/routers/chores.py) | CRUD Chores + 4 Assignment-Endpoints + Socket-Events | ✅ Fertig |
| [`app/services/chore_scheduler.py`](../backend/app/services/chore_scheduler.py) | Lazy-Materialisierung, Kalender-basierte Rotation, Datumsberechnung (weekly/biweekly/monthly) | ✅ Fertig |
| [`app/services/invite_code.py`](../backend/app/services/invite_code.py) | Gemeinsame Invite-Code-Generierung mit Retry-Logik | ✅ Fertig |
| `migrations/` | Alembic-Migrationen (9 Versionen) | ✅ Fertig |
| [`scripts/regenerate_invite_codes.py`](../backend/scripts/regenerate_invite_codes.py) | Dry-Run/Apply Script für Invite-Code-Migration | ✅ Fertig |

### Backend-Tests (`backend/tests/`)

| Datei | Abdeckung | Status |
|---|---|---|
| [`conftest.py`](../backend/tests/conftest.py) | SQLite in-memory DB (StaticPool), Multi-Tenant Fixtures (2 Households, 3 User), Socket-Mock | ✅ Fertig |
| [`test_auth_guard.py`](../backend/tests/test_auth_guard.py) | Kein Token → 401, Ungültiger Token → 401, Abgelaufener Token → 401 | ✅ Fertig |
| [`test_shopping_scoping.py`](../backend/tests/test_shopping_scoping.py) | Multi-Tenant Shopping: Eigene Items lesen ✅, Cross-Household GET/POST/PATCH/DELETE → 403 | ✅ Fertig |
| [`test_shopping_stores.py`](../backend/tests/test_shopping_stores.py) | Store-Verwaltung: Distinct Stores, Rename, Dissolve, Cross-Tenant → 403 (9 Tests) | ✅ Fertig |
| [`test_todo_scoping.py`](../backend/tests/test_todo_scoping.py) | Multi-Tenant Todos: Eigene Todos lesen ✅, Cross-Household GET/POST/PATCH/DELETE → 403 | ✅ Fertig |
| [`test_household_join.py`](../backend/tests/test_household_join.py) | Join mit gültigem Code → 200, Ungültiger Code → 404, Bereits Mitglied → 409, Case-insensitiv | ✅ Fertig |
| [`test_expense_scoping.py`](../backend/tests/test_expense_scoping.py) | Multi-Tenant Expenses: Eigene lesen ✅, Cross-Household GET/POST/PATCH/DELETE/Balances → 403 | ✅ Fertig |
| [`test_expense_splits.py`](../backend/tests/test_expense_splits.py) | split_evenly Unit-Tests, Even/Custom-Split API, Validierung (422), PATCH Reshare, DELETE | ✅ Fertig |
| [`test_expense_balances.py`](../backend/tests/test_expense_balances.py) | compute_settlements Unit-Tests (7), Balances-Endpoint Integration (3+1 Scoping) | ✅ Fertig |
| [`test_expense_events.py`](../backend/tests/test_expense_events.py) | Socket.IO Events: create/update/delete emittiert, failed=kein Event, Room-Check | ✅ Fertig |
| [`test_settlements.py`](../backend/tests/test_settlements.py) | CRUD, Scoping, Validierung, Balance-Integration, Socket-Events (23 Tests) | ✅ Fertig |
| [`test_chores.py`](../backend/tests/test_chores.py) | Scheduler-Unit-Tests, API-Tests, Socket-Events (28 Tests) | ✅ Fertig |
| [`test_chore_scoping.py`](../backend/tests/test_chore_scoping.py) | Cross-Household 403 auf alle 8 Endpoints (8 Tests) | ✅ Fertig |
| [`test_currency.py`](../backend/tests/test_currency.py) | Währungs-Mismatch, Default-Currency, /me Response | ✅ Fertig |
| [`test_admin_guard.py`](../backend/tests/test_admin_guard.py) | verify_household_admin: Admin pass, Non-admin reject | ✅ Fertig |
| [`test_households.py`](../backend/tests/test_households.py) | Create, Rename, Join-Event, Members-Role (8 Tests) | ✅ Fertig |
| [`test_leave_remove.py`](../backend/tests/test_leave_remove.py) | Leave/Remove: Auto-Promotion, Cascade, Balances, 403-Regeln (10 Tests) | ✅ Fertig |
| [`test_register.py`](../backend/tests/test_register.py) | Register mit Code, ohne Code, beides/keines → 422 (6 Tests) | ✅ Fertig |

### Frontend (`frontend/src/`)

| Datei | Zweck | Status |
|---|---|---|
| [`App.vue`](../frontend/src/App.vue) | App-Shell: Desktop Top-Bar, Mobile Bottom-Tab-Bar (5 Module: 🛒 🧹 ✅ 💰 🏠), Socket-Binding, Offline-Banner, Toasts | ✅ Fertig |
| [`main.ts`](../frontend/src/main.ts) | App-Bootstrap, Pinia, Router, i18n, Theme-CSS Import | ✅ Fertig |
| [`i18n.ts`](../frontend/src/i18n.ts) | vue-i18n Setup, detectLocale (localStorage → navigator.language → en) | ✅ Fertig |
| [`api/client.ts`](../frontend/src/api/client.ts) | Axios-Client mit JWT-Interceptor, 401-Handler | ✅ Fertig |
| [`types/index.ts`](../frontend/src/types/index.ts) | ShoppingItem, TodoItem, UserInfo, HouseholdInfo (+currency), HouseholdMemberInfo (+role), MeResponse, ChoreInfo, ChoreAssignmentInfo, SettlementInfo | ✅ Fertig |
| **i18n** | | |
| [`locales/de.json`](../frontend/src/locales/de.json) | Deutsche Übersetzungen (272 Keys) | ✅ Fertig |
| [`locales/en.json`](../frontend/src/locales/en.json) | Englische Übersetzungen (272 Keys) | ✅ Fertig |
| [`scripts/check-locales.js`](../frontend/scripts/check-locales.js) | Build-Script: Prüft Key-Sync zwischen DE und EN | ✅ Fertig |
| **Design-System** | | |
| [`assets/theme.css`](../frontend/src/assets/theme.css) | Design-Token-System: Farben (Light/Dark), Typografie (Nunito/Quicksand), Spacing, Radii (card 20px, btn 12px, dialog 24px), Schatten, Transitions, Avatar-Palette, Global Reset | ✅ Fertig |
| [`components/ui/BaseButton.vue`](../frontend/src/components/ui/BaseButton.vue) | Button: 4 Varianten (primary=acc/secondary=chip/danger/ghost), 2 Grössen, Loading-State, radius 12px | ✅ Fertig |
| [`components/ui/BaseInput.vue`](../frontend/src/components/ui/BaseInput.vue) | Input: Label, Error-State, v-model, iOS-Zoom-Prevention (16px), acc-Fokus, radius 12px | ✅ Fertig |
| [`components/ui/BaseCard.vue`](../frontend/src/components/ui/BaseCard.vue) | Card: 3 Padding-Stufen, var(--card) Background, Shadow, radius 20px | ✅ Fertig |
| [`components/ui/BaseCheckCircle.vue`](../frontend/src/components/ui/BaseCheckCircle.vue) | **NEU:** Runde Checkbox (22px), checked=ok+weisser Haken, Phosphor PhCheck bold | ✅ Fertig |
| [`components/ui/BasePillTabs.vue`](../frontend/src/components/ui/BasePillTabs.vue) | **NEU:** Generische Pill-Filterleiste (aktiv=ink/card, inaktiv=chip/ink) | ✅ Fertig |
| [`components/ui/BaseEmptyState.vue`](../frontend/src/components/ui/BaseEmptyState.vue) | Empty-State: Phosphor PhPackage Icon + Titel + Subtitle, zentriert, + Action-Slot | ✅ Fertig |
| [`components/ui/BaseDialog.vue`](../frontend/src/components/ui/BaseDialog.vue) | Dialog (Teleport, Overlay, Esc, Transitions), Phosphor PhX, radius 24px | ✅ Fertig |
| [`components/ui/BaseSkeleton.vue`](../frontend/src/components/ui/BaseSkeleton.vue) | Skeleton-Loading-Platzhalter, bg=chip | ✅ Fertig |
| [`components/ui/BaseSpinner.vue`](../frontend/src/components/ui/BaseSpinner.vue) | CSS-only Spinner: 2 Grössen, accessible, acc-Farbe | ✅ Fertig |
| **Stores** | | |
| [`stores/auth.ts`](../frontend/src/stores/auth.ts) | Login, Register (+ invite_code Option), Token-Persistenz, fetchMe, Household-Wechsel, Socket-Handler (household_updated/member_joined/left/removed) | ✅ Fertig |
| [`stores/shopping.ts`](../frontend/src/stores/shopping.ts) | Shopping CRUD, Optimistic Updates, Repository-Pattern, Race-Condition-Schutz, Store-Verwaltung (fetchStores, reassignStore, activeStoreFilter) | ✅ Fertig |
| [`stores/todos.ts`](../frontend/src/stores/todos.ts) | Todos CRUD, Optimistic Updates, Repository-Pattern, Race-Condition-Schutz | ✅ Fertig |
| [`stores/expenses.ts`](../frontend/src/stores/expenses.ts) | Expenses CRUD, Socket-Handler, debounced Balances-Refetch, Optimistic Delete | ✅ Fertig |
| [`stores/settlements.ts`](../frontend/src/stores/settlements.ts) | Settlements CRUD, Socket-Handler | ✅ Fertig |
| [`stores/chores.ts`](../frontend/src/stores/chores.ts) | Chores CRUD, Optimistic Updates, Toggle-Mutex, 5 Socket-Handler | ✅ Fertig |
| **Repositories** | | |
| [`repositories/shoppingRepository.ts`](../frontend/src/repositories/shoppingRepository.ts) | ShoppingRepository Interface + Online-Factory | ✅ Fertig |
| [`repositories/todosRepository.ts`](../frontend/src/repositories/todosRepository.ts) | TodosRepository Interface + Online-Factory | ✅ Fertig |
| [`repositories/householdsRepository.ts`](../frontend/src/repositories/householdsRepository.ts) | HouseholdsRepository Interface + Online-Factory (join, fetchInviteCode, fetchMembers, + create, rename, leave, removeMember) | ✅ Fertig |
| [`repositories/expensesRepository.ts`](../frontend/src/repositories/expensesRepository.ts) | ExpensesRepository Interface + Online-Factory (CRUD + getBalances) | ✅ Fertig |
| [`repositories/settlementsRepository.ts`](../frontend/src/repositories/settlementsRepository.ts) | SettlementsRepository Interface + Online-Factory | ✅ Fertig |
| [`repositories/choresRepository.ts`](../frontend/src/repositories/choresRepository.ts) | ChoresRepository Interface + Online-Factory | ✅ Fertig |
| **Utils** | | |
| [`utils/money.ts`](../frontend/src/utils/money.ts) | formatRappen (Intl.NumberFormat), parseAmountToRappen (String-basiert, kein Float) | ✅ Fertig |
| [`utils/apiErrors.ts`](../frontend/src/utils/apiErrors.ts) | Error-Code-Extraktion, i18n-Mapping für maschinenlesbare Backend-Codes | ✅ Fertig |
| [`utils/memberColor.ts`](../frontend/src/utils/memberColor.ts) | **NEU:** Deterministisches User→Farbe-Mapping (6 Farben: p1, p2, #94798C, #8A8272, acc, ok) | ✅ Fertig |
| **Composables** | | |
| [`composables/useSocket.ts`](../frontend/src/composables/useSocket.ts) | Socket.IO Client-Wrapper | ✅ Fertig |
| [`composables/useConnectivity.ts`](../frontend/src/composables/useConnectivity.ts) | Online/Offline-Erkennung (navigator.onLine) | ✅ Fertig |
| [`composables/useToast.ts`](../frontend/src/composables/useToast.ts) | App-weites Toast-System für Fehler-Feedback | ✅ Fertig |
| **Views** | | |
| [`views/LoginView.vue`](../frontend/src/views/LoginView.vue) | Login-Formular (BaseCard/BaseInput/BaseButton) | ✅ Fertig |
| [`views/RegisterView.vue`](../frontend/src/views/RegisterView.vue) | Registrierung: Tab-Umschalter (Haushalt gründen / Mit Code beitreten), ?code= Query-Param | ✅ Fertig |
| [`views/ShoppingView.vue`](../frontend/src/views/ShoppingView.vue) | Shopping-Seite | ✅ Fertig |
| [`views/TodosView.vue`](../frontend/src/views/TodosView.vue) | Todos-Seite mit Aufgabenliste | ✅ Fertig |
| [`views/HouseholdView.vue`](../frontend/src/views/HouseholdView.vue) | Haushalt-Verwaltung: 4 Sektionen (Haushalt, Mitglieder, Einladen, App), Leave/Remove, Share-Invite | ✅ Fertig |
| [`views/ExpensesView.vue`](../frontend/src/views/ExpensesView.vue) | Ausgaben-Seite: BalanceSummary + ExpenseList | ✅ Fertig |
| [`views/ChoresView.vue`](../frontend/src/views/ChoresView.vue) | Putzplan: "Diese Woche" (Assignments gruppiert nach Tag) + "Ämtli verwalten" (CRUD), BasePillTabs-Filter (Alle/Meine), Empty-State CTA | ✅ Fertig |
| [`views/NoHouseholdView.vue`](../frontend/src/views/NoHouseholdView.vue) | Kein-Haushalt-Zustand: Gründen / Beitreten | ✅ Fertig |
| **Komponenten** | | |
| [`components/ShoppingList.vue`](../frontend/src/components/ShoppingList.vue) | Shopping-Liste: Store-Chips-Filter, Gruppierung nach Geschäft, Quick-Add mit Store-Übernahme, Kebab-Menü (Rename/Dissolve), Edit-Sheet | ✅ Fertig |
| [`components/ShoppingItemEditSheet.vue`](../frontend/src/components/ShoppingItemEditSheet.vue) | Item-Bearbeitung: Name, Menge, Geschäft (Chips + Freitext), Abteilung (Datalist) | ✅ Fertig |
| [`components/TodoList.vue`](../frontend/src/components/TodoList.vue) | Todo-Liste: Quick-Add, Detail-Edit, BaseCheckCircle, Zuweisung, Fälligkeitsdatum, Überfällig-Badge | ✅ Fertig |
| [`components/ExpenseList.vue`](../frontend/src/components/ExpenseList.vue) | Expense-Liste: Sticky Add-Button, Datum/Bezahlt-von Meta, Edit-Dialog, Optimistic Delete | ✅ Fertig |
| [`components/BalanceSummary.vue`](../frontend/src/components/BalanceSummary.vue) | Saldo-Übersicht: Salden pro Mitglied, Ausgleichsvorschläge, Inline-Settlement-Erfassung | ✅ Fertig |
| [`components/ExpenseFormDialog.vue`](../frontend/src/components/ExpenseFormDialog.vue) | Expense-Formular-Dialog: Create/Edit, Even/Custom Split, Betrags-Validierung | ✅ Fertig |
| **Router** | | |
| [`router/index.ts`](../frontend/src/router/index.ts) | Routen: /login, /register, /shopping, /chores, /todos, /expenses, /household, /no-household + Auth-Guard (+ 0-Haushalte-Guard) | ✅ Fertig |

---

## 4. API-Endpoints

| Method | Path | Auth | Beschreibung |
|---|---|---|---|
| POST | `/api/auth/register` | ❌ | **Geändert:** household_name ODER invite_code |
| POST | `/api/auth/login` | ❌ | JWT zurückgeben |
| GET | `/api/auth/me` | ✅ | User-Info + Households |
| GET | `/api/households/{id}/members` | ✅ | Mitglieder-Liste |
| GET | `/api/households/{id}/invite-code` | ✅ | Invite-Code des Households |
| POST | `/api/households/join` | ✅ | Household per Invite-Code beitreten |
| POST | `/api/households/` | ✅ | **NEU:** Haushalt erstellen (Ersteller wird Admin) |
| PATCH | `/api/households/{id}` | ✅ Admin | **NEU:** Haushalt umbenennen |
| POST | `/api/households/{id}/leave` | ✅ | **NEU:** Haushalt verlassen |
| DELETE | `/api/households/{id}/members/{uid}` | ✅ Admin | **NEU:** Mitglied entfernen |
| **Shopping** | | | |
| GET | `/api/households/{id}/shopping-items/` | ✅ | Einkaufsliste |
| GET | `/api/households/{id}/shopping-items/stores` | ✅ | Distinct Store-Werte |
| POST | `/api/households/{id}/shopping-items/` | ✅ | Item hinzufügen |
| POST | `/api/households/{id}/shopping-items/reassign-store` | ✅ | Store umbenennen/auflösen |
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
| `shopping_items_bulk_updated` | Server → Room | `{ item_ids, changes: { store } }` |
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
| **Households** | | |
| `household_updated` | Server → Room | `{ id, name }` |
| `household_member_joined` | Server → Room | `{ household_id, user_id, display_name, role }` |
| `household_member_left` | Server → Room | `{ household_id, user_id }` |
| `household_member_removed` | Server → Room | `{ household_id, user_id }` |

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
│ currency     │    └───────────────────┘    │ created_at   │
│ created_at   │                              └──────────────┘
└──────┬───────┘
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
Household.currency: Default "CHF", eine Währung pro Haushalt
```

---

## Geschäftsregeln

### Währungsregel
- **Eine Währung pro Haushalt** (`Household.currency`, Default: CHF)
- Expenses und Settlements müssen die Haushaltswährung verwenden
- Fremdwährungs-Mismatch → 422 CURRENCY_MISMATCH
- Kein Multi-Currency (bewusste Design-Entscheidung)

### Rollen und Berechtigungen
- **Zwei Rollen:** `admin` und `member`
- Registrierung mit `household_name` → Ersteller wird `admin`
- Registrierung mit `invite_code` → Beitritt als `member`
- `POST /api/households/` → Ersteller wird `admin`
- Admin-geschützte Endpoints: PATCH Haushalt (rename), DELETE Member
- Keine feingranularen Berechtigungen (bewusst: nur admin/member)

### Haushalt verlassen
- **Immer erlaubt**, auch mit offenem Saldo
- Expenses/Shares werden NICHT gelöscht ("Ehemaliges Mitglied"-Muster)
- Letztes Mitglied verlässt → Haushalt wird komplett gelöscht (CASCADE)
- Einziger Admin verlässt → dienstältestes verbleibendes Mitglied (frühestes `joined_at`, Tiebreaker: `user_id`) wird automatisch Admin
- Kein manueller Admin-Transfer-Dialog (Auto-Promotion-Regel reicht)

### Mitglied entfernen
- Admin darf Mitglieder mit `role="member"` entfernen
- Admin darf andere Admins NICHT entfernen → 403 CANNOT_REMOVE_ADMIN
- Sich selbst entfernen → 422 CANNOT_REMOVE_SELF (nutze /leave stattdessen)
- rotation_order in Chores wird NICHT bereinigt (Scheduler überspringt Nicht-Mitglieder)

### Registrierung
- Genau eines von `household_name` oder `invite_code` muss gesetzt sein
- `household_name` → neuer Haushalt + Admin
- `invite_code` → bestehender Haushalt + Member

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
| i18n (DE + EN, 531 Keys, Locale-Check) | ✅ | ✅ | — |
| Error-Code-System (maschinenlesbar) | ✅ | ✅ i18n-Mapping | — |
| Offline-Banner | — | ✅ | — |
| Toast-System | — | ✅ | — |
| Repository-Layer (Offline-Ready Seam) | — | ✅ (6 Repos) | — |
| Race-Condition-Schutz (Temp-IDs, Toggle-Mutex) | — | ✅ | — |
| Design-System (CSS Custom Properties) | — | ✅ theme.css + 7 UI-Komponenten | — |
| Mobile-First UI | — | ✅ Bottom-Tab-Bar, Touch-optimiert | — |
| Household erstellen (eigenständig) | ✅ POST /households/ | ✅ HouseholdView | — |
| Household umbenennen | ✅ PATCH /households/{id} | ✅ HouseholdView | ✅ Socket |
| Haushalt verlassen / Mitglied entfernen | ✅ POST /leave, DELETE /members/{uid} | ✅ HouseholdView | ✅ Socket |
| Rollen-System (admin/member) | ✅ verify_household_admin | ✅ UI-Anzeige | — |
| Währung pro Haushalt | ✅ Household.currency | ✅ /me Response | — |
| Backend-Tests (Multi-Tenant + Auth) | ✅ 32 Testdateien, ~151 Tests | — | — |
| Dashboard | ✅ | ✅ DashboardView | — |
| Einkauf 2.0 (Multi-Listen, Stores) | ✅ | ✅ ShoppingView | ✅ Socket |
| Aufgaben 2.0 (Unified Tasks) | ✅ | ✅ TodosView | ✅ Socket |
| Finanzen 2.0 (Budget + Bills) | ✅ | ✅ ExpensesView | ✅ Socket |
| Kalender + Events | ✅ | ✅ CalendarView | ✅ Socket |
| Abstimmungen (Polls) | ✅ | ✅ (integriert in Calendar/Food) | ✅ Socket |
| Haustiere (Katzen) | ✅ | ✅ PetsView + PetDetailView | — |
| Essen (Wochenmenü + Rezepte) | ✅ | ✅ FoodView | — |
| Notizen | ✅ | ✅ NotesView | — |
| App-Shell (Bottom-Nav, MoreSheet, Sync-Status) | — | ✅ | — |

### ❌ Offen (nächste Schritte)

| Feature | Aufwand | Prio | Beschreibung |
|---|---|---|---|
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
| Alembic | 1.18.5 | DB-Migrationen (23 Versionen) |
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
- **Umfang:** vue-i18n, detectLocale (localStorage → navigator.language → en), 255 Keys in de.json + en.json
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

### Epic 7: Household-Management + Rollen + Währung ✅
- **Abgeschlossen:** 2026-08-06
- **Umfang:**
  - Household CRUD: Erstellen (POST), Umbenennen (PATCH), Verlassen (POST /leave), Mitglied entfernen (DELETE)
  - Rollen-System: admin/member, verify_household_admin Dependency, Auto-Promotion bei Admin-Abgang
  - Währung: Household.currency (Default CHF), CURRENCY_MISMATCH-Validierung
  - Registrierung: household_name ODER invite_code (XOR-Validierung)
  - Invite-Code-Service: Gemeinsame Generierung mit Retry-Logik
  - Frontend: NoHouseholdView, BaseDialog, überarbeitete RegisterView (Tab-Umschalter), HouseholdView (4 Sektionen)
  - Socket-Events: household_updated, household_member_joined/left/removed
  - 4 neue Socket-Handler im Auth-Store
- **Tests:** 5 neue Testdateien (test_currency, test_admin_guard, test_households, test_leave_remove, test_register), ~33 neue Tests, Gesamt: ~151
- **Migration:** `a194489b8f0e` (add_household_currency)
- **i18n:** 205 → 255 Keys (50 neue Keys für Household-Management, Rollen, Währung)

### Epic 8: Design-Foundation Teil 3 — UI auf Design-System bringen ✅
- **Abgeschlossen:** 2026-08-07
- **Scope:** Rein visuell, kein Backend, keine Funktionsänderungen
- **Design-System-Umsetzung:**
  - Theme-Tokens: Neue Radii (`--radius-card: 20px`, `--radius-btn: 12px`, `--radius-dialog: 24px`)
  - 7 UI-Komponenten auf neue Tokens umgestellt (card, acc, chip, line-strong, ink, sub statt veralteter neutral-Aliases)
  - Buttons: Primary=`var(--acc)`, Secondary=`var(--chip)`, Ghost=`var(--acc)`/`var(--acc-soft)`
  - Karten: radius 20px, Dialoge: radius 24px, Inputs/Buttons: radius 12px
  - Abschnittstitel: `font-family: var(--font-display)` (Quicksand 600)
- **Neue Komponenten:**
  - `BaseCheckCircle.vue`: Runde Checkbox (ok-grün + weisser PhCheck bold), ersetzt native Checkboxen
  - `BasePillTabs.vue`: Generische Pill-Filterleiste (aktiv=ink/card, inaktiv=chip/ink)
  - `utils/memberColor.ts`: Deterministisches User→Farbe-Mapping (6 Farben)
- **Icon-Migration:** Lucide → Phosphor (`@phosphor-icons/vue`), 26 Icons in 16 Dateien migriert, `lucide-vue-next` entfernt
- **Integrationen:**
  - BaseCheckCircle in ShoppingList + TodoList (erledigte Items: line-through + var(--sub))
  - BasePillTabs in ChoresView (ersetzt showOnlyMine Toggle)
- **Validierung:** typecheck ✅, build ✅, 272 i18n-Keys sync ✅
- **i18n:** 255 → 272 Keys (17 neue Keys für PillTabs-Labels, Chores-Filter)

### Epic 9: Dashboard ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** Dashboard-View mit Tagesgruss, Schnellzugriff-Buttons (Shopping, Task, Expense), Widget-Übersicht (Aufgaben, Einkauf, Finanzen)
- **Backend:** `app/routers/dashboard.py` – aggregierter Dashboard-Endpunkt
- **Frontend:** DashboardView.vue, `stores/dashboard.ts`, `repositories/dashboardRepository.ts`
- **Tests:** `test_dashboard_scoping.py` (Multi-Tenant-Scoping)
- **i18n:** `dashboard.*` Keys (15+ Keys: greetings, widgets, quick-actions)
- **Navigation:** Dashboard als Startseite (`/` → `/dashboard`)

### Epic 10: Einkauf 2.0 – Multi-Listen + Stores ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** ShoppingList-Model (Multiple Listen pro Haushalt), Gruppen nach Geschäft/Kategorie, Zuweisung zu Mitgliedern, Artikel-Detailansicht
- **Backend:** `ShoppingList` Model, `app/routers/shopping.py` (list_router + router), Socket-Events `shopping_list_created/updated/deleted`
- **Migration:** `e8f4b2a6c9d3` (add_shopping_lists), `0f34ff355756` (add_ondelete_to_shopping_items_fks)
- **Frontend:** ShoppingView.vue überarbeitet (Listen-Tabs, Gruppen-Toggle, Artikeldetails), `stores/shopping.ts` erweitert
- **i18n:** `shopping.lists`, `shopping.newList`, `shopping.groupByStore`, `shopping.groupByCategory`, `shopping.storePlaceholder`, `shopping.assignToMe` etc.

### Epic 11: Aufgaben 2.0 – Unified Tasks ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** Aufgaben-View vereinigt Todos + Chore-Assignments in einer Timeline-Ansicht (Überfällig / Heute / Diese Woche / Später). Todo-Tags, Todo-Claim, Personen-Filter (PillTabs)
- **Backend:** `app/routers/tasks.py` – Unified Tasks Endpoint (merges todos + chore assignments), `Todo.tags` JSON-Feld, Claim-Endpoint
- **Migration:** `e6cbf2921e48` (add_tags_to_todos)
- **Frontend:** `TodosView.vue` (komplett neu als Unified Tasks), `stores/tasks.ts`, `repositories/tasksRepository.ts`, UnifiedTask-Type
- **Tests:** `test_todo_tags.py`, `test_todo_claim.py`
- **i18n:** `tasks.*` Keys (filterAll, filterShared, groupOverdue/Today/ThisWeek/Later, claim, recurring, manageChores)

### Epic 12: Finanzen 2.0 – Budget + Wiederkehrende Rechnungen ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** Budget pro Monat, wiederkehrende Rechnungen (RecurringBill), Rechnungs-Buchung als Expense, Finanz-Übersicht mit Budget-Balken
- **Backend:** `Budget` + `RecurringBill` Models, `app/routers/budgets.py`, `app/routers/recurring_bills.py`, Finanz-Summary-Endpoint
- **Migration:** `f1a2b3c4d5e6` (add_finance_v2_models)
- **Frontend:** ExpensesView.vue überarbeitet (Budget-Widget, Pending Bills, Recent Expenses, Bill-Management), `stores/finance.ts`, `repositories/financeRepository.ts`
- **Tests:** `test_budget_scoping.py`, `test_recurring_bill_scoping.py`, `test_recurring_bill_book.py`, `test_finance_summary.py`
- **i18n:** `finance.*` Keys (available, budgetLine, noBudget, setBudget, pendingBills, recurringBills, addBill etc.)
- **Socket-Events:** `budget_updated`, `recurring_bill_created/updated/deleted/booked`

### Epic 13: Kalender + Polls ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** Event-Kalender (Wochenansicht + Liste), Event-CRUD, Ganztägige Events, Kategorien (arbeit, katzen, haushalt, freunde, geburtstage, essen, sonstiges), Abstimmungen (EventPoll) mit Vote + Entscheidung → Event-Erstellung
- **Backend:** `Event`, `EventPoll`, `EventPollOption`, `EventPollVote` Models, `app/routers/events.py`, `app/routers/polls.py`
- **Migration:** `4678310121c3` (add_events_table), `d155cbf3f424` (add_event_polls), `k5l6m7n8o9p0` (add_poll_type_and_recipe_id)
- **Frontend:** CalendarView.vue (Wochen- und Listenansicht), `stores/calendar.ts`, `stores/polls.ts`, `repositories/calendarRepository.ts`, `repositories/pollsRepository.ts`, `utils/categoryColors.ts`
- **Tests:** `test_event_scoping.py`, `test_poll_scoping.py`
- **i18n:** `calendar.*` Keys (25+ Keys), `polls.*` Keys (18+ Keys)
- **Socket-Events:** `event_created/updated/deleted`, `poll_created/voted/decided/deleted`

### Epic 14: Haustiere (Katzen) ✅
- **Abgeschlossen:** 2026-08-07
- **Umfang:** Pet-Management (Name, Rasse, Geburtsdatum, Gewicht, Foto-URL), Fütterungs-Log (Morgen/Abend pro Tag), Medikamente-Management + Verabreichungs-Log, Detail-Profil-Seite (Chip-Nr, Versicherung, Tierarzt, Futter-Notizen, Gesundheitseinträge mit Ampel-System)
- **Backend:** `Pet`, `FeedingLog`, `Medication`, `MedicationLog` Models, `app/routers/pets.py`
- **Migration:** `g1h2i3j4k5l6` (add_pets_and_feeding_logs), `h2i3j4k5l6m7` (add_medications_module), `i3j4k5l6m7n8` (add_pet_profile_fields)
- **Frontend:** PetsView.vue (Übersicht mit Fütterungs-Widget), PetDetailView.vue (Profil, Medikamente, Gesundheitseinträge), `stores/pets.ts`, `repositories/petsRepository.ts`
- **Tests:** `test_pet_scoping.py`, `test_feeding_scoping.py`, `test_medication_scoping.py`
- **i18n:** `pets.*` Keys (50+ Keys inkl. Medikamente, Gesundheit, Profil)

### Epic 15: Essen (Wochenmenü + Rezepte) ✅
- **Abgeschlossen:** 2026-08-08
- **Umfang:** Rezept-Verwaltung (Name, Portionen, Kosten, Dauer, Zutaten-Liste, Favoriten), Wochenmenü-Planung (Rezept oder Freitext pro Tag), "Fehlende Zutaten zur Einkaufsliste"-Button, Essens-Abstimmung (poll_type='meal')
- **Backend:** `Recipe`, `MealPlanEntry` Models, `app/routers/food.py` (recipe_router + meal_plan_router)
- **Migration:** `j4k5l6m7n8o9` (add_food_module)
- **Frontend:** FoodView.vue (Wochenmenü, Rezept-CRUD, Meal-Polls), `stores/food.ts`, `repositories/foodRepository.ts`
- **Tests:** `test_food_scoping.py`, `test_food_shopping.py`, `test_meal_poll.py`
- **i18n:** `food.*` Keys (35+ Keys)
- **Security-Review:** `docs/security-review-food-module.md`, `docs/security/food-module-review.md`

### Epic 16: Notizen ✅
- **Abgeschlossen:** 2026-08-08
- **Umfang:** Notiz-CRUD (Titel, Body, Tag, Pinned), Angepinnte Notizen oben, Tag-Filter
- **Backend:** `Note` Model, `app/routers/notes.py`
- **Migration:** `l6m7n8o9p0q1` (add_notes_module), `m7n8o9p0q1r2` (add_ondelete_set_null_notes)
- **Frontend:** NotesView.vue, `stores/notes.ts`, `repositories/notesRepository.ts`
- **Tests:** `test_note_scoping.py`
- **i18n:** `notes.*` Keys (15 Keys)

### Epic 17: Feinschliff 0d – App-Shell, Navigation, UI-Polish ✅
- **Abgeschlossen:** 2026-08-08
- **Umfang:**
  - Mobile Bottom-Nav vereinfacht auf 4 Tabs + "Mehr"-Sheet (Start, Kalender, Aufgaben, Einkauf, Mehr)
  - MoreSheet-Komponente: Overlay-Bottom-Sheet mit 5 Einträgen (Finanzen, Katzen, Essen, Notizen, Einstellungen)
  - Desktop Top-Bar: 6 direkte Nav-Links (Start, Kalender, Einkauf, Aufgaben, Finanzen, Haushalt) — Putzplan-Link entfernt, stattdessen "Ämtli verwalten"-Link in der Aufgaben-View
  - Sync-Status-Indikator (grün/gelb/grau) in Bottom-Nav und Top-Bar
  - BaseAvatar-Komponente mit deterministic User→Farbe-Mapping
  - PageHeader-Komponente für konsistente Seitenkopfzeilen
  - `useTheme` Composable
  - `utils/dates.ts` – formatDateShort Helper
- **Frontend:** TheBottomNav.vue, MoreSheet.vue, BaseAvatar.vue, PageHeader.vue, `composables/useTheme.ts`, `utils/dates.ts`
- **i18n:** `nav.*`, `moreSheet.*`, `sync.*` Keys
- **Navigation-Konsolidierung:** `/chores` aus Desktop-Top-Bar entfernt, "Ämtli verwalten"-Link (PhBroom) in TodosView ergänzt (`tasks.manageChores` Key)

### Epic 18: Upload-Infrastruktur + Katzenfotos ✅
- **Abgeschlossen:** 2026-08-10
- **Umfang:**
  - Wiederverwendbare Datei-Upload-Infrastruktur (lokal, später Supabase-Adapter)
  - StoredFile Model + LocalStorageService (data/uploads/{household_id}/{uuid}{ext})
  - Files Router: POST (Upload + Pillow-Resize auf 1600px), GET (JWT-geschützter Download), DELETE (mit FILE_IN_USE-Schutz)
  - Pet-Foto-Integration: PATCH pet mit photo_file_id, Validierung Household+MIME
  - Frontend: JWT-geschützter Blob-Download via ObjectURL, useProtectedImage Composable
  - PetPhotoAvatar Component (sm/md/lg), Upload-Flow in PetDetailView, Thumbnails in PetsView
  - Docker: uploaddata Volume für Persistenz
  - Security-Härtung: Chunk-basiertes Lesen, MAX_IMAGE_PIXELS, PDF Magic-Byte, EXIF-Rotation, Path-Traversal-Defense, Content-Disposition-Sanitisierung
- **Backend:** `routers/files.py`, `services/storage.py`, `models.py` (StoredFile), `routers/pets.py` (photo_file_id)
- **Frontend:** `repositories/filesRepository.ts`, `composables/useProtectedImage.ts`, `components/PetPhotoAvatar.vue`, PetDetailView, PetsView
- **Tests:** 14 neue Tests in `test_files_scoping.py` (Cross-Tenant, Validation, Upload/Download/Delete)
- **Reviews:** Security-Review (`docs/security/epic8-upload-review.md`), Business-Logic-Review (`docs/review-epic8-upload.md`)
- **i18n:** 9 neue Keys (pets.photo*, files.*) → 588 Keys total

### Epic 19: Einkaufsliste „nach Geschäft" (Redesign + Verwaltung) ✅
- **Abgeschlossen:** 2026-08-12
- **Umfang:**
  - Geschäft als primäres Ordnungskonzept (ersetzt Abteilung/Geschäft-Tabs)
  - Store-Chips-Filter oberhalb der Liste (Alle + je Geschäft mit Badge-Counter)
  - Quick-Add übernimmt automatisch aktiven Store-Filter
  - Item-Edit-Sheet (Bottom-Sheet): Name, Menge, Geschäft (Chips + Freitext), Abteilung
  - Store-Verwaltung: Umbenennen und Auflösen via Gruppen-Header Kebab-Menü
  - Merge-Warnung wenn Ziel-Store bereits existiert
  - Echtzeit-Sync: `shopping_items_bulk_updated` Socket-Event
  - Keine neue DB-Tabelle, keine Migration (Stores bleiben abgeleitete Freitext-Werte)
- **Backend:** 2 neue Endpoints in `routers/shopping.py`: `GET /stores` (distinct), `POST /reassign-store` (Bulk-Update)
- **Frontend:** `ShoppingList.vue` (Hauptumbau), `ShoppingItemEditSheet.vue` (neu), `stores/shopping.ts`, `repositories/shoppingRepository.ts`, `App.vue` (Socket-Registrierung)
- **Tests:** 9 neue Tests in `test_shopping_stores.py` (GET stores, reassign rename/dissolve, cross-tenant, edge cases)
- **Reviews:** Security-Review (`docs/security/epic18-shopping-stores-review.md` — bestanden), Business-Logic-Review (2 Findings behoben: Merge-Warnung + maxlength)
- **i18n:** 15 neue Keys (shopping.allStores, renameStore, dissolveStore, editItem etc.) → 615 Keys total
- **Offener Punkt (nächster Sprint):** Case-insensitive Store-Normalisierung (Backend-Änderung)
