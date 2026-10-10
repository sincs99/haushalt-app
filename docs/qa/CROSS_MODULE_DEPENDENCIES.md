# Cross-Module Dependencies

**Date:** 2026-10-10 · Companion to [FULL_LOGIC_AUDIT.md](FULL_LOGIC_AUDIT.md).

How a change in one module propagates, which invariants must hold along the way, and where inconsistent
states were found. "Verified" = reproduced/checked in this audit (scripts in `audit-evidence/`).

---

## 1. Dependency matrix (who reads/writes whom)

Rows = source module; columns = dependent module. `W` writes/deletes rows of the target, `R` reads it for
derived state, `E` propagates via socket event, `P` triggers push, `C` FK cascade/SET NULL.

| Source ↓ / Dependent → | Members | Todos | Chores | Shopping | Expenses/Balances | Bills/Budget | Calendar | Polls | Meal plan/Recipes | Pets | Plants | Documents/Files | Tags | Push/Badge/Widget | Dashboard | Frontend stores |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **Membership (join/leave/remove)** | W | — (assignee kept) | R (rotation skip) | — (assignee kept) | R (ex-member pattern) | R (payer kept) | — (participants kept) | — (votes kept) | — | — | — | C (last leaver deletes) | — | R (recipients) | R | E |
| **Household delete** | C | C | C | C | C | C | C | C | C | C | C | C + files | C | C | — | — |
| **Todos** | — | W | — | — | — | — | — | — | — | — | — | — | R (target) | P/R | R | E |
| **Chores (edit/pause/delete)** | R | — | W/C | — | — | — | — | — | — | — | — | — | R (target) | P/R | R | E (partial) |
| **Shopping** | R (assignee validated) | — | — | W | — | — | — | — | — | — | — | — | R | — | R | E |
| **Expenses** | R | — | — | — | W | R (booked state) | — | — | — | — | — | — | — | — | R (saldo) | E |
| **Settlements** | R | — | — | — | W | — | — | — | — | — | — | — | — | — | R | E |
| **Recurring bill book** | R | — | — | — | W | W | — | — | — | — | — | — | — | — | R | E |
| **Calendar delete** | — | — | — | — | — | — | C (events) | C (decided_event SET NULL) | — | — | — | — | — | — | R | E |
| **Poll decide** | — | — | — | — | — | — | W (event) | W | W (meal) | — | — | — | — | — | R | E (partial for meal) |
| **Recipe delete** | — | — | — | — | — | — | — | C (option SET NULL) | C (entry recipe NULL) | — | — | — | — | — | — | E (meal plan not updated) |
| **Meal plan add-missing** | — | — | — | W (+list) | — | — | — | — | R | — | — | — | — | — | — | E |
| **Pets (delete)** | — | — | — | — | — | — | — | — | — | C (feedings, meds, logs, care) | — | W (photo) | R (target 404) | R | R | E (no child events) |
| **Plants / AI advice** | — | — | — | — | — | — | — | — | — | — | W | W (photo) | R | P | R | E |
| **Documents delete** | — | — | — | — | — | — | — | — | — | (photo if shared, CASA-28) | (photo) | W files | — | P (expiry) | — | E |
| **File cleanup (sched)** | — | — | — | — | — | — | — | — | — | C (photo SET NULL) | C | C (document_files) | — | — | — | — |
| **Tags execute** | R | W | W | — | — | — | — | — | — | W | W | — | W (use_count) | — | R | E |
| **AI** | R (opt-in) | — | — | W (frontend loop) | — | — | — | — | W (recipe save) | — | W (frontend apply) | — | — | — | — | — |
| **Push scheduler** | R | R/W (claims) | W (materialise, claims) | — | — | — | — | — | — | R/W | R/W | R/W | — | P | — | (no emit on materialise) |
| **Auth (refresh/logout)** | — | — | — | — | — | — | — | — | — | — | — | — | — | (subscriptions kept) | — | E (disconnect) |

## 2. Required scenarios (from the brief)

### 2.1 Member removal → expenses → settlements → chores → todos → push

| Aspect | Content |
|---|---|
| Source operation | `POST /leave` or `DELETE /members/{uid}` (`households.py:160-270`) |
| Dependent entities | expense shares & payer (kept), settlements (kept), recurring bill default payer (kept), chore `rotation_order` (kept, skipped), materialised chore assignments (kept, up to 7 days ahead + overdue), todos/shopping `assigned_to_user_id` (kept), events `participant_ids` (kept), poll votes (kept, counted), widget token (kept on leave), push subscriptions (filtered at send time), socket rooms (evicted) |
| Required invariants | Ex-member debts remain visible and settleable (F16); push only to members (H11); each open duty has a responsible person or is visibly "open for all" (H8, decision) |
| Existing implementation | "ehemaliges Mitglied" pattern for finance; scheduler skip; push fallback to all members if assignee is not a member; attention counts only "mine or NULL" |
| Possible failures (verified) | Push "Ämtli heute fällig" to all, but badge/widget 0 and dashboard shows no name (CASA-22); bill default payer stale → booking 422 with raw UUID (CASA-22, J1); ex-member votes counted (CASA-22); widget key revives on rejoin (CASA-22); after settlement, deletion of a settled expense creates a claim for the ex-member who cannot see it (CASA-02, J1); Undo of an ex-member expense → 422, claim lost (CASA-03) |
| Evidence | `journeys/j1_finance_leave.py`, `households/lifecycle.py`, `chores_tasks_time/pg_schedule.py` |
| Missing tests | attention with ex-member assignee; widget token after leave/rejoin; journey settle → delete after departure |

### 2.2 Household switch → Pinia stores → in-flight requests → socket rooms → widget state

| Aspect | Content |
|---|---|
| Source | Header household select / `authStore.switchHousehold` → `App.vue` watch (`App.vue:83-268`) |
| Dependent | 17 stores, socket rooms (leave old/join new), listener rebinding, `refreshAllStores()`, WidgetSettingsCard, AI store, app badge |
| Required invariants | Only the current household's data is displayed; requests for the old household are discarded; socket events of the old room are not applied (H10) |
| Implementation | `resetHouseholdScopedStores()`; generation guards in pets/plants/documents only; rooms switched correctly |
| Failures (verified) | Late responses re-fill 12 stores with the old household's data incl. balances and `activeListId` (CASA-12); A → null → C not reset; WidgetSettingsCard shows old key; AI suggestion saved to new household (CASA-34) |
| Evidence | `households/staleSwitch.test.ts`, `frontend_realtime_ux/races.test.ts` R1/R2 |
| Missing tests | per-store late-response tests; App-level A→null→C test |

### 2.3 Recurring bill booking → expense → balances → budget → dashboard

| Aspect | Content |
|---|---|
| Source | `POST /recurring-bills/{id}/book` |
| Dependent | Expense (+ shares over current members, `booked_month`), balances, finance summary (`pending_bills.is_booked_this_month`), budget remaining, dashboard saldo |
| Invariants | One booking per bill and household month (F10); Σshares = amount (F1); summary/budget/dashboard agree (F15) |
| Implementation | UNIQUE + IntegrityError → 409; household month |
| Failures | Delete + Undo → link lost → second booking (CASA-03); delete + rebook after departure splits differently than the original (CASA-02); default payer ex-member → 422 (CASA-22); `pending_bills` card not refreshed on other members' bill events (CASA-42); no bill management UI (CASA-58) |
| Verified OK | 8-way concurrent booking → exactly one; month boundaries; summary = dashboard = balances |
| Missing tests | Undo scenario; summary refresh on bill events |

### 2.4 Meal poll decision → meal plan → recipe → shopping list

| Aspect | Content |
|---|---|
| Source | `POST /polls/{id}/meal-decide` |
| Dependent | MealPlanEntry (upsert on `decided_meal_date`), recipe link, "add missing" → shopping items/list |
| Invariants | Decided exactly once (K5); entry has recipe or text (M2); all clients show the decision (M4); planned meals are not silently lost (M3, decision); missing-ingredient import does not duplicate (S7) |
| Failures | `{date}`-only event blanks the day for others (CASA-19); silent overwrite of a manual plan (CASA-19); concurrent write → 500, poll stays open (CASA-19); recipe deleted later → empty entry (CASA-52); import dedupes only first list/exact name, not concurrency-safe (CASA-53) |
| Verified OK | recipe deleted before decide → label fallback; vote after decision rejected; repeated import idempotent |
| Evidence | `journeys/j4_meal_shopping.py`, `shopping_food_calendar/t_polls.out`, `t_food.out` |

### 2.5 Event poll decision → calendar → event notifications

| Aspect | Content |
|---|---|
| Source | `POST /polls/{id}/decide` |
| Dependent | Event (in chosen calendar, household time), poll `decided_event_id`, calendar views, dashboard |
| Invariants | ≤ 1 event (K5); decided poll has its event (K7) |
| Failures | Calendar deleted concurrently → poll decided without event, decider 500 (CASA-20); option without time → event "now" (CASA-60); option times in UTC in the API (CASA-60) |
| Event notifications | **None exist** (no push for events; not in the plan) → PD-K1 |
| Verified OK | full `EventResponse` emitted (L-03 fixed); concurrent decide → one event |

### 2.6 Todo completion → unified tasks → dashboard → app badge

| Aspect | Content |
|---|---|
| Source | `PATCH /todos/{id} {is_done}`, tag `todo.done` |
| Dependent | reminders (`notified_at`), `/tasks`, dashboard lists/counts, badge (`/dashboard/badge`), widget summary |
| Invariants | Completed todos generate no reminders; reopening restores future reminders (T2); same classification on all surfaces (T4) |
| Failures | Undo cancels future reminders while the bell is still displayed (CASA-06); `/tasks` unused and classified differently (CASA-43); parallel tag scans → two events (CASA-29) |
| Verified OK | badge events refresh the badge; dashboard "due today" not overdue (L-04 fixed) |

### 2.7 Chore completion → rotation → unified tasks → push scheduler → NFC tag

| Aspect | Content |
|---|---|
| Source | `POST …/assignments/{id}/complete`, tag `chore.assignment.done`, schedule edit, pause |
| Dependent | assignment state, rotation index (unchanged by completion), dashboard/badge/widget, push "Du bist dran", tag resolve |
| Invariants | C4, C5, C8, C9, C10, C11 |
| Failures | Repeated scan completes backlog (CASA-05); execute ≠ resolve (CASA-18); schedule edit backfills overdue + skips a turn + phantom assignments on other clients (CASA-16); paused chore still pushes (CASA-17); scheduler materialisation without socket emit (CASA-46) |
| Verified OK | exactly-once push across workers; reassign re-notifies new assignee |

### 2.8 Pet care completion → logs → due date → push → dashboard

| Aspect | Content |
|---|---|
| Source | `POST …/care-tasks/{id}/complete`, tag `pet.care_task.done` |
| Dependent | `last_done_at`, `next_due_at = today + interval`, `notified_at = NULL`, dashboard pet-care list, badge |
| Invariants | P5; one push per due cycle |
| Failures | Tag reports `changed:true` on a same-day repeat (CASA-29); pet delete cascades care tasks without child events → dashboard/badge keep them on other clients until refresh (CASA-43) |
| Verified OK | L-06 fixed; push claim safe against completion race (µs window) |

### 2.9 Plant AI advice → care task modification → history → notifications → NFC tag

| Aspect | Content |
|---|---|
| Source | `AiPlantCareCard` → `plants.applyAdviceTasks` (sequential PATCH/POST) |
| Dependent | plant care tasks (interval), `care_notes` (append), `species` (fill if empty), next due, push, `plant.water` tag |
| Invariants | PL3 (no duplicates, labelled tasks untouched); PL4 (decision) |
| Failures | Interval change does not move the due date (E-2, CASA via PPD-10); unlabelled user intervals overwritten without old→new display; partial failure leaves a partial application (retry safe); single-plant water tag then also completes non-due water tasks (CASA-29) |
| Verified OK | retry re-reads tasks → no duplicates; notes appended |

### 2.10 Document deletion → stored files → storage quota → notification scheduler

| Aspect | Content |
|---|---|
| Source | `DELETE /documents/{id}`, page removal, orphan cleanup |
| Dependent | `StoredFile` rows + disk files, quota usage, expiry reminders, pet/plant photos sharing a file |
| Invariants | D1–D3, D6 |
| Failures | Raced claims can share a file between a pet photo and a document → document delete removes the pet photo (CASA-28); orphan cleanup vs attach (CASA-27); quota exceeded by parallel uploads (CASA-26); file written to disk but DB commit fails → disk orphan never cleaned (reasoned) |
| Verified OK | deletion removes only owned files sequentially; reminders stop with the document |

### 2.11 Logout → access token → refresh token → Socket.IO → multi-device sessions

| Aspect | Content |
|---|---|
| Source | `POST /auth/logout`, reuse detection, cookie expiry, cross-tab logout |
| Dependent | refresh tokens (one revoked; all on reuse), sockets (all of the user disconnected), push subscriptions, Pinia stores, other tabs |
| Invariants | H9, H10, H11 |
| Failures | Benign concurrent refresh → global logout (CASA-11); stores not cleared → next user sees previous data (CASA-12); silent session end at start keeps push subscription → lock-screen reminders on a logged-out device (CASA-47) |
| Accepted (D) | Logout disconnects sockets on all devices; access token valid ≤ 15 min; no "log out everywhere" |

### 2.12 Network interruption → pending mutation → retry → version merge → server state

| Aspect | Content |
|---|---|
| Source | Offline M0: client IDs for shopping items/lists and todos; no outbox, no automatic retry |
| Dependent | create idempotency, `version`-based stale-event discard, optimistic state and rollback |
| Invariants | S1, S2 (documented limitation), S3 |
| Findings | Backend resurrects a deleted item on a delayed same-id create (documented, not reachable from M0 UI); manual retry after a lost response uses a new id → duplicate; rollback hides an item the server has (CASA-45); 404 on own DELETE re-inserts a ghost (CASA-45); token-refresh reload can wipe fresh state (CASA-44) |
| Note | Before M1/M2 (outbox), tombstones and "404 on DELETE = success" are prerequisites (offline-first-phase2 B4a) |

## 3. Places where technically valid operations combine into invalid outcomes

| # | Combination | Outcome | ID |
|---|---|---|---|
| 1 | Settle all → delete a settled expense (any member) → rebook bill after a departure | Claims toward an ex-member who cannot see them; rent split differently from reality | CASA-02 |
| 2 | Delete booked expense → Undo → "Buchen" on the pending card | Rent booked twice in one month | CASA-03 |
| 3 | Mark todo done → Undo | Future reminder silently gone, bell still shown | CASA-06 |
| 4 | Edit chore weekday on a weekend | Already-overdue duty for the next person, a turn skipped | CASA-16 |
| 5 | Pause chore → (week passes) → reactivate | Pushes during pause; burst of overdue duties after | CASA-17 |
| 6 | Tag resolve shown → partner completes in app → scanner confirms | Older assignment completed instead | CASA-18 |
| 7 | Manual meal plan → meal poll for same day decided | Planned meal silently replaced; others see "no meal" | CASA-19 |
| 8 | Member leaves with today's chore → scheduler at 08:00 | Push to everyone, badge 0 for everyone | CASA-22 |
| 9 | Log out on a family tablet → partner logs in | Partner sees previous user's balances until reload | CASA-12 |
| 10 | Two partners tap "Ausgleichen" for the same suggestion | Debt reversed | CASA-08 |
| 11 | Recipe deleted while planned | Day shows "no meal", entry undeletable via add-missing | CASA-52 |
| 12 | Last two members leave at once → old invite code used later | New joiner sees abandoned data | CASA-10 |
