# Area: chores_tasks_time — Ämtli rotation, Todos, Reminders, Unified Tasks, Dashboard, Badge, Push scheduler, temporal logic

Auditor scripts (all under `$S/work/chores_tasks_time/`, S = scratchpad):

| Script | What it does |
|---|---|
| `prop_scheduler.py` | Hypothesis property tests against the real `next_due_dates`, `_resolve_next_assignee`, `_compute_anchor_date` (3000 + 2000 examples) and fixed edge cases |
| `tt.py` | Time-travel helper: patches every "today" source (`chore_scheduler.today_in_tz`, `routers.chores/dashboard.today_in_tz`, `attention.household_today`, `household_time._utc_now`) |
| `pg_concurrency.py` | PG: 12 parallel `GET /chores/assignments` and `GET /tasks`; then 4 parallel scheduler runs and 6 API calls at the same time |
| `pg_schedule.py` | PG: schedule edits, completed future assignment, pause/reactivate, push for a paused chore, L-09, a member leaving, reassign after the push |
| `pg_todos.py` | PG: todo due-date classification in `/tasks`, `/dashboard` and attention (badge and widget) for 4 time zones; reminder lifecycle; assigning a user from another household; claim race |
| `pg_push.py` | PG: 6 parallel scheduler runs over all 5 reminder kinds; DST-end morning boundary; missed day |

Household time zone cannot be changed through the API (`Household.timezone` has no writer in any router; it is always `Europe/Zurich`). Scenarios with other time zones therefore only apply to the frontend device time zone, or to data written directly into the database.

---

## 1. Inventory

| Feature / endpoint / store | Status |
|---|---|
| `chore_scheduler.next_due_dates` (weekly / biweekly / monthly, clamping at month end) | **Implemented and verified**: `prop_scheduler.py` covers incremental vs. one-shot windows, day spacing, weekday/day clamping and anchor = first date; edges Dec 31→Jan 1, Feb 28/29, day 29/31 |
| `_resolve_next_assignee` (rotation, skipping ex-members) | **Implemented and verified**: property test checks round-robin over the remaining members; `None` when no member is left |
| `materialize_due_assignments` (7 days ahead, 14 days back, savepoint, `FOR UPDATE`) | **Implemented and verified on PG for concurrency**. Ignores `anchor_date` after a schedule edit: **defect F1** |
| `POST/PATCH/DELETE /chores/`, `GET /chores/` | Implemented and verified (existing tests and PG scripts). PATCH with a schedule change has defects F1, F3 and F4 |
| `GET /chores/assignments`, `complete`, `uncomplete`, `PATCH` reassign | **Implemented and verified** (idempotent; reassign resets `notified_at`, verified) |
| `GET /tasks` (unified tasks) | Implemented, but **not used by the frontend**: `stores/tasks.ts` is only reset in `householdScope.ts` and no view calls `fetchTasks`. Its classification differs from the dashboard and the badge (F10) |
| `GET /dashboard` | Implemented and verified for todos in Zurich (L-04 fix holds). Chores: only items due today, no overdue items, no materialisation |
| `GET /dashboard/badge`, `GET /api/widget/summary` (both use `attention.due_items`) | Implemented and verified. Inconsistent for ex-member assignees (F6) and paused chores (F3) |
| Todos CRUD, claim, reminders | Implemented. Claim race verified on PG. **Assignee not validated** (F5). **Reopening a done todo loses its future reminders** (F2) |
| Push scheduler `run_once` / `scheduler_loop` (todo, pet, plant, chore, document) | **Implemented and verified**: multi-worker dedupe via conditional UPDATE (`_claim`) on PG; DST-safe local hour. Delivery is at-most-once, which is intended (F11) |
| `household_time.py`, `event_times.py` | Implemented; used consistently by the chores, dashboard and attention code |
| Frontend `stores/chores.ts`, `ChoresView.vue` | Implemented. "Today" is the device date (F13). Rotation can only be reordered (L-16 still open) |
| Frontend `stores/todos.ts`, `TodoList.vue` | Implemented. `getNextReminder` ignores `notified_at`, so it shows a reminder that will never fire (part of F2) |
| Frontend `useAppBadge.ts` | Implemented; it is a thin wrapper around `/dashboard/badge` |
| Docs: PROJECT-STATUS says "Ämtli-Liste … Schedule-Änderung → zukünftige Zuweisungen gelöscht" | Matches the code, but the docs do not mention that past dates can be backfilled after the edit (F1) |

## 2. Invariants

| Invariant | Enforced at | Can be violated by | Status | Existing tests | Missing tests |
|---|---|---|---|---|---|
| At most one assignment per (chore, date) | `models.py:630` `uq_chore_assignment_per_date`; savepoint at `chore_scheduler.py:214-223`; `with_for_update` at `:175` | Concurrent GET /assignments, /tasks or scheduler | **Verified** on PG (12 parallel requests → 5 rows, 0 duplicates; mixed scheduler and API → 11 rows, 0 duplicates) | `test_materialize_idempotent` (SQLite) | PG concurrency test |
| Rotation index advances exactly once per created assignment (+ skips) | `chore_scheduler.py:135-136` | Concurrent materialisation; a duplicate after the savepoint (index already incremented at :136 before the IntegrityError) | **Verified** on PG (index == assignment count for each chore after the parallel runs). Because of `FOR UPDATE`, the IntegrityError path is practically unreachable | `test_rotation_*` | PG |
| Assignment dates follow the current schedule and are never before `anchor_date` after an edit | none (`chore_scheduler.py:190-197` uses `last+1`) | PATCH weekday / day_of_month | **Violated** (F1) | `test_real_schedule_change_continues_rotation` (does not cover a gap ≥ 1 day) | API test: weekday Mon→Wed edited on Saturday |
| Paused chore produces no new work and no notifications | `chore_scheduler.py:174` (no new assignments only) | Materialised assignments remain; push/badge/tasks/dashboard don't filter `Chore.active` | **Violated** for push (F3); visibility is L-10 (decision) | none | push test for a paused chore |
| Reactivated chore does not produce a burst of overdue duties | none | PATCH active=true after a pause of 2 weeks or more | **Violated** (F4) | `test_backfill_limited_to_14_days` (accepts the burst for a new chore) | reactivate test |
| "Du bist dran" goes to the current assignee, once per assignment | `push_service.py:351-357` + `_claim`; reset at `chores.py:505-507` | Multiple workers, reassign | **Verified** (6 parallel workers → 1 push per kind; reassign after the push → new push to the new assignee) | `test_chore_notifies_assignee_once_in_the_morning` | multi-worker PG test |
| A reminder fires once, never for a done todo | `push_service.py:219-222`, `todos.py:251-254` | done → undo/reopen | **Violated** for reopen (F2) | `test_done_and_stale_reminders_claimed_but_not_sent` | reopen test |
| Todo assignee is a household member | **none** | POST/PATCH todos with any user UUID | **Violated** (F5) | none | 422 test |
| Badge, widget, push and dashboard agree on what is "due today / mine" | `attention.py`, `dashboard.py`, `push_service.py` (each its own query) | Ex-member assignee, paused chore, overdue chores | **Partially violated** (F3, F6, F10) | `test_attention_count_per_user` | cross-surface consistency test |
| Todo "due today" is not overdue on its own day | `dashboard.py:177-181`, `attention.py:87`, `TodoList.vue:95-97` | Device or household west of UTC | **Verified** for Zurich; violated west of UTC (F7, reachable only through the device time zone) | `test_dashboard_todo_due_today_is_not_overdue` | — |
| Claim: exactly one winner | `todos.py:316-327` conditional UPDATE | Parallel claims | **Verified** on PG (8 parallel → 1×200, 7×409, 1 emit) | `test_todo_claim.py` (SQLite) | — |
| Scheduler "local morning" is correct across DST | `push_service.py:347-349` (astimezone) | DST days | **Verified** (2026-03-29 08:30 CEST sends; 2026-10-25 06:59Z → 0, 07:00Z → 1) | `test_pet_care_waits_for_morning` | — |

## 3. Findings

### F1 — Editing the schedule creates a past-dated, overdue assignment and uses up a rotation slot
- **Severity:** Medium · **Class:** A · **Confidence:** High
- **Modules:** `backend/app/services/chore_scheduler.py:190-202`, `backend/app/routers/chores.py:295-318`
- **Observed:** Weekly chore on Monday, last assignment Mon 2026-10-05. On Sat 2026-10-10 the weekday changes to Wednesday. The PATCH sets `anchor_date=2026-10-14`. The next materialisation then creates **2026-10-07 (Wednesday, already past, overdue) for Carla** and 2026-10-14 for Anna. Monthly works the same way: the 1st changes to the 8th on 10-10 (anchor 2026-11-08), and an **overdue assignment dated 2026-10-08** for Ben appears.
- **Evidence** (`pg_schedule.py` output):
  ```
  patch 200 anchor 2026-10-14
  after edit: [('2026-09-28','Anna',False), ('2026-10-05','Ben',False), ('2026-10-07','Carla',False), ('2026-10-14','Anna',False)]
  == 2. monthly 1st -> 8th edit on 10-10 ==
  patch 200 anchor 2026-11-08
  after edit: [('2026-10-01','Anna',False), ('2026-10-08','Ben',False)]
  ```
  `prop_scheduler.py`: `weekly Wed anchor 10-14, from 10-06: [2026-10-07, 2026-10-14]`. `_weekly_dates` and `_monthly_dates` only use the anchor for biweekly parity.
- **Root cause:** When a last assignment exists, `from_date = last_assignment.due_date + 1 day` (`chore_scheduler.py:190-191`). It is never clamped to `chore.anchor_date`, which the PATCH recomputed as "first new date ≥ today".
- **Impact:** Right after the edit, a person gets an overdue Ämtli for a day that has already passed. It counts in their badge and widget and shows red in the Putzplan, and it takes their turn in the rotation (Carla's real next turn is skipped). For monthly chores it is almost certain whenever the new day of month is earlier than today.
- **Fix:** In `materialize_due_assignments`, use `from_date = max(from_date, chore.anchor_date, backfill_limit)`. This is safe because `anchor_date` is always the first due date. Alternatively, in the PATCH, do not backfill before today.
- **Regression test:** API test with `today_in_tz` patched to a Saturday: weekly Monday chore, PATCH weekday=2, then assert that no open assignment has `today > due_date > last_old_date`. Add a monthly variant.

### F2 — Marking a todo done and then undoing it (toast "Rückgängig") or reopening it silently disables its future reminders
- **Severity:** High · **Class:** A · **Confidence:** High
- **Modules:** `backend/app/routers/todos.py:248-256`, `backend/app/services/push_service.py:212-222`, `frontend/src/components/TodoList.vue:118-122, 266-273`, `DashboardView.vue:163-173`
- **Observed:** A todo has a reminder 5 hours in the future. It is set done and then undone within a second. The reminder's `notified_at` is set and never reset, so the scheduler never picks it up and the dashboard "upcoming reminders" no longer lists it. `TodoList.getNextReminder` filters only by `remind_at > now`, so **the UI still shows the bell with the future time**.
- **Evidence** (`pg_todos.py`):
  ```
  after done+reopen (undo within seconds): future reminder notified_at = 2026-10-10T07:00:24Z
  push at reminder time after reopen: []
  dashboard upcoming_reminders after reopen: []
  ```
  Code: `if update_data["is_done"] is True: … reminder.notified_at = datetime.now(...)` and in the `else:` branch only `item.done_at = None`.
- **Root cause:** The done path uses `notified_at` as the "cancelled" marker; reopening does not restore it. The prior review (section 6, "Todo wieder öffnen … Zeitpunkt ist eh vorbei") assumed that all reminders are in the past, which is false for the undo path.
- **Impact:** A reminder the user explicitly set never arrives, and the UI claims it is still scheduled. Undo is the advertised way to recover from an accidental tick, so this happens through a normal action.
- **Fix:** On `is_done=False`, reset `notified_at=None` for reminders with `remind_at > now` (and perhaps within `STALE_AFTER`). Alternatively, stop marking reminders on completion: the scheduler already skips reminders of done todos (`push_service.py:221`). The second option is the simplest.
- **Regression test:** PG/API: add a future reminder, PATCH is_done true then false, run `process_todo_reminders` at `remind_at + 1 min` and expect 1 send. Frontend: the bell should be hidden when `notified_at` is set.

### F3 — A paused chore (`active=false`) still sends "Du bist dran" and counts in the badge, widget, tasks and dashboard
- **Severity:** Medium · **Class:** B (extends L-10 / E-3, which only covered visibility) · **Confidence:** High
- **Modules:** `push_service.py:332-344` (no `Chore.active` filter), `attention.py:94-108`, `tasks.py:48-56`, `dashboard.py:217-227`
- **Observed:** A chore is created (assignment Tue 11-24 materialised) and then paused. On 11-24 at 09:30 local time, Anna receives the push "Du bist dran: PausedPush". It also appears in her badge (count 3) and in `/tasks`.
- **Evidence** (`pg_schedule.py`): `pushes on 11-24: [('Du bist dran', 'PausedPush', ['Anna'])]`
- **Impact:** A household pauses an Ämtli (holidays, renovation) and still gets push notifications and a badge count for up to 7 days.
- **Fix:** Add `Chore.active == True` to the push query and to the attention, dashboard and tasks queries. Better: on pause, delete open assignments with `due_date >= today`. That decides E-3 as option (c) for future items, and it also fixes F4's index accounting if the index is given back as the schedule edit does.
- **Test:** push test for a paused chore; badge test.

### F4 — Reactivating a chore after a long pause creates a burst of overdue assignments and advances the rotation
- **Severity:** Medium · **Class:** A/C · **Confidence:** High
- **Modules:** `chore_scheduler.py:190-197`, `chores.py:320-322` (`active` is set without any re-anchoring)
- **Observed:** A weekly Saturday chore is paused on 10-10 and reactivated on 11-21. Materialisation immediately creates **11-07 (Carla) and 11-14 (Anna) as overdue**, plus 11-21 and 11-28. Two people get overdue duties for weeks when the chore was paused, and their badges increase.
- **Evidence:** `overdue open right after reactivation: [('2026-11-07','Carla',False), ('2026-11-14','Anna',False)]`
- **Root cause:** The 14-day backfill runs from the last assignment. Reactivation is not treated as a fresh start.
- **Fix:** When `active` changes from False to True, set `anchor_date = _compute_anchor_date(…, today)` and materialise from `max(last+1, anchor)` (same clamp as F1).
- **Test:** API test for pause, then reactivate 6 weeks later; assert no open `due_date < today`.

### F5 — Todo assignee is not validated: any user UUID, including a user of another household, is accepted
- **Severity:** Medium · **Class:** B · **Confidence:** High
- **Modules:** `backend/app/routers/todos.py:196-204` (create), `:242-245` (patch). There is no `assert_users_in_household` call; chores, expenses and recurring_bills do have one (`grep` count: chores 3, expenses 7, recurring_bills 4, todos 0).
- **Evidence** (`pg_todos.py`): `create todo assigned to user of another household: 201`, `patch assign to foreign user: 200`.
- **Impact:** Integrity problem. A todo that is "assigned" to a non-member is invisible in "Meine" and in everyone's badge (attention filters by `assigned_to_user_id == user or NULL`), its reminder falls back to all members, and the UI shows no name. It also lets a client probe for user UUIDs (no content leaks; the foreign user cannot read the todo). Offline sync clients (stale member lists) can create such todos without anyone noticing.
- **Fix:** Call `assert_users_in_household(db, household_id, [assigned_to_user_id])` on create and patch when the value is not None. To allow a stale ex-member on patch, use the same rule as L-05.
- **Test:** POST/PATCH with a foreign user → 422 `USERS_NOT_IN_HOUSEHOLD`.

### F6 — Assignments and todos of a departed member: push goes to everyone, but the badge and widget count nothing
- **Severity:** Low–Medium · **Class:** A (inconsistency) / relates to L-15, E-6 · **Confidence:** High
- **Modules:** `push_service.py:354-357` (falls back to all members), `attention.py:84, 101-104` (only `== user_id` or `NULL`), `dashboard.py:217-236`
- **Observed:** Q is the assignee for today's "Trash" and leaves. The scheduler sends "Ämtli heute fällig" to P, but P's badge is **0**. The dashboard lists the chore with Q's UUID (the UI shows no name). After P reassigns it to themselves: a new push and badge 1.
- **Evidence:** `badge P … {'count': 0}`, `push for Trash: [('Ämtli heute fällig','Trash',['P'])]`.
- **Impact:** Duties already materialised for someone who left (up to 7 days ahead, plus overdue ones) are nobody's. The badge and widget hide them, while the push says they are open.
- **Fix:** Pick one rule. Either attention treats assignees who are no longer members like `NULL`, or leaving or removal sets `assigned_user_id=NULL` on open assignments and todos (E-6 option b). The second is the recommended one; the same transaction could also clean up `rotation_order` (E-7).
- **Test:** attention test with an ex-member assignee.

### F7 — Todo due dates are stored as 00:00 UTC; on devices west of UTC, a todo shows the previous day and is overdue on its due day
- **Severity:** Low · **Class:** D/E (already noted as "Unschärfe" in logic-review §6) · **Confidence:** High
- **Modules:** `models.py:347-349` (`DateTime(timezone=True)`), `TodoList.vue:95-97`, `utils/dates.ts:82-89`, `attention.py:87`, `dashboard.py:177-181`
- **Evidence** (`pg_todos.py`, household tz forced to America/New_York in the DB): `dashboard overdue_count: 2 … ('due_today', True)`, `attention … ('due_today','overdue'), ('due_tomorrow','today')`. In Zurich, after 00:30 local time and in Auckland, the backend is consistent and correct.
- **Reachability:** The household time zone has no API writer, so in practice this only affects frontend users whose device is west of UTC (travelling). `formatDateShort` and `isOverdue` then show the day before and mark the todo red.
- **Fix:** Make `due_date` a `Date` column (migration: `due_date::date` in UTC), or have the frontend treat the value as a date string (`substring(0,10)`).

### F8 — A future assignment completed early blocks the new schedule after an edit (one period is skipped)
- **Severity:** Low · **Class:** C (documented as "Unschärfe, selten" in logic-review §2) · **Confidence:** High
- **Evidence:** Friday 10-16 is completed early, then the weekday changes Fri→Mon on 10-10 (anchor 10-12). Result: only `[('2026-10-16','Anna',True)]`. There is no Monday 10-12; the next one will be 10-19.
- **Fix:** Use the same clamp as F1 but count only open assignments. Alternatively, accept and document it.

### F9 — Materialisation through `/tasks`, the push scheduler and the tag path does not emit `chore_assignment_created`
- **Severity:** Low · **Class:** A · **Confidence:** High
- **Modules:** `tasks.py:46` and `push_service.py:322` call `materialize_due_assignments` without emitting (only `chores.list_assignments` emits, at `:391-397`).
- **Evidence** (`pg_concurrency.py`): 11 assignments created, only 5 `chore_assignment_created` emits (the first round was won by the `/tasks` path → 0 emits).
- **Impact:** A Putzplan that is open on another device does not show the new assignments until it reloads (e.g. at 08:00 the scheduler creates the next week's assignments).
- **Fix:** Emit from inside `materialize_due_assignments` after the commit (or return the rows and emit in all callers).

### F10 — The "what's due" surfaces disagree: `/tasks`, dashboard, and badge/widget
- **Severity:** Low · **Class:** F/E · **Confidence:** High (code reading plus scripts)
- `/tasks` (`tasks.py:48-56`) returns **all** open assignments with no 14-day lookback and including paused chores. Dashboard chores (`dashboard.py:217-227`) show only items due **today**: no overdue items and no materialisation. Badge and widget (`attention.py:94-108`) count overdue chores up to 14 days back. So the badge can say 2 while the dashboard card shows no Ämtli. `/tasks` is not used by any view (dead API surface).
- **Fix:** Use one service (e.g. `attention.due_items` plus a horizon) for the dashboard and `/tasks`. Show overdue chores on the dashboard. Remove `/tasks` or document it.

### F11 — Push delivery is at-most-once: a missed due day or a send error loses the notification
- **Severity:** Low · **Class:** D (intentional; documented in code comments at `push_service.py:44-46, 348`) · **Confidence:** High
- `_claim` commits before the send (`push_service.py:190-199`). A chore push is sent only when `due_date == local today` (verified: due 11-01, first run 11-02 → 0 sent). A todo reminder older than 12 hours is dropped (`STALE_AFTER`). Pet, plant and document overdue items are still sent late. Reminder kinds therefore behave differently after downtime. Acceptable; document it in PROJECT-STATUS §8.

### F12 — Concurrent schedule PATCH and materialisation can lose an update to `next_rotation_index`
- **Severity:** Low · **Class:** E · **Confidence:** Low (unverified, reasoned)
- `update_chore` loads the chore with `db.get` without a lock (`chores.py:270`), computes `next_rotation_index - deleted` from that stale value (`:318`), and writes it as an absolute value. A materialisation that commits in between (holding `FOR UPDATE`) is overwritten. Fix: `db.get(Chore, id, with_for_update=True)` in PATCH.

### F13 — The Putzplan uses the device date for "today/overdue" while the server uses the household time zone
- **Severity:** Low · **Class:** F · `ChoresView.vue:50-66, 103-123` (`todayStr()` from `new Date()`). Only differs for travelling users.

### F14 — Reminder `remind_at` without an offset is treated as UTC, while events treat it as household wall time
- **Severity:** Low · **Class:** F · `todos.py:34-44` versus `event_times.py:20-24`. The current frontend always sends `toISOString()` (`TodoList.vue:136`), so this is not reachable from the UI. Evidence: `naive 02:30 on DST day -> 201 2027-03-28T02:30:00Z`.

### F15 — Reminders can be added to a todo that is already done; they are silently claimed and never sent
- **Severity:** Low · **Class:** F · `todos.py:340-382` has no `is_done` check. Harmless but confusing; return 422 or allow it only after reopening.

### Verified correct (no finding)
- Concurrent materialisation (12 parallel requests, plus 4 scheduler threads during 6 API calls) on PG: no duplicates, no 500s, rotation index exact, all clients see the same set (`pg_concurrency.py`).
- Multi-worker push dedupe for all 5 kinds: 6 parallel `run_once` equivalents → exactly 1 send per item (`pg_push.py`: `Counter({'todo':1,'pet':1,'plant':1,'chore':1,'document':1})`).
- Date math: incremental windows equal a one-shot window; spacing is 7, 14 or 1 month; day 29/31 clamping including leap years; year boundary; biweekly parity across the new year (`prop_scheduler.py`).
- Renaming with the full UI payload does not touch assignments (existing test plus code at `chores.py:290-293`).
- Reassigning after the push resets `notified_at` and notifies the new assignee (`pg_schedule.py` §8).
- Deleting a todo cascades its reminders (count 0). Todo claim race: 1 winner.
- DST: morning hour 08:00 is local on both DST days.

## 4. Prior review status

| Item | Status now |
|---|---|
| L-04 (dashboard overdue at 00:00 UTC) | **Fixed, verified** (Zurich, including 00:30 local). Remains for devices west of UTC (F7) |
| L-05 (edit chore with an ex-member in the rotation) | Fixed (code `chores.py:283-285`, test `test_rename_chore_with_departed_member_in_rotation`) |
| L-09 (rotation give-back miscounts with skipped ex-members) | Still in the code, but **practically unreachable**. PATCH deletes only open assignments with `today < due_date`, and materialisation never goes beyond `today+7`. The minimum period is 7 days, so at most 1 assignment is deleted. That assignment was the last one created, so `index-1` points exactly at its assignee (any skipped ex-members come before it). Verified in `pg_schedule.py` §6 with [A, X(ex), B]: the deleted Wednesday goes back to B, which is correct. Would become real if the horizon grew beyond 7 days. Suggest downgrading it to a comment |
| L-10 / E-3 (paused chore stays visible) | **Open**, and worse than described: it also triggers push and badge (F3), and reactivation produces a backfill burst (F4) |
| L-15 / E-6 (ex-member stays assignee) | **Open**; consequences confirmed (F6) |
| L-16 (UI can only reorder the rotation) | **Open** (`ChoresView.vue:580-600`, only ↑/↓ buttons; a new chore pre-fills all current members at :187) |
| L-18 (claim → 409 even if already mine) | As documented; PG race verified |
| E-7 (clean up the rotation on leave) | Open; F6 suggests doing it in the same transaction as E-6 (b) |
| Logic-review §6 "Todo wieder öffnen → Erinnerungen bleiben verschickt: ok" | **Incorrect assessment**; see F2 |
| Logic-review §2 "Erledigte zukünftige Zuweisung blockiert Neuplanung" | Still present (F8) |

## 5. Cross-module effects

| Source operation | Dependent entities | What can become inconsistent |
|---|---|---|
| Chore PATCH (weekday / day_of_month) | ChoreAssignment, rotation index, badge, widget | A past overdue assignment appears and the rotation skips a person (F1) |
| Chore PATCH active=false | Open assignments, push scheduler, attention, `/tasks`, dashboard | Pushes and badge counts continue for up to 7 days (F3) |
| Chore PATCH active=true | Materialisation | Backfill burst of overdue items (F4) |
| Member leave/remove (`households.py:160ff`, `:224ff`) | ChoreAssignment.assigned_user_id, Todo.assigned_to_user_id, rotation_order, widget token | Push goes to everyone while the badge counts nobody; the UI shows "Unbekannt" (F6) |
| Todo done → undo/reopen | TodoReminder.notified_at, dashboard "upcoming reminders", TodoList bell | Reminder is lost but still displayed (F2) |
| Todo create/patch with a foreign assignee | attention, push recipients, "Meine" filter | The todo is invisible in everyone's personal views (F5) |
| Scheduler materialisation at 08:00, `/tasks` | Socket clients | No `chore_assignment_created` events (F9) |
| Tag action `chore.assignment.done` (`tag_actions.py:509-547`) | Calls `list_assignments`, so F1/F4 assignments can become "current" | A scan may tick off the retroactive overdue assignment from F1 instead of the real one (reasoned, not run) |

## 6. Test gaps

| Scenario | Recommended type |
|---|---|
| Schedule edit with a gap between the last assignment and the new anchor (F1), weekly and monthly | API (SQLite fine) + property test "no open assignment before anchor after edit" |
| Done → undo → reminder still fires (F2) | API + scheduler unit; frontend: bell hidden when `notified_at` is set |
| Paused chore: no push, no badge (F3) | Scheduler unit |
| Reactivate after a pause (F4) | API |
| Todo assignee validation (F5) | API |
| Concurrent GET /assignments, /tasks and scheduler on PG (currently only SQLite with a shared session) | PG integration |
| Multi-worker scheduler dedupe | PG integration |
| Badge vs dashboard vs widget for the same data (ex-member, paused, overdue chore) | API consistency test |
| Concurrent schedule PATCH vs materialisation (F12) | PG integration |
| Hypothesis on `next_due_dates` (the window-split invariant) | Property-based (port `prop_scheduler.py` into the suite) |

## 7. Product decisions

| Question | Options | Recommendation |
|---|---|---|
| Pausing a chore (E-3) | a) keep open future assignments (today) · b) hide them while paused · c) delete open assignments with `due_date ≥ today` and give back the index | **c**. It also stops push and badge (F3) and makes reactivation clean (with F4's re-anchor) |
| Reactivation start point | a) backfill 14 days (today) · b) start from the next due date ≥ today | **b** |
| Departed member's open duties (E-6/E-7) | a) leave them (today) · b) set them to NULL ("open for all") and remove the member from `rotation_order` | **b**. Push, badge and UI then agree |
| Missed push after downtime | a) drop it (today; chores same-day only, todos 12 h) · b) send late with a "überfällig" title | a, but document it in PROJECT-STATUS §8 |
| Dashboard chores section | a) today only (today) · b) today + overdue (same as the badge) | **b** |
| `/tasks` endpoint | a) keep it unused · b) remove it · c) make the frontend use it with the attention rules | b, or c if a combined list is planned |

## 8. Unverified

- F12 (lost update in PATCH vs. materialise): needs a precise interleaving; reasoned only.
- Tag-scan interaction with F1/F4 assignments: reasoned from `tag_actions.py:509-547`, not executed.
- Real Web Push delivery and the service worker applying `badge`: mocked (`send_to_users` patched).
- Frontend behaviour of `<input type="date">` showing an ISO datetime when editing (`TodoList.vue:240`): the browser drops the invalid value, so the field appears empty. The ref keeps the ISO string, so saving does not clear the due date. Not executed in a browser.
- Real uvicorn multi-process deployment: the Dockerfile runs `--workers 1`. Dedupe was verified with threads and separate DB sessions, which exercise the same conditional-UPDATE path.
- The frontend vitest suite was not run for this area; no new frontend tests were written (scratchpad-only rule).
