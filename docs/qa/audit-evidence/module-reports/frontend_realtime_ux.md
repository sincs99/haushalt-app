# Audit area: frontend_realtime_ux

Scope: Vue component → Pinia store → repository → REST → `emit_to_household_sync` → socket → other clients;
Offline M0 (client IDs, `version`), PWA/service worker/push/badge, household switching, reconnect, token refresh, user logic/UX.

Evidence artefacts (all in `$S/work/frontend_realtime_ux/`, `$S` = scratchpad):

| Artefact | What it proves |
|---|---|
| `races.test.ts` + `vitest.scratch.config.mts` → `races.out` | 9 store-level race scenarios (R1–R9) executed against the **real** store code (`frontend/src/stores/*`) with mocked repositories. Run: `cd frontend && npx vitest run --config $W/vitest.scratch.config.mts --reporter=verbose --silent=false` |
| `pg_realtime.py` → `pg_realtime.out` | PostgreSQL harness: chore schedule change emits, stale full-payload overwrites (notes, expenses), create-after-delete, bulk reassign versioning, double DELETE |
| `pg_reminder_version.py` → `.out` | Reminder add/delete emit `todo_updated` without version bump |
| `pg_undo_bill.py` → `.out` | Expense-delete-Undo loses bill link → bill can be booked twice |

Repo untouched (`git status` clean). Existing suite: `npx vitest run` → **33 files, 473 tests passed**; `npm run check:locales` → "Locale files in sync (1173 keys)".

---

## 1. Inventory

| Feature / component | Status | Notes |
|---|---|---|
| Socket transport `useSocket.ts` (auth fn, `reauth`, `session_ended`, recover, reconnect callbacks) | Implemented + verified (`composables/__tests__/useSocket.test.ts`, backend `test_socket_session.py`) | Join failures (`error` event) are not handled (F-14) |
| Central listener binding in `App.vue` (watch on `[token, currentHouseholdId]`, l. 83–268) | Implemented, partly verified | Rebinds and **reloads all core stores on every token change** (every ≤15 min) (F-6) |
| View-local listeners (Calendar, Notes, Food, Pets, Plants, Documents, Tags, Household, Pet/PlantDetail) | Implemented, not behaviourally verified end-to-end | Each view registers `onReconnect` except Chores/Expenses/Shopping/Dashboard/Household (they rely on App.vue) |
| `upsertVersioned` / `isStale` (`utils/syncVersion.ts` l. 18–38) | Implemented + verified (`syncVersion.test.ts`, `syncRaces.test.ts`) | Used by shopping lists/items, todos, chore assignments only |
| Client IDs on create (shopping item/list, todo) | Implemented + verified (backend client-id tests, `pg_realtime` P4) | No protection for **manual** retries (each call new UUID, R9) |
| Optimistic updates + rollback: shopping, todos, chores (complete/uncomplete/remove), notes, calendar, documents, expenses/settlements (delete only) | Implemented, verified for happy paths (store tests) | Rollbacks ignore concurrent server truth (R4) |
| Household switch reset `householdScope.ts` | Implemented + verified (`householdScope.test.ts`) | Only on A→B switch, **not on logout→login** (F-2); in-flight responses not guarded in 12 stores (F-1) |
| Generation/request guards | Implemented + verified only in pets, plants, documents, useProtectedImage, invite/members | Unguarded: shopping, todos, expenses, settlements, chores, finance, dashboard, polls, calendar, notes, food, tasks |
| Reconnect reload (L-14) | Partial | Core stores via `handleReconnect` (App.vue l. 290–297); budget (`fetchBudget`) and member lists not reloaded |
| Offline M0 (backend `version`, client ids, stale-event guard) | Implemented + verified for the 4 versioned entities | Outbox, IndexedDB, timeouts = Planned (M1–M6, G) |
| PWA: precache app shell, no `/api` runtime caching, `navigateFallbackDenylist` | Implemented + verified by config reading (`vite.config.ts` l. 40–53) | No authenticated response cached by SW → no leak across logout/household switch |
| SW update flow (`registerType: 'prompt'`, toast 60 s) | Implemented, not behaviourally verified | No periodic update check, no re-prompt (F-13) |
| Push handler (`public/push-sw.js`), notification click | Implemented, not behaviourally verified | URLs carry no household context (F-11) |
| App badge (`useAppBadge.ts`, SW from push payload) | Implemented + verified (`useAppBadge.test.ts`) | Multi-household flip (F-11); `pet_deleted`/`chore` events don't refresh dashboard (F-10) |
| Offline banner / sync dot / `requireOnline` guard in `useAsyncAction` | Implemented + verified (`useToast`/store tests; prior UX review Q-2) | "connected" dot shown even if room join failed (F-14) |
| Locales DE/EN | Implemented + verified (key parity) | Backend-generated German-only names in tag targets (F-16) |

## 2. Socket contract (backend emit vs. frontend consumer)

Emits: 110 call sites, all after `db.commit()` (checked per function; the five "no direct commit" sites commit inside `commit_or_get_existing` or are in GET materialization / helper wrappers). Emits run via `asyncio.run_coroutine_threadsafe` from the request thread (`socket_manager.py` l. 287–306) → **no ordering guarantee between two concurrent requests**.

| Event | Emitted at | Payload | Consumer | Version? | Assessment |
|---|---|---|---|---|---|
| shopping_item_created/updated | shopping.py 586/651, food.py 556 | full `ShoppingItemResponse` | App.vue → shopping store (upsertVersioned) | yes | OK |
| shopping_item_deleted | shopping.py 679 | `{id}` | App.vue | – | OK (rollback issue R4) |
| shopping_items_bulk_updated | shopping.py 514 | `{item_ids, changes:{store}}` | App.vue → `handleBulkUpdated` | **no** (server bumps version 1→2, `pg_realtime` P5; client patches field, keeps v1) | Low: equal/older-version echo can revert store |
| shopping_list_created/updated/deleted | shopping.py 351/382/421, food.py 538 | full / `{id}` | App.vue | yes | OK; list delete does not remove its items locally (items filtered by `list_id`, invisible) |
| todo_created/updated/deleted | todos.py 215/262/286/333/380/422 | full `TodoResponse` / `{id}` | App.vue | yes, **but reminder add/delete emit `todo_updated` with unchanged version** (`pg_reminder_version.out`: v1 → v1 → v1) | Low: reordered reminder events not detected (F-15) |
| chore_created/updated/deleted | chores.py 253/327/355 | full / `{id,household_id}` | App.vue → chores store (no version) | no | **schedule change deletes assignments without event** (F-3) |
| chore_assignment_created/updated | chores.py 393 (GET!), 439/474/512 | full | App.vue | yes | OK |
| — (no `chore_assignment_deleted`) | — | — | — | — | missing (F-3) |
| expense_created/updated/deleted | expenses.py 336/463/491, recurring_bills.py 306 | full / `{id}` | App.vue → expenses store | **no** (`updated_at` exists but unused) | `handleExpenseUpdated` inserts if missing → resurrects deleted (R6) |
| settlement_created/deleted | settlements.py 117/143 | full / `{id}` | App.vue | no | OK (immutable) |
| budget_updated | budgets.py 79/96 | full `BudgetResponse` incl. `month` | App.vue → `handleBudgetUpdated` | no | handler ignores `month` (F-9) |
| **budget_deleted** | budgets.py 168 | `{household_id, month}` | **none** | – | emitted-but-unconsumed; needed (F-9) |
| recurring_bill_created/updated/deleted/booked | recurring_bills.py 126/162/190/307 | full / ids | App.vue | no | OK |
| event_created/updated/deleted | events.py 179/261/289, polls.py 435 | full `_event_response` (L-03 fixed) | CalendarView + dashboard invalidate | no | OK |
| calendar_created/updated/deleted | calendars.py | full/`{id}` | CalendarView | no | OK (delete refused when events exist) |
| poll_created/voted/decided/deleted | polls.py | full `PollResponse` | App.vue **and** CalendarView (double binding, idempotent) | no | Low: reordered `poll_voted` events can show stale counts |
| **meal_plan_updated** (from poll decide) | polls.py 525–529 | **`{date}` only** | FoodView → `food.handleMealPlanUpdated` replaces whole entry | no | **partial payload stored as full object** (F-5) |
| meal_plan_updated/deleted (food) | food.py 422/458 | full / `{date}` | FoodView | no | OK |
| recipe_* | food.py | full/`{id}` | FoodView | no | OK |
| note_created/updated/deleted | notes.py | full/`{id}` | NotesView | no (`updated_at` unused) | lost updates (F-4) |
| document_*, tag_* | documents.py, tags.py | full/`{id,file_ids}` | DocumentsView, TagsView | no | OK; tags check `household_id` |
| pet_*, feeding_*, medication_*, pet_care_task_* | pets.py | full / ids | PetsView, PetDetailView, App.vue (care tasks) | no | OK; generation-guarded store. `pet_deleted` not in dashboard/badge invalidation (F-10) |
| plant_*, plant_care_* | plants.py | full / ids | PlantsView, PlantDetailView, App.vue | no | OK |
| household_updated / member_joined/left/removed | households.py, ai.py 126 | ids/name | App.vue (auth), HouseholdView | – | `member_joined` not used to refresh member lists of todos/chores/expenses/shopping (F-12) |
| **file_uploaded / file_deleted** | files.py 400/472 | full / `{id}` | **none** | – | emitted-but-unconsumed; **not needed** (photos are referenced via pet/plant/document events) |
| consumed-but-never-emitted | — | — | none found | – | — |

## 3. Versioning

| Entity | `version` (SyncVersionMixin) | `updated_at` | Frontend stale protection |
|---|---|---|---|
| ShoppingList, ShoppingItem, Todo, ChoreAssignment | yes (models.py 273, 298, 335, 627) | yes | `upsertVersioned` |
| Expense, Budget, Note, Document | no | yes (unused by client) | none |
| Settlement, RecurringBill, Chore, Calendar, Event, EventPoll, Pet, Medication, PetCareTask, Plant, PlantCareTask, Recipe, MealPlanEntry, Tag, TodoReminder | no | no | none |

Consequences for unversioned entities (documented as limitation in PROJECT-STATUS §8 "version/updated_at nur teilweise"):
* **Lost updates on the server** whenever a UI sends a full payload built from an older snapshot: verified for notes and expenses on PG (F-4).
* **Stale UI**: delayed `*_updated` events overwrite newer state; `handleExpenseUpdated`/`handleBillUpdated` insert-if-missing resurrect deleted rows (R6).

---

## 4. Invariants

| Invariant | Where enforced | Ops that can violate | Status | Existing tests | Missing tests |
|---|---|---|---|---|---|
| UI shows only data of the current household | `householdScope.ts` reset on switch (App.vue l. 180–182); guards in pets/plants/documents | late fetch response after switch (R1, R2); logout→login of another user (R3) | **Violated** | `householdScope.test.ts` (reset only) | per-store "late response after switch" tests |
| No duplicate entity from REST + socket | client IDs + `upsertVersioned` | – | Verified | `syncRaces.test.ts` | – |
| Newer server state never replaced by older event (versioned entities) | `isStale` (syncVersion.ts l. 18–20) | same-version events with different content (reminders, bulk) | Partially verified | `syncVersion.test.ts` | reminder reorder |
| Optimistic change converges to server truth | per-store rollback | own error after concurrent remote change (R4); stale full snapshot from `refreshAllStores` (R7); REST lost after commit (R9) | **Violated in edge races** | store tests (simple rollback) | R4/R7/R9 |
| Server-deleted entity disappears on all clients | `*_deleted` events | chore schedule change (no event, R5/P1); pet delete → care tasks/dashboard; budget delete | **Violated** | – | chore schedule-change event test |
| Socket payload is a full entity when inserted into store | backend response models | `meal_plan_updated {date}` (R8) | **Violated** | L-03 test covers only `event_created` | meal-plan contract test |
| A user's concurrent edit is not silently lost | none (LWW) | notes, expenses, todos (full-payload PATCH) | **Violated (by design for M0, product decision)** | – | conflict tests (If-Match) |
| Each month's recurring bill is booked at most once | unique `(recurring_bill_id, booked_month)` | delete booked expense + UI Undo (P-undo) | **Violated via UI flow** | `test_recurring_bill_book.py` (direct double book) | delete+undo+rebook |
| SW never serves authenticated API data | no `runtimeCaching`, denylist `/api` (vite.config.ts l. 40–53) | – | Verified (config) | – | build-output assertion |
| Logout removes local user data | `_clearState` (auth.ts l. 287–296) | Pinia stores not reset | **Violated** (R3) | `auth.test.ts` (tokens/marker only) | logout → stores empty |

---

## 5. Findings

### F-1 In-flight GET responses of the previous household overwrite stores after a household switch (12 stores unguarded)
* **Severity:** Medium · **Class:** A · **Confidence:** High
* **Modules:** `stores/shopping.ts` l. 56–71, 121–132; `stores/expenses.ts` l. 42–73; `todos.ts` l. 23–34; `chores.ts` l. 34–58; `finance.ts`; `settlements.ts`; `dashboard.ts` l. 20–36; `polls.ts`; `calendar.ts`; `notes.ts`; `food.ts`; `tasks.ts`; `App.vue` l. 177–184, 264.
* **Observed:** fetch functions read `currentHouseholdId` at start and assign the response unconditionally (`items.value = await repo.fetchAll(householdId)`). If household A's request resolves after the switch to B (reset + B fetch already done), A's data is displayed under B.
* **Evidence:** `races.out` — `R1 items after switch: ["A:Milch A (fremder Haushalt)"]`, `R2 balances after switch: {"household":"A",…,"saldo_rappen":-5000}`.
* **Repro:** slow network; open app in household A (App.vue `refreshAllStores()` fires 13 GETs); immediately switch to B in the header select; A's responses arrive last.
* **Expected:** responses for a household that is no longer current are discarded (the pattern already exists: `captureHousehold` in pets.ts/plants.ts, `requestSeq` in documents.ts).
* **Root cause:** L-07 fix only clears the stores; it does not invalidate requests in flight. Only pets/plants/documents got generation guards in the 07.10. fixes.
* **Impact:** wrong balances/budget shown for the other household (money), A's shopping list shown under B; `fetchLists` also sets `activeListId` to A's list → adding an item in B fails with 400 "list_id does not belong to this household". Self-heals only on next token refresh/reconnect (≤15 min).
* **Fix:** shared `householdGeneration` counter (incremented in `resetHouseholdScopedStores`) captured in every fetch; drop result if changed. Also ignore socket payloads whose `household_id` ≠ current.
* **Regression test:** per store, deferred A-response resolved after reset + B-response (pattern of R1).

### F-2 Logout does not clear household-scoped stores; next login in the same tab shows the previous user's data
* **Severity:** Medium (privacy on shared devices; finance saldo/dashboard of previous user) · **Class:** A · **Confidence:** High (code) / Medium (end-to-end not run in browser)
* **Modules:** `stores/auth.ts` `_clearState` l. 287–296 (sets `currentHouseholdId = null`, no store reset); `App.vue` l. 163–167 (token null → only disconnect) and l. 180 (`if (oldHouseholdId && oldHouseholdId !== householdId) resetHouseholdScopedStores()` — `oldHouseholdId` is `null` after logout → reset skipped). Same for cross-tab logout (`_registerStorageListener` l. 308–315). Logout uses `router.push('/login')`, no page reload.
* **Evidence:** code quotes above; `races.out` R3 (simulation of the App.vue condition): `items visible to next user before fetch returns: ["Privat A"]`. ai/documents/tags reset themselves via a watch (`ai.ts` l. 204), all other stores keep data.
* **Expected:** logout empties all user/household stores (documented intent in offline-first-phase2 §3.4 "Logout … lokale Daten löschen").
* **Impact:** user B logging in on a family tablet sees user A's dashboard (incl. `finance.saldo_rappen`), shopping list, expenses, notes until B's requests return; if they fail (offline), A's data stays.
* **Fix:** call `resetHouseholdScopedStores()` (plus ai/documents/tags) in `_clearState`, or in the App.vue watch when `token` becomes null.
* **Test:** auth store logout → all stores empty; App watch with `old=[t,'A']`, `new=[null,null]`, then `[t2,'C']`.

### F-3 Chore schedule change deletes open assignments without any socket event → phantom assignments on other clients
* **Severity:** Medium · **Class:** A · **Confidence:** High
* **Modules:** `backend/app/routers/chores.py` l. 287–316 (`.delete()` of future open assignments), l. 325–329 (only `chore_updated` emitted); `frontend/src/stores/chores.ts` l. 219–224 (`handleChoreUpdated` replaces chore only); only the editing client refetches (`updateChore` l. 94–97). Dashboard is not invalidated by `chore_*` events (App.vue l. 218–258).
* **Evidence:** `pg_realtime.out` P1: `emits after schedule PATCH: ['chore_updated']`, then `assignments after: [('10ce1ecd','2026-10-15')]`, `complete on stale assignment c2b25c12 -> 404 CHORE_ASSIGNMENT_NOT_FOUND`. `races.out` R5: other client ends with `["as-old@2026-10-12","as-new@2026-10-15"]`.
* **Impact:** other members see the chore twice (old and new date) on Ämtli/Tasks/Dashboard; ticking the old one gives an error toast; wrong person may think it is their turn. Persists until next reload/token refresh.
* **Fix:** emit `chore_assignment_deleted {ids}` (or `chore_assignments_changed {chore_id}`) and refetch assignments in `handleChoreUpdated` when schedule fields changed; add `chore_*` to dashboard/badge invalidation (badge already has them).
* **Test:** backend: schedule PATCH emits deletion event with ids; store: `handleChoreUpdated` with changed recurrence triggers refetch.

### F-4 Silent lost updates for unversioned entities edited with full payloads (notes, expenses, todos …)
* **Severity:** Medium (expenses: amount/shares) · **Class:** C/E (LWW is accepted for M0; no conflict detection, no user feedback) · **Confidence:** High
* **Modules:** `NotesView.vue` l. 122–137 (sends title/body/tag/pinned), `ExpenseFormDialog.vue` l. 221–230 (sends description, amount, payer, date, split, shares), `TodoList.vue` l. 271–276; backend PATCHes apply all sent fields (`notes.py` l. 148–153).
* **Evidence:** `pg_realtime.out` P2: Ben changes note body to "PW: NEU-1234", Anna saves dialog opened earlier → `final body: PW: alt | has version field: False`. P3: Ben corrects amount 100→150 CHF, Anna edits description → `final amount: 10000 | version field: False`.
* **Impact:** household money record silently reverted; edits by partner vanish without notice (the socket update even changes the list behind the open dialog, but the dialog keeps the stale form values).
* **Fix (options in §8):** send only changed fields (cheap, removes most cases), and/or `If-Match: updated_at/version` → 409 + "wurde inzwischen von X geändert".
* **Test:** PG integration: stale PATCH with `If-Match` → 409; frontend: dialog sends diff only.

### F-5 `meal_plan_updated` from a decided meal poll carries only `{date}`; FoodView replaces the entry with it
* **Severity:** Low–Medium · **Class:** A (same family as L-03) · **Confidence:** High
* **Modules:** `backend/app/routers/polls.py` l. 525–529 (`{"date": str(meal_date)}`); `frontend/src/stores/food.ts` l. 208–215 (`weekPlan.value[idx] = data`); `FoodView.vue` l. 150–155 (`getDisplayName` → "Kein Essen" if neither recipe nor free_text).
* **Evidence:** `races.out` R8: `weekPlan entry after poll decide event: [{"date":"2026-10-12"}]`. Food emits full `MealPlanEntryResponse` (food.py l. 422) — contract inconsistent.
* **Impact:** everyone with the food view open sees the decided day as "no meal" (and entry without `id`, so "add missing to shopping" can't work) until reload.
* **Fix:** emit `MealPlanEntryResponse` in polls.py; or handler refetches week when payload lacks `id`.
* **Test:** backend contract test that every `meal_plan_updated` payload validates against `MealPlanEntryResponse`.

### F-6 Every access-token change re-runs the App.vue watch → full reload of all core stores; stale snapshot can wipe fresh optimistic/REST state
* **Severity:** Low–Medium · **Class:** A/E · **Confidence:** Medium (store race verified; end-to-end timing reasoned)
* **Modules:** `App.vue` l. 83–87 (watch source includes `authStore.token`), l. 264 (`refreshAllStores()` unconditionally), `client.ts` l. 43–78 (401 → refresh → retry), stores assign full arrays (`shopping.ts` l. 128).
* **Observed:** token lifetime 15 min (`config.py` l. 8). The first action after idle (POST → 401 → refresh) changes the token, which triggers 13 GETs concurrently with the retried POST. A GET snapshot read before the POST commit but delivered after it replaces `items` and removes the just-created item; `upsertVersioned(..., false)` does not re-insert it.
* **Evidence:** `races.out` R7: `items after stale snapshot: []`. Usually healed by the following socket reconnect (token expiry also ends the socket), so effect is a vanish-and-reappear or ≤15 min invisibility.
* **Fix:** don't reload on pure token change (only on household change/reconnect); merge snapshots with pending optimistic entries (or compare `version`, keep entries with `version===0`/newer).
* **Test:** App watch: token change with same household → no `fetchItems`.

### F-7 Rollback after own failed DELETE re-inserts an item another member already deleted (ghost)
* **Severity:** Low · **Class:** A (PROJECT-STATUS §8 lists only "Rollback-Position … kosmetisch") · **Confidence:** High
* **Modules:** `shopping.ts` l. 403–424, `todos.ts` l. 195–216, `expenses.ts` l. 131–150, `settlements.ts`, `chores.ts` l. 114–125.
* **Evidence:** `races.out` R4: `items after own 404: ["i1"]`; backend second DELETE → 404 (`pg_realtime.out` P6: `204 404`).
* **Expected:** 404 on DELETE = success (offline-first-phase2 B4a "Client behandelt 404 als Erfolg" — not implemented in M0), and no reinsertion if a `*_deleted` event arrived meanwhile.
* **Impact:** two people clearing the list together get an error toast and a phantom item that cannot be deleted (404 again) until reload.
* **Fix:** treat 404 as success in repositories' `remove`; track remote deletions during in-flight delete.

### F-8 Manual retry after a lost response creates duplicates; rollback removes an item the server already has
* **Severity:** Low · **Class:** E (M0 has no automatic retry; client-ID idempotency only covers same-ID replays) · **Confidence:** High
* **Modules:** `shopping.ts` l. 209–263 (new `crypto.randomUUID()` per call, rollback `filter` l. 260), same in `todos.ts` l. 44–99; axios without timeout (`client.ts` l. 5–7).
* **Evidence:** `races.out` R9: socket echo arrived, REST failed → `items after rollback: []`; second attempt `client ids … DIFFERENT`.
* **Note on "deleted item recreated by delayed creation retry":** backend behaviour confirmed (`pg_realtime.out` P4: `retry create -> 201 (201 = resurrected)`), but **no frontend path issues a same-ID retry in M0**: no outbox, no axios-retry; the only automatic retry is the 401 interceptor (request rejected by `get_current_user` before the handler ran) and Undo uses new IDs. → documented limitation (D), not reachable today; becomes relevant with M2 outbox.
* **Fix:** keep the optimistic item and mark it "unbestätigt" on network errors (no rollback if a socket echo with same ID arrived); timeout + retry with the **same** ID.

### F-9 Budget socket handling ignores the month; `budget_deleted` is not consumed
* **Severity:** Low · **Class:** A · **Confidence:** High (code)
* **Modules:** `finance.ts` l. 143–152 (`budget.value = data`; patches `summary.budget_rappen` without comparing `data.month` with summary month); `budgets.py` l. 168 emits `budget_deleted` → no listener in App.vue l. 187–258.
* **Impact:** after another member deletes the budget, others still see "Noch verfügbar" based on the deleted budget until reload; a budget saved for another month (API, or device on another side of the month boundary) overwrites the displayed current-month budget.
* **Fix:** compare `month`; on `budget_deleted` set `budget=null` and refetch summary.

### F-10 Dashboard/badge invalidation incomplete
* **Severity:** Low · **Class:** A · **Confidence:** High (code)
* **Modules:** `App.vue` l. 218–258; `useAppBadge.ts` BADGE_EVENTS l. 18–35.
* **Observed:** dashboard (which lists chore titles, pet care, events) is not invalidated by `chore_created/updated/deleted`, `pet_updated/deleted`, `calendar_*`, `budget_deleted`; badge not by `pet_deleted` (cascade-deletes care tasks without `pet_care_task_deleted`). Deleted/paused chores and deleted pets' tasks remain on other members' start page; tapping "erledigt" → 404.
* **Fix:** add the events; or one generic `household_changed` invalidation.

### F-11 Push notifications have no household context; badge flips between households
* **Severity:** Low–Medium (multi-household users only) · **Class:** A/F · **Confidence:** High (code)
* **Modules:** `push_service.py` l. 232 (`"/todos"`), 256 (`/pets/{pet_id}`), 287 (`/plants/{plant_id}`), 362 (`/chores`); `public/push-sw.js` l. 40–57 (navigates to URL as is); router has no `?household=` handling.
* **Impact:** tapping a pet reminder for household B while the app is on A opens `/pets/<id>` in A → "nicht gefunden"/empty; reminder appears lost. SW sets badge from push payload (household B count, `push-sw.js` l. 7–14) while the open app sets it for A (`setAppBadgeHousehold`).
* **Fix:** include `household_id` in push URL (`/pets/<id>?hh=<id>`), switch household on navigation; badge = sum over households or per current.

### F-12 Member lists in feature stores are not refreshed on `household_member_joined/left`
* **Severity:** Low · **Class:** A · **Confidence:** High (code)
* **Modules:** `auth.ts` l. 336–338 (no-op), only `HouseholdView` refetches; `todos.members`, `chores.members`, `expenses.members`, calendar/notes members stay stale until view remount.
* **Impact:** new member not selectable as assignee/payer, shown nameless (avatar missing) in "added by"; departed member still offered as participant.

### F-13 SW update flow: one 60-s toast, no periodic update check
* **Severity:** Low · **Class:** E/F · **Confidence:** Medium (config reading)
* **Modules:** `pwa.ts` l. 9–20 (`registerSW({ onNeedRefresh })` only), `vite.config.ts` l. 8 (`registerType: 'prompt'`).
* **Impact:** installed iOS PWAs stay alive for days; if the toast is missed the old frontend keeps talking to a new backend (current-audit-fixes: "Frontend und Backend müssen gemeinsam veröffentlicht werden"). Push handler is part of the SW, so it updates only after reload.
* **Fix:** `onRegisteredSW` + `registration.update()` on `visibilitychange`/interval; persistent "Update verfügbar" entry in Settings.

### F-14 Failed `join_household` is invisible; status dot shows "verbunden"
* **Severity:** Low · **Class:** A · **Confidence:** Medium
* **Modules:** `socket_manager.py` l. 196–237 emits `error`; `useSocket.ts` has no `error` listener; `App.vue` l. 76–80 status = `isConnected`.
* **Impact:** after a DB hiccup during join the client is connected but in no room → no realtime updates, no indication, until next reconnect/token change.

### F-15 Same-version `todo_updated` events (reminders) are not ordered
* **Severity:** Low · **Class:** A · **Confidence:** High (PG) / reasoned (UI)
* **Evidence:** `pg_reminder_version.out`: `todo_updated after add: version 1 reminders 1` / `after delete: version 1 reminders 0`. `isStale` treats equal versions as fresh → reordered events can show a deleted reminder.
* **Fix:** bump Todo version on reminder changes (touch parent) — consistent with "Netto-Änderung" rule.

### F-16 (UX / product inconsistency) Backend-generated German-only labels for English users
* **Severity:** Low · **Class:** F · `tag_actions.py` l. 326–336 (`PLANT_CARE_TYPE_NAMES` "Gießen"…; comment "Tags kennen keine i18n") used in target lists and scan `target_name`. Locale parity check passes but does not cover backend strings.

### F-17 Expense delete + Undo loses the recurring-bill link → bill can be booked twice
* **Severity:** Medium (money) · **Class:** D (Undo limitation documented in `ExpensesView.vue` l. 205–206 and ux-review F-9 ◐) with **undocumented money consequence** · **Confidence:** High
* **Evidence:** `pg_undo_bill.out`: `undo re-create 201 recurring_bill_id: None` → `summary pending bills: [('Miete', False)]` → `book again 201` → `expenses 'Miete' this month: 2`.
* **Impact:** rent counted twice in balances if someone follows the "zu buchen" hint after an Undo.
* **Fix:** for expenses with `recurring_bill_id`, confirm dialog instead of Undo, or soft-delete/restore endpoint.

### UX classification summary (item 6 of the brief)
* **Confirmed UX defects:** F-5 (decided meal shows "kein Essen"), F-3 (phantom chores + error toast), F-7 (undeletable ghost item), F-11 (notification opens wrong household), F-14 (misleading "verbunden").
* **A11y defects:** none new found beyond prior reviews (BaseDialog focus trap, role=alert toasts, aria labels were fixed per ux-review/current-audit-fixes; not re-audited in a browser).
* **Product inconsistencies:** F-4 (silent overwrite while versioned modules are protected), F-16, attribution: shopping items have `added_by` but no "abgehakt von", todos have no `done_by` (models.py l. 298–370) while chore assignments show "erledigt von" (`ChoresView.vue` l. 443–446).
* **Subjective recommendations:** show "geändert von X" hint when a socket update changes an entity behind an open edit dialog; single persistent update banner instead of 60-s toast.
* Verified OK: duplicate-action prevention via `useAsyncAction` keys (`useAsyncAction.ts` l. 40–74) incl. quick-add per name; offline guard before request; destructive actions use confirm or Undo; DE/EN key parity.

---

## 6. Prior review status

| Item | Status now | Evidence |
|---|---|---|
| L-03 (`event_created` partial payload from poll decide) | **Fixed** — polls.py l. 435 emits `_event_response`. Same defect class still present for `meal_plan_updated` (F-5) | code |
| L-07 (stores not reset on household switch) | **Fixed for the switch itself**, but in-flight responses (F-1) and logout→login (F-2) remain | R1–R3 |
| L-08 (auto-promoted admin sees role only after reload) | **Fixed** — `auth.ts` l. 394–399 `fetchMe()` on other member's leave | code |
| L-14 (reconnect reload) | **Open, mitigated**: App reloads core stores; Calendar/Pets/Plants/Notes/Food/Documents/Tags/Todos/Detail views register `onReconnect`. Not reloaded: budget (`fetchBudget`), member lists, HouseholdView members/invite | grep `onReconnect(` |
| L-15 (ex-member as assignee, no name) | Open (frontend still shows nothing; related F-12) | code |
| L-18 | n/a (unchanged) | – |
| §8 "Wiederholtes Anlegen nach Löschen" | Backend behaviour confirmed; not reachable from M0 frontend (no same-ID retry) | P4, F-8 |
| §8 "`deleteItem()` Rollback-Position (kosmetisch)" | Understated: rollback can resurrect a remotely deleted item (F-7) | R4 |
| current-audit-fixes (pets/plants generation guards, invite guard, photo upload) | Verified present (pets.ts `captureHousehold/captureRequest`, plants.ts, documents `requestSeq`) | code |
| ux-review F-9 ◐ (Undo loses bill link) | Still partial; money consequence verified (F-17) | P-undo |

## 7. Cross-module effects

| Source op | Dependent | Inconsistency |
|---|---|---|
| Chore schedule PATCH | ChoreAssignments (deleted), Dashboard chores, Tasks view, badge | phantom assignments on other clients (F-3) |
| Chore DELETE | assignments (cascade) | handled in chores store; dashboard not invalidated (F-10) |
| Pet DELETE | care tasks, feedings, medications (cascade, no per-child events) | dashboard + badge keep pet tasks (F-10) |
| Meal poll decide | MealPlanEntry | partial payload (F-5) |
| Expense DELETE (+Undo) of booked bill | RecurringBill booking state, balances | double booking possible (F-17) |
| Bulk store reassign | item versions bumped, payload without versions | client keeps old version (low) |
| Household switch / logout | all stores | leakage (F-1, F-2) |
| Token refresh (every 15 min) | all core stores | full reload races with optimistic state (F-6) |
| Shopping list DELETE | items (cascade) | items stay in `items` (hidden by filter) – harmless |

## 8. Test gaps

| Scenario | Recommended type |
|---|---|
| Late response after household switch for each unguarded store | Vitest unit (pattern R1/R2) |
| Logout → login of another user empties stores | Vitest (App watch) or E2E (Playwright) |
| Schedule change emits deletion / other client converges | backend pytest + PG integration + store unit |
| Socket payload contract: each emitted event validates against the store's type | backend contract test (collect emits per router) |
| Reordered events (update after delete; same-version reminders) | Vitest unit + property-based (random event permutations converge to last server state) |
| Stale full-payload PATCH (notes, expenses) | PG integration (after adding If-Match) |
| Delete booked expense + Undo + rebook | PG integration |
| Push click with household context | E2E |
| SW: build output has no `/api` runtime route | build assertion test |

## 9. Product decisions

| Question | Options | Recommendation |
|---|---|---|
| Concurrent edits of unversioned entities (notes, expenses, events) | a) LWW silent (today) · b) send only changed fields · c) `If-Match`/version → 409 + reload hint | b now (cheap), c for expenses (money) |
| Undo of deleting a booked-bill expense | a) recreate without link (today) · b) no Undo, confirm dialog · c) restore endpoint keeping `recurring_bill_id`/`booked_month` | b short term, c later |
| Push for other household | a) open URL in current household (today) · b) switch household automatically · c) ask | b with toast "Gewechselt zu …" |
| Attribution of shared actions | a) as today (added_by, chore completed_by) · b) add `checked_by`/`done_by` | b for shopping/todos (cheap, helps "wer hat das schon gekauft?") |
| Reload on token refresh | a) full reload (today) · b) only on household change/reconnect | b |

## 10. Unverified

* Real browser/iOS behaviour (SW update, push click, badge) — no device/browser run; conclusions from code/config.
* Actual frequency of socket event reordering across request threads (`run_coroutine_threadsafe`) — reasoned, not measured; R6/F-15 rely on it.
* F-2 end-to-end in the real App.vue component (simulated the watch condition; store state retention confirmed by code).
* F-6 end-to-end timing (store race verified; that the subsequent socket reconnect heals it is reasoned).
* Accessibility not re-audited in a browser (screen reader, contrast) — relied on prior reviews.
* HTTP caching of `/api/files/*` responses in the browser cache (no `Cache-Control` set in files.py) — not tested.
