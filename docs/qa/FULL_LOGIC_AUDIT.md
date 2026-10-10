# Casa – Comprehensive Production Logic Audit

**Date:** 2026-10-10 · **Code state:** `e053c71` (= `origin/master` after PR #33), branch `claude/adoring-goldberg-3zhyfm`
**Scope:** business logic, user logic, domain consistency and cross-module behaviour of the whole application
(backend, frontend, schedulers, tags, AI, operations). No application code was changed.

Companion documents:
[BUSINESS_RULES_MATRIX.md](BUSINESS_RULES_MATRIX.md) ·
[CROSS_MODULE_DEPENDENCIES.md](CROSS_MODULE_DEPENDENCIES.md) ·
[USER_JOURNEY_AUDIT.md](USER_JOURNEY_AUDIT.md) ·
[TEST_GAP_MATRIX.md](TEST_GAP_MATRIX.md) ·
[PRODUCT_DECISIONS.md](PRODUCT_DECISIONS.md) ·
[REMEDIATION_ROADMAP.md](REMEDIATION_ROADMAP.md) ·
reproduction scripts and raw outputs: [audit-evidence/](audit-evidence/README.md) ·
**fix status after the audit: [REMEDIATION_STATUS.md](REMEDIATION_STATUS.md)**

---

## 0. Method and evidence standard

| Step | What was done |
|---|---|
| Baseline | Full suites run on this checkout: **backend 837 passed** (62 files, coverage 94 %), **frontend 473 passed** (33 files, statements 77.49 %, branches 72.14 %), `vue-tsc` typecheck, locale check (1173 keys, in sync), `ruff` clean. These match the numbers in `docs/PROJECT-STATUS.md` and `docs/qa/current-audit-fixes.md`. |
| Real database | A local **PostgreSQL 16** was created and migrated with the real Alembic chain (`alembic upgrade head`, single head `a3b4c5d6e7f8`). All concurrency, locking and constraint claims below were reproduced on PostgreSQL with one session per request (`audit-evidence/pgharness.py`). The repository's own test suite uses SQLite in-memory with **one shared session for all requests**, so it cannot observe these behaviours. |
| Property-based tests | Hypothesis tests against the real `split_evenly`, `validate_custom_shares`, `compute_settlements` and the chore scheduler date functions; 300 random REST operation sequences against the finance API on PostgreSQL. |
| Frontend | Store-level race tests (late responses, logout, partial socket payloads, rollbacks) against the real Pinia stores with mocked repositories, run from scratch configs outside `src/`. No real browser or device run in this audit. |
| Journeys | Multi-step, multi-user scenarios executed end-to-end through the API (see USER_JOURNEY_AUDIT.md). |
| Prior work | Every item of `docs/qa/logic-review.md` (L-01…L-18, E-1…E-10) and `docs/qa/current-audit-fixes.md` was re-checked against current code. |

Severity scale: **Critical** – silent corruption of financial or safety-relevant records in a realistic path;
**High** – broken essential workflow, data loss, or false records through normal use;
**Medium** – wrong or confusing state requiring coincidence, concurrency or a less common path, or significant UX/product risk;
**Low** – edge cases, robustness, cosmetics with a functional impact.
Classification letters follow the brief: **A** confirmed defect · **B** missing enforcement of an established rule ·
**C** ambiguous product decision · **D** intentional documented limitation · **E** architectural risk ·
**F** UX improvement · **G** planned, not implemented.

---

## 1. Executive summary

**Answer to the audit question.** For a *single* user working *sequentially*, Casa behaves consistently and
logically: the split arithmetic is exact, settlement suggestions are mathematically valid, recurring bills
are booked once per household month, timezone handling of the household's calendar dates is correct,
reminder dispatch is exactly-once across workers, tenant isolation holds on all 139 household routes, and the
prior logic review's fixes (L-01…L-08) are still in place.

It does **not** yet behave as one consistent interconnected system under *concurrent* use and *changing
household circumstances*. The gaps cluster in five themes:

1. **Financial records are not protected as records.** Two concurrent edits of one expense can leave shares
   summing to twice the amount, and both users are told it succeeded (CASA-01, reproduced 9/10 on PostgreSQL).
   Settled history can be edited or deleted by any member without trace, including in ways that create claims
   for former members who can no longer see the household (CASA-02). The Undo of an expense deletion can
   double-book a recurring bill (CASA-03). The same payment recorded by both parties flips the debt (CASA-08).
2. **Idempotency is incomplete at the physical-action boundary.** A repeated or double NFC read of a chore tag
   completes older assignments (CASA-05). A tag executes against whatever is current at execute time, not what
   the user confirmed (CASA-18). "Feed all" racing with a single feeding leaves pets unfed while telling the
   user "all already fed" (CASA-13).
3. **State transitions lose information.** Undoing a completed todo silently disables its future reminders
   while the UI still shows them (CASA-06). Changing a chore schedule creates an already-overdue duty and
   skips someone's turn (CASA-16). Pausing a chore does not stop its push notifications (CASA-17).
4. **The frontend is not isolated per household/user session.** Late responses from the previous household
   overwrite 12 stores after a switch, and logout does not clear stores before the next user logs in on the
   same device (CASA-12).
5. **Robustness and operations.** One malformed PATCH can make the shared calendar or the recipe list return
   HTTP 500 for the whole household until repaired via API (CASA-04). The documented rollback restore leaves
   the database half-restored and blocks the next start (CASA-07). Many check-then-act operations surface as
   HTTP 500 or as invariant violations under ordinary concurrency (CASA-10, CASA-20, CASA-24). None of this is
   detectable by the current CI (CASA-25).

**Counts.** 60 findings: **1 Critical, 6 High, 18 Medium, 35 Low.** 13 of the 18 open items from the prior
logic review are unchanged; 3 prior "ok" assessments are now known to be wrong (chore tag, todo reopen,
concurrent refresh), and 2 prior "ok" assessments hold only sequentially (last-admin/last-member leave,
calendar-delete guard).

**Production readiness verdict:** *Conditionally usable for a small, mostly-sequential household; not ready to
be relied upon as a shared financial ledger or as a medication/feeding record without the P0 items in
REMEDIATION_ROADMAP.md.* P0 consists of 7 changes, most of them Small (row locks, a version column, an idempotency
key, a null-validation rule, a restore-script fix). Nothing was found that exposes one household's data to
another household's members.

### 1.1 Top findings

| ID | Sev | Class | Finding | Verified |
|---|---|---|---|---|
| CASA-01 | Critical | A | Concurrent expense edits duplicate shares; balances no longer sum to zero; both users get 200 | PG 9/10 rounds (lead + finance agent) |
| CASA-02 | High | C/E | Settled history silently editable/deletable by any member; may create claims toward ex-members | PG journey J1 |
| CASA-03 | High | A | Expense delete + Undo loses the bill link → bill booked twice in one month; ex-member expenses cannot be restored | PG |
| CASA-04 | High | A | `PATCH … null` persists JSON `null` → calendar range / recipe list return 500 for the whole household | PG (lead) |
| CASA-05 | High | A | Chore NFC tag: each repeated or parallel scan completes one more (older) assignment, reports success | PG + code |
| CASA-06 | High | A | Todo done → Undo silently cancels all future reminders; UI still shows the bell | PG + code |
| CASA-07 | High | A | Documented rollback restore (`restore-db.ps1`) leaves a mixed DB and a crash-looping backend | PG with identical `pg_restore` flags |

### 1.2 Verified correct (selected)

- Split and rounding: `sum(shares) == amount`, fairness within 1 Rappen, deterministic, duplicates rejected
  (hypothesis, 3000 examples each); 300 random sequential REST sequences kept all ledger invariants.
- Settlement suggestions zero all balances with ≤ n−1 transfers (n up to 5000); greedy is not minimal (documented).
- Recurring bill booking: exactly one booking per bill and household month under 8-way concurrency.
- Month/year boundaries (31.12→1.1, 29.2) for finance summary, budget, dashboard and chore schedules; 08:00
  local reminder hour correct on both DST days of 2026.
- Push reminders are claimed exactly once even with multiple scheduler processes; recipients are always
  filtered by current membership.
- All 139 household-scoped routes require membership (8 admin, 131 member); a removed member's still-valid
  access token gets 403 on REST, file downloads and tag scans.
- Service worker caches only the app shell (no `/api` runtime caching) – no authenticated data survives logout.
- Poll decision is exactly-once under concurrency; one vote per person per poll holds under concurrent changes.
- Migrated PostgreSQL schema has no structural drift from the SQLAlchemy models.

---

## 2. Feature inventory and module classification

Branch check: GitHub `master` equals the audited HEAD `e053c71`; every feature branch named in
`PROJECT-STATUS.md` (#20–#33: plants, AI, tags, refresh cookie, invite expiry, widget, logic review, audit
fixes) is merged. (The local `master` ref in this container is stale; that is not a missing merge.)

| Module | Classification | Notes |
|---|---|---|
| Auth (register, login, refresh rotation, logout, `/me`) | Implemented and verified | Concurrency defect in refresh (CASA-11) |
| Households, membership, roles, invite codes | Implemented and verified (sequential) | Not race-safe (CASA-10); no admin repair path |
| Household switch (frontend) | Partially implemented | Reset exists; in-flight responses and logout not isolated (CASA-12) |
| Shopping lists/items, stores, client IDs, versions | Implemented and verified | Lost update via edit sheet (CASA-09); delete-then-retry resurrection is a documented limitation (D) |
| Todos, claim, reminders | Implemented and verified | CASA-06, CASA-21 |
| Unified tasks `GET /tasks` | **Implemented but unused** | No view calls it; its classification differs from dashboard/badge (CASA-43) |
| Chores & rotation | Implemented and verified (scheduler maths) | Schedule edit/pause/reactivate defects (CASA-16, CASA-17) |
| Expenses, balances, settlements | Implemented and verified (sequential) | CASA-01/02/03/08/09/23 |
| Budgets, finance summary | Implemented and verified | Socket handler edge cases (CASA-42) |
| Recurring bills (API, booking) | Implemented and verified | **No management UI**, although `PROJECT-STATUS.md:306` claims one → *documentation inconsistent* |
| Calendars, events | Implemented and verified | CASA-04, CASA-20, CASA-35; **no event reminders** (neither implemented nor planned → product decision) |
| Polls (event, meal) | Implemented and verified | CASA-19 |
| Recipes, meal plan | Implemented (API); **UI recipe CRUD planned** | Epic 15 text claims recipe CRUD in FoodView → *documentation inconsistent* |
| Pets, feeding, medication, pet care | Implemented and verified | CASA-13/14/15 |
| Plants, care tasks, care log, water-all | Implemented and verified | CASA-29 |
| Documents & files (multi-page, quota, cleanup) | Implemented and verified (sequential) | Concurrency Lows (CASA-26/27/28) |
| NFC/QR tags (7 actions) | Implemented and verified for side-effect parity | CASA-05, CASA-18, CASA-31 |
| AI assistant (recipe, plant care; opt-in, quota) | Implemented; verified with mocked provider only | Never called against the real API (documented, `PROJECT-STATUS.md` §8) |
| Web Push, app badge | Implemented; verified server-side | No real device delivery tested |
| Widget (Scriptable) | Implemented and verified | CASA-22 (key revival) |
| Offline M0 (client IDs, versions on 4 entities) | Implemented and verified | M1+ (IndexedDB, outbox) planned (G) |
| "Log out everywhere", password change, account deletion | Planned / not present (G) | Account deletion would hit inconsistent FK rules (CASA-55) |
| Backups/restore scripts | Implemented; restore defective for rollback (CASA-07) | |

---

## 3. Findings – Critical and High

### CASA-01 · Concurrent expense edits corrupt the ledger (shares duplicated)
- **Severity:** Critical · **Class:** A · **Modules:** Finance (expenses, balances, dashboard saldo, settlement suggestions)
- **Refs:** `backend/app/routers/expenses.py:355` (`db.get` without lock), `:447-458` (`expense.shares.clear(); db.flush()` then insert); `models.py` `Expense` (no `version`)
- **Observed:** Two PATCH requests on the same expense with different `participant_ids` (`[A,B]` and `[C,D]`), sent concurrently: both return **200**; the expense (amount 1000) ends with **4 shares of 500 (sum 2000)**. `GET /balances` then sums to −9000 over 10 expenses with `unassigned_rappen = 0`. Overlapping participant sets or an amount change instead produce an unhandled `IntegrityError uq_expense_share_user` → **HTTP 500**; DELETE ‖ PATCH produces `DeadlockDetected`/`StaleDataError` → 500.
- **Expected:** `sum(shares) == amount` at every commit; one of two conflicting edits gets 409.
- **Reproduction:** household with 4 members; create an even expense of 10.00; send two PATCHes concurrently with disjoint `participant_ids`.
- **Evidence:** `audit-evidence/journeys/v2_shares.py` → `rounds (codes, n_shares, sum): [((200,200),2,1000), ((200,200),4,2000) ×9]`, `invariant violations: 9/10; sum saldi: -9000 unassigned: 0`. Independently: `finance/pg_conc_detail.py` (9/10), `journeys/j3_expense_concurrent_patch.py` (37/40 → 500 for amount‖participants).
- **Root cause:** each transaction deletes the share rows *it loaded*; the second delete matches 0 rows (SQLAlchemy only warns: `expected to delete 3 row(s); 0 were matched`) and both transactions insert their own shares. No row lock, no version, no DB-level check of the invariant.
- **Business impact:** silent, persistent wrong debts for every participant; the dashboard saldo and settlement suggestions are wrong; nobody is informed. Realistic triggers: the same person saving from phone and laptop, two partners correcting the same receipt, a client retry while the first request is still running.
- **Recommended solution:** lock the expense row at the start of PATCH/DELETE (`with_for_update()`); add `version` (SyncVersionMixin) and an `If-Match`/409 precondition; map `IntegrityError`/`OperationalError` to 409; optionally a deferred constraint trigger asserting Σshares = amount at commit.
- **Regression test:** PG integration, `H.parallel` PATCH‖PATCH (participants, amount) and DELETE‖PATCH; assert Σshares = amount and status ∈ {200, 404, 409}.
- **Confidence:** High.

### CASA-02 · Settled financial history can be rewritten by any member, silently
- **Severity:** High · **Class:** C/E (no rule exists; consequences are severe) · **Modules:** Finance, Households (ex-members), Recurring bills
- **Refs:** `expenses.py:347-495`, `settlements.py:126-147` (only `verify_household_access`); `Expense` has no creator/editor column; hard deletes; `recurring_bills.py:239-248` (rebook allowed after delete)
- **Observed (journey J1):** Anna, Ben, Carla; rent 3000.00 booked (Anna pays), groceries 100.00 (Ben pays); Carla leaves; all suggested settlements are recorded → all balances 0. Ben then deletes Anna's settled rent expense (204). Balances invert: Anna −2000.00; **Carla (ex-member, gets 403 on every endpoint) becomes a creditor of 1000.00**. The bill can be booked again for the same month (201) and is now split between the two current members only, leaving Carla owed 1000.00 for rent she actually paid. No warning, no history, no notification.
- **Expected:** a settled period is either immutable, or changes are explicit (warning, attribution, visible history) and do not silently create claims for people who cannot see them.
- **Reproduction:** `audit-evidence/journeys/j1_finance_leave.py` (output `j1.out`).
- **Root cause:** no ownership or audit model on financial records; settlements are not linked to the expenses they settle; the bill "booked" state is derived from the existence of an expense.
- **Business impact:** loss of trust in the ledger; disputes cannot be resolved because nothing records who changed what. One member can erase a debt they owe (finance scenario 1: debtor deletes creditor's expense → both balances 0).
- **Recommended solution:** product decision PD-F1/PD-F2 (PRODUCT_DECISIONS.md). Minimum: `created_by/updated_by/deleted_by`, soft delete with visible history, warning "Salden ändern sich nachträglich" when touching expenses dated before the last settlement involving the same people.
- **Regression test:** API journey test: settle → delete → assert warning/audit entry; ex-member balance changes are visible to remaining members.
- **Confidence:** High.

### CASA-03 · Expense delete + Undo double-books a recurring bill; ex-member expenses cannot be restored
- **Severity:** High · **Class:** A · **Modules:** Finance UI, Recurring bills, Balances
- **Refs:** `frontend/src/views/ExpensesView.vue:201-223` (Undo = `addExpense` without `recurring_bill_id`/`booked_month`), `recurring_bills.py:239-248`
- **Observed:** Delete the booked "Miete" expense, tap **Rückgängig** → re-created with `recurring_bill_id = null`; the finance summary shows the bill as not booked; booking it again succeeds → **two rent expenses in the same month**, rent counted twice in balances and budget. Deleting an expense paid by an ex-member and tapping Undo → **422 USERS_NOT_IN_HOUSEHOLD**, the ex-member's claim is permanently gone.
- **Expected:** Undo restores exactly the deleted record (including bill link and ex-member participants) or is not offered.
- **Reproduction / evidence:** `frontend_realtime_ux/pg_undo_bill.py` → `undo re-create 201 recurring_bill_id: None`, `book again 201`, `expenses 'Miete' this month: 2`; `finance/pg_scenarios.py` scenarios 8b and 10.
- **Root cause:** Undo is implemented as a fresh create through the public API, which cannot carry server-owned fields and re-validates membership.
- **Business impact:** double charges after a common recovery action; irreversible loss of an ex-member's claim.
- **Recommended solution:** server-side soft delete with a restore endpoint (or delayed hard delete after the undo window); short term: no Undo for expenses with `recurring_bill_id` or ex-member participants (confirm dialog instead).
- **Regression test:** PG/API: delete booked expense → restore → bill still booked, booking again → 409; ex-member expense restore → 200.
- **Confidence:** High. (The prior UX review F-9 noted the lost link; the double-booking consequence was undocumented.)

### CASA-04 · Explicit `null` in a PATCH persists JSON `null` and breaks a module for the whole household
- **Severity:** High · **Class:** A · **Modules:** Calendar, Recipes/Meal plan (same pattern risk on every JSON NOT NULL column)
- **Refs:** `events.py:250-252` (`if … is not None:` skips conversion, `setattr` stores `None`), `food.py:76` (`ingredients: list[str] | None`, validator does not coerce `None`), `models.py` JSON columns without `none_as_null`
- **Observed:** `PATCH /events/{id} {"participant_ids": null}` → 500, **but the value is committed**; afterwards `GET /events?from_date=…` for any range containing the event returns **500 for every member**. `PATCH /recipes/{id} {"ingredients": null}` → 500, committed; afterwards `GET /recipes` and `GET /meal-plan` return 500 for everyone (the Food page is unusable).
- **Expected:** 422 for `null` on non-nullable fields; the row is unchanged.
- **Reproduction / evidence:** `journeys/v1_nulls.py` → `PATCH participants null: 500`, `GET events range: 500`, `PATCH recipe ingredients null: 500`, `GET recipes: 500 (Ben): 500`; `shopping_food_calendar/t_cal.out` C5, `t_food3.out`.
- **Root cause:** SQLAlchemy `JSON` stores Python `None` as JSON literal `null`, which satisfies `NOT NULL`; the commit happens before response validation fails.
- **Business impact:** one malformed request (API client, buggy build, future offline replay) takes down a shared module with no in-app recovery. Not reachable from the current UI.
- **Recommended solution:** generic validator on all `*Update` schemas rejecting explicit `null` for non-nullable fields; `JSON(none_as_null=True)` for NOT NULL JSON columns; coerce `ingredients=None → []` like `steps`/`tags`.
- **Regression test:** parametrised API test: every non-nullable PATCH field with `null` → 422, row unchanged, list endpoints 200.
- **Confidence:** High.

### CASA-05 · Chore NFC tag completes the backlog on repeated or parallel scans
- **Severity:** High · **Class:** A · **Modules:** Tags, Chores, Dashboard/badge, rotation statistics
- **Refs:** `backend/app/services/tag_actions.py:536-549`
- **Observed:** each execute picks "the latest *open* assignment with `due_date ≤ today`". After today's is done, the next scan completes last week's open assignment, then the one before: sequential scans completed 2026-10-10, 2026-10-03, 2026-09-26, each `changed: true` with the success message. Two parallel scans completed two assignments. If nothing is due, a scan can complete next period's assignment up to 6 days early.
- **Expected:** a scan completes only the current period; once done, further scans report "already done". (The module's own docstring states "Ältere offene Zuweisungen bleiben unangetastet"; `logic-review.md` §9 rated this "ok".)
- **Evidence:** `tags_ai/pg_tags.py` T1/T2; code quoted above.
- **Root cause:** "current" is recomputed from what is still open, with no notion of "this period is already done".
- **Business impact:** NFC readers commonly fire twice; a retry after a network error is natural. Other members' missed duties disappear as "done by" the scanner, falsifying who did what and hiding overdue work.
- **Recommended solution:** current period = latest assignment with `due_date ≤ today` regardless of completion (else the next within 6 days); if completed → `changed=false`/`ALREADY_DONE`; plus target pinning (CASA-18).
- **Regression test:** PG: two open past assignments, execute twice → second `changed=false`, backlog untouched; parallel variant.
- **Confidence:** High.

### CASA-06 · Todo "done" followed by Undo/reopen silently cancels all future reminders
- **Severity:** High · **Class:** A · **Modules:** Todos, reminders, push scheduler, dashboard "upcoming reminders", TodoList UI
- **Refs:** `backend/app/routers/todos.py:249-256` (done sets `notified_at` on all open reminders; `else` branch only resets `done_at`), `frontend/src/components/TodoList.vue:118-122` (`getNextReminder` ignores `notified_at`)
- **Observed:** a todo with a reminder 5 h ahead is marked done and undone within a second (the "Rückgängig" toast). The reminder keeps `notified_at`; it is never sent; the dashboard no longer lists it; **the todo list still shows the bell with the future time**.
- **Expected:** reopening restores pending reminders whose time has not passed.
- **Evidence:** `chores_tasks_time/pg_todos.py`: `after done+reopen: future reminder notified_at = 2026-10-10T07:00:24Z`, `push at reminder time after reopen: []`.
- **Root cause:** `notified_at` is overloaded as "cancelled"; the reverse transition was never implemented (`logic-review.md` §6 assumed all reminders would be in the past).
- **Business impact:** a reminder the user explicitly set never fires while the app claims it will — after the recommended recovery action for an accidental tick.
- **Recommended solution:** simplest: stop marking reminders on completion (the scheduler already skips done todos, `push_service.py:221`); alternatively reset `notified_at=None` for `remind_at > now` on reopen. Frontend: hide the bell when `notified_at` is set.
- **Regression test:** API + scheduler: future reminder, done → undo, run scheduler at `remind_at+1min` → 1 push.
- **Confidence:** High.

### CASA-07 · The documented rollback restore corrupts the database and blocks the next start
- **Severity:** High · **Class:** A (operations procedure) · **Modules:** `scripts/restore-db.ps1:139`, `docs/deployment.md:210-216`, Alembic
- **Observed:** restoring a pre-update dump with `pg_restore --clean --if-exists` onto a schema migrated past it: tables added by the update (e.g. `widget_tokens`) keep FKs to `users`/`households`, so these cannot be dropped; their **current** rows survive and the backup rows fail with duplicate keys, while every other table returns to the backup state and `alembic_version` drops to the old revision. The script reports exit code 1 only as a yellow "probably warnings". The next `alembic upgrade head` (container start) fails with `DuplicateTable` → backend restart loop.
- **Expected:** the database equals the dump exactly, or the restore aborts loudly.
- **Evidence:** `infra_data_tests/restore_rollback.sh` (same flags; the PowerShell wrapper itself was not executed): `cannot drop table public.users because other objects depend on it`, `COPY failed for table "users": duplicate key`, `errors ignored on restore: 10`, then `DuplicateTable: relation "widget_tokens" already exists`.
- **Root cause:** `--clean` with a partially overlapping schema; no `--single-transaction --exit-on-error`; backend not stopped; DB not recreated.
- **Business impact:** in an emergency rollback the household gets a mixed database (users/households from "now", memberships/expenses from "then") without a clear error, followed by an outage.
- **Recommended solution:** stop the backend; drop and recreate the schema (or database); `pg_restore --single-transaction --exit-on-error`; treat non-zero exit as failure; document that a rollback requires the matching old code version.
- **Regression test:** scripted ops test: migrate N-1 → seed → dump → upgrade head → restore → row equality and successful `alembic upgrade head`.
- **Confidence:** High.

---

## 4. Findings – Medium

### CASA-08 · The same payment recorded twice flips the debt; implausible settlements accepted
- **Severity:** Medium · **Class:** B/C · **Modules:** Settlements, Balances · **Refs:** `settlements.py:76-122`; `BalanceSummary.vue:73-103` (guard per dialog instance only)
- **Observed:** debtor and creditor both press "Ausgleichen" for the same suggestion: 201, 201 → the debt flips (Anna −25.00, Ben +25.00) and a new reverse suggestion appears; 15/15 parallel rounds created two rows. Overpayment (debt 5.00, recorded 999.99) and settlements against the debt direction are accepted.
- **Expected:** a retry or a second recording of the same payment is detected (idempotency key; warning on duplicates or amounts above the current debt).
- **Evidence:** `finance/pg_scenarios.py` (scenarios 3, 3b, 4), `finance/pg_concurrency.py` a).
- **Impact:** a very likely real-world flow ("I entered it" – "me too") creates a reversed debt. **Fix:** client-generated id via `services/client_ids.py`; plausibility warning; show "erfasst von X". **Test:** two identical POSTs → second 409/flagged. **Confidence:** High.

### CASA-09 · Lost updates: edit dialogs send full snapshots of unversioned (or unchecked) entities
- **Severity:** Medium · **Class:** E/A · **Modules:** Expenses, Notes, Shopping edit sheet, Todos
- **Refs:** `ExpenseFormDialog.vue:221-231`, `NotesView.vue:122-137`, `ShoppingItemEditSheet.vue:66-75`, `TodoList.vue:271-276`; no `version` on expenses/notes; shopping has `version` but the server ignores it in PATCH
- **Observed:** Ben corrects an expense 100.00 → 250.00; Anna then saves a description edit from a dialog opened earlier → amount silently back to 100.00. Same for a note body and a shopping item's quantity.
- **Expected:** either only changed fields are sent, or a stale write is rejected (409, "inzwischen von X geändert").
- **Evidence:** `finance/pg_scenarios.py` scenario 5; `frontend_realtime_ux/pg_realtime.out` P2/P3; shopping by code reading.
- **Impact:** a partner's correction vanishes without notice, including money amounts. `logic-review.md` §5 ("both edits survive") holds only for the raw API. **Fix:** send diffs (cheap) and add `version`/`If-Match` for expenses. **Test:** stale full PATCH → 409; dialog diff unit test. **Confidence:** High.

### CASA-10 · Membership races: household without admin, orphan household joinable by code, successful join undone
- **Severity:** Medium · **Class:** A · **Modules:** Households, all household data, file storage · **Refs:** `households.py:176-211` (count and promotion without lock), `:482-550`
- **Observed (PostgreSQL):** (a) admin and the most senior member leave concurrently → remaining member is a plain member (6–8/15 runs) or 500 `StaleDataError`; **no endpoint can promote anyone**. (b) last two members leave concurrently → household with 0 members survives (5–11 of 15–40 runs) with all data and files; anyone holding the still-valid invite code can join and **sees all previous data**. (c) join ‖ last-member leave → join returns 200 but the membership is cascaded away (13/15).
- **Expected:** invariants "≥1 admin if ≥1 member", "≥1 member or deleted", "200 join ⇒ member".
- **Evidence:** `households/races.py`, `households/orphan_join.py` (`outsider sees old data: 200 ['geheime Notiz von A']`), `infra_data_tests/leave_race.py`.
- **Impact:** rare (near-simultaneous actions) but unrecoverable without DB access; privacy exposure of an abandoned household's data to a later code holder. **Fix:** `SELECT … FROM households WHERE id=… FOR UPDATE` at the start of join/leave/remove; re-count after delete; auto-promote when no admin exists; periodic cleanup of 0-member households. **Test:** PG race tests for each pair. **Confidence:** High.

### CASA-11 · Concurrent token refresh triggers reuse detection and logs the user out everywhere
- **Severity:** Medium · **Class:** A · **Modules:** Auth, Socket.IO, multi-tab/PWA · **Refs:** `auth.py:200-216` (`_create_token_pair` commits), `:407-413` (`replaced_by_id` set after), `:356-398`
- **Observed:** two requests with the same refresh cookie at nearly the same time: in 9/40 (0 ms) and 7/40 (≤20 ms jitter) pairs the second sees "revoked without replacement" and runs reuse detection → **all refresh tokens revoked, all sockets disconnected**. A third use within the 30 s grace window always triggers it. Without a lock, pairs also fork into two active chains.
- **Expected:** benign duplicates never log out (`logic-review.md` §11 promises "beide bekommen gültige Tokens").
- **Evidence:** `households/refresh_race.py`, `households/grace_three.py`.
- **Impact:** sporadic forced logout on all devices (tabs waking together, PWA + tab), hard to diagnose. **Fix:** lock the old token row; set `revoked_at`, `replaced_by_id` and insert the successor in one commit; follow the replacement chain in the grace path. **Test:** PG 2- and 3-way concurrent refresh → no `REFRESH_TOKEN_REUSED`, one active token. **Confidence:** High (frequency in production unknown).

### CASA-12 · Frontend state is not isolated per household or per user session
- **Severity:** Medium · **Class:** A · **Modules:** 12 Pinia stores, `App.vue`, `auth.ts`
- **Refs:** unguarded `x.value = await …` in `shopping.ts`, `todos.ts`, `expenses.ts`, `settlements.ts`, `chores.ts`, `finance.ts`, `dashboard.ts`, `polls.ts`, `calendar.ts`, `notes.ts`, `food.ts` (recipes), `tasks.ts`; guarded only in `pets.ts`, `plants.ts`, `documents.ts`; `auth.ts:287-296` (`_clearState` resets no stores); `App.vue:180` (reset only when `oldHouseholdId` is truthy)
- **Observed:** (a) a response for household A that arrives after the switch to B overwrites B's store — A's shopping items, A's balances and A's `activeListId` shown under B (adding an item then fails 400). (b) After logout and login of another user in the same tab, the previous user's dashboard saldo, shopping list, expenses and notes remain visible until (or, offline, instead of) the new user's data. (c) Leaving the last household and creating/joining a new one does not reset stores.
- **Expected:** only data of the current household and user is ever displayed.
- **Evidence:** `households/staleSwitch.test.ts` (`TODOS after switch: ["hh-A:A-Todo"]`), `frontend_realtime_ux/races.test.ts` R1–R3.
- **Impact:** wrong money figures shown for a household; privacy issue on shared family devices. Not a cross-tenant leak (the user belongs to both households), except (b) where a *different user* sees data. **Fix:** a shared household/session generation counter checked after every await (generalise `captureRequest`); reset all stores on logout and on any `currentHouseholdId` change including transitions through `null`. **Test:** per-store "late response after switch" tests; logout → stores empty. **Confidence:** High.

### CASA-13 · "Feed all" racing a single feeding leaves pets unfed but says "all already fed"
- **Severity:** Medium · **Class:** A · **Modules:** Pets, Tags (`pet.feed` without target), Dashboard · **Refs:** `pets.py:426-429` (`except IntegrityError: db.rollback(); return []`), `PetsView.vue:145-157`, `tag_actions.py:257-267`
- **Observed:** 4 pets; one person feeds pet 1 while another taps "Alle gefüttert": in 12/30 trials feed-all returned `[]` and only 1 of 4 pets was fed; the toast said "Alle sind schon gefüttert"; the tag page said "War schon erledigt — nichts geändert".
- **Evidence:** `pets_plants_documents/s1_pets.py` S2 `{(200, 0, 1): 12, (200, 4, 4): 12, (200, 3, 4): 6}`; `tags_ai/pg_tags.py` T4.
- **Impact:** animals miss a meal while two people each believe someone fed them — exactly the coordination problem the feature exists to solve. **Fix:** per-pet `INSERT … ON CONFLICT DO NOTHING RETURNING`; report what was really created. **Test:** PG race → every pet fed. **Confidence:** High.

### CASA-14 · Medication administration: a second daily dose cannot be recorded in the UI; duplicates across devices are not detected
- **Severity:** Medium · **Class:** C/F · **Modules:** Pets (medications) · **Refs:** `PetDetailView.vue:266-271, 776-783` (button hidden after any dose today), `pets.py:750-775` (no guard)
- **Observed:** a "2x täglich" medication cannot get its evening dose logged in the app (the API accepts it). Two people giving the pill at the same time both get 201; the warning only appears after the socket update. Inactive medications accept doses via API.
- **Evidence:** `pets_plants_documents/s1_pets.py` S3 (`parallel give by Anna+Ben: [201, 201]`, `sequential double give: 201 201`).
- **Impact:** the next person cannot tell whether the second dose was given → risk of a missed or a double dose. Never silently merge or discard doses; record and *warn*. **Fix:** see PD-P1 (always allow, show "zuletzt gegeben um HH:MM von X", confirmation within N hours; later `doses_per_day`). **Test:** component test for multi-dose; API idempotency with client id. **Confidence:** High.

### CASA-15 · Deleting a pet, medication, chore or plant erases its history; any member can do it
- **Severity:** Medium · **Class:** C · **Modules:** Pets, Chores, Plants · **Refs:** `models.py` cascades (`medication_logs`, `feeding_logs`, `chore_assignments`, `plant_care_logs`), `pets.py:503-531, 720-741`, `chores.py:336-353`; confirmation texts `de.json:704,730` do not mention history
- **Observed:** a non-admin member deletes a medication → `medication_logs before=5 after=0`. Non-destructive alternatives exist (`active=false` for medications and chores) but the UI never suggests them.
- **Impact:** a vet's question "when was the last antibiotic given?" becomes unanswerable after one mis-tap; chore fairness history vanishes. **Fix:** PD-P2 (block delete when history exists and offer deactivate/archive; warn with counts). **Confidence:** High.

### CASA-16 · Changing a chore schedule creates an already-overdue assignment and skips a turn; other clients keep phantom assignments
- **Severity:** Medium · **Class:** A · **Modules:** Chores, rotation, badge/widget, other clients · **Refs:** `chore_scheduler.py:190-197` (`from_date = last + 1 day`, never clamped to the new `anchor_date`); `chores.py:287-329` (deletes future open assignments, emits only `chore_updated`)
- **Observed:** weekly Monday chore, edited to Wednesday on Saturday 10-10 → an open, overdue 10-07 assignment for Carla appears and her real next turn is consumed; monthly 1st → 8th on 10-10 creates an overdue 10-08. Other members' open apps keep the deleted assignments; ticking one → 404.
- **Evidence:** `chores_tasks_time/pg_schedule.py` (`after edit: … ('2026-10-07','Carla',False), ('2026-10-14','Anna',False)`); `frontend_realtime_ux/pg_realtime.out` P1.
- **Fix:** `from_date = max(last+1, anchor_date, backfill_limit)`; emit `chore_assignments_changed`/deleted ids and refetch on schedule change. **Test:** API with patched today; store test. **Confidence:** High.

### CASA-17 · A paused chore keeps notifying; reactivation creates a burst of overdue duties
- **Severity:** Medium · **Class:** B/A · **Modules:** Chores, push scheduler, attention/badge, widget, dashboard, `/tasks` · **Refs:** `push_service.py:332-344`, `attention.py:94-108`, `tasks.py:48-56`, `dashboard.py:217-227` (no `Chore.active` filter); `chores.py:320-322`
- **Observed:** a chore paused after its next assignment was materialised still sends "Du bist dran" and counts in the badge for up to 7 days. Reactivating after 6 weeks immediately creates two overdue assignments for two different people.
- **Evidence:** `chores_tasks_time/pg_schedule.py` (`pushes on 11-24: [('Du bist dran','PausedPush',['Anna'])]`; `overdue open right after reactivation: [('2026-11-07','Carla'), ('2026-11-14','Anna')]`).
- **Impact:** holidays/renovation pauses still nag; reactivation punishes people for weeks nobody was supposed to clean. Extends L-10/E-3. **Fix:** PD-C1 (delete open future assignments on pause, re-anchor on reactivation) or filter `Chore.active` everywhere. **Confidence:** High.

### CASA-18 · Tag execute is not pinned to what the user confirmed on resolve
- **Severity:** Medium · **Class:** A/B · **Modules:** Tags (chore, `plant.water` without target) · **Refs:** `routers/tags.py:151-153` (`TagExecuteRequest` only has `slot`), `tag_actions.py:588`, `plants.py:345-381`
- **Observed:** resolve shows the 2026-10-10 assignment; Ben completes it in the app; the scanner taps confirm → the 2026-10-03 assignment is completed instead (`same as shown? False`). "Water all" waters whatever is due at execute time, not the count shown.
- **Evidence:** `tags_ai/pg_tags.py` T3. **Fix:** return a confirm token (target ids/versions) from resolve and require it on execute; 409/`changed=false` if stale. **Confidence:** High.

### CASA-19 · Meal-poll decision blanks the day on other devices, silently overwrites a planned meal, and fails with 500 under concurrency
- **Severity:** Medium · **Class:** A/C · **Modules:** Polls, Meal plan, Food UI · **Refs:** `polls.py:525-529` (emits `{"date"}` only; PUT emits the full entry at `food.py:422-426`), `stores/food.ts:208-215`, `FoodView.vue:150-155`; `polls.py:488-514` (upsert overwrite); `food.py:395-419`
- **Observed:** (a) other members see the decided day as "Kein Essen geplant" (entry replaced by `{date}`, no id, so "add missing ingredients" cannot work) until reload — same defect class as the fixed L-03. (b) A manually planned "Grosis Geburtstag – Fondue" is replaced by the poll result without warning or undo. (c) Two parallel writes to the same day → 500 (4/4), a concurrently decided meal poll stays open.
- **Evidence:** `journeys/j4_meal_shopping.py` (`emitted events: [('meal_plan_updated', {'date': '2026-10-17'})]`, Pasta overwritten by Zopf); `shopping_food_calendar/t_polls.out` P7/P9, `vt/mealdecide.test.ts`.
- **Fix:** emit `MealPlanEntryResponse`; confirm/409 when the date is occupied (PD-M1); `ON CONFLICT DO UPDATE`. **Confidence:** High.

### CASA-20 · Calendar deletion races silently delete events that were just confirmed
- **Severity:** Medium · **Class:** A · **Modules:** Calendars, Events, Polls · **Refs:** `calendars.py:178-203` (count check then delete; ORM cascade on `Calendar.events`), `polls.py:400-425`
- **Observed:** delete calendar ‖ create event: creator gets 201 but only 1 of 3 such events survived; delete calendar ‖ poll decide: poll ends `entschieden` with `decided_event_id = NULL`, decider gets 500 (3/6); two concurrent calendar deletes left 0 calendars (1/2).
- **Evidence:** `shopping_food_calendar/t_cal.out` C9/C10, `t_polls.out` P5. **Fix:** lock the calendar (or household calendars) row; FK `RESTRICT` + `passive_deletes` instead of ORM cascade. **Confidence:** High.

### CASA-21 · Missing membership validation for todo assignees, event participants and event-poll recipes
- **Severity:** Medium · **Class:** B · **Refs:** `todos.py:195-204, 243-246` (no `assert_users_in_household`; chores/expenses/bills/shopping validate), `events.py:170, 250-252`, `polls.py:205-221` (recipes validated only for meal polls)
- **Observed:** todo assigned to a user of another household → 201/200; random UUID → 500 (FK); event participants: random, duplicate and foreign ids accepted; event poll accepts a foreign household's recipe id (a later delete in the other household nulls the option's link — a cross-tenant side effect).
- **Evidence:** `chores_tasks_time/pg_todos.py`, `households/lifecycle.py` §4, `shopping_food_calendar/t_cal.out` C6, `t_polls.out` P10.
- **Impact:** such todos are counted for nobody (badge, "Meine"); foreign ids stored in household data (no content leak). **Fix:** `assert_users_allowed` (ex-members already on record allowed, as for L-05). **Confidence:** High.

### CASA-22 · A member's departure leaves dangling responsibilities that different surfaces treat differently
- **Severity:** Medium · **Class:** C/A · **Modules:** Households, Todos, Chores, Push, Badge/widget, Recurring bills, Polls, Widget tokens
- **Refs:** `households.py:160-270` (no cleanup), `attention.py:79,98-104` (mine or NULL), `push_service.py:226,354-357` (assignee else all members), `recurring_bills.py:225-231`, `widget.py:184-207`
- **Observed:** todos/chore assignments of an ex-member: push "Ämtli heute fällig" goes to all remaining members, but their badge and widget count **0** and the dashboard lists the item without a name; up to 7 days of materialised turns stay assigned to the ex-member. A recurring bill keeps the ex-member as default payer (booking without override → 422 with a raw UUID message; the UI pre-selects a current member). Ex-members' votes in open polls keep counting. The ex-member's widget key is not deleted on voluntary leave and works again after rejoining (contradicts `docs/widget.md:35`).
- **Evidence:** `chores_tasks_time/pg_schedule.py`, `households/lifecycle.py`, `journeys/j1.out`, `shopping_food_calendar/t_polls.out` P13.
- **Fix:** PD-H1 (clear assignees/default payer on leave, or treat ex-member assignees as unassigned everywhere); delete widget tokens on leave/remove. **Confidence:** High. (Extends L-15/E-6/E-7.)

### CASA-23 · Only the newest 100 expenses and settlements are visible; older ones still count
- **Severity:** Medium · **Class:** A · **Refs:** `expensesRepository.ts`/`settlementsRepository.ts` (`fetchAll` without paging), backend default `limit=100` (`expenses.py:231`); no "load more" in `ExpensesView.vue`
- **Impact:** after a few months (≈5 expenses/week) old entries cannot be found, corrected or deleted, and balances cannot be reconciled against the visible list. **Evidence:** code reading. **Fix:** pagination or month filter matching the finance summary. **Confidence:** High.

### CASA-24 · Ordinary concurrency surfaces as HTTP 500 on many endpoints
- **Severity:** Medium (aggregate) · **Class:** A · **Modules:** Budgets, Meal plan, Widget tokens, Register, Join, Documents, Shopping items, Expenses, Polls
- **Observed (PG):** concurrent first `PUT /budget` (1/6 → 500), meal-plan PUT same day (4/4), widget-token create (3/6 → 500; two callers received tokens that were immediately invalid), register same email (5/6), double join (≈11/15), two documents claiming the same file (5/10), item into a concurrently force-deleted list (2–3/5), plus CASA-01/10/19/20.
- **Root cause:** check-then-insert relying on unique/FK constraints without catching `IntegrityError`/`StaleDataError` (caught only in `client_ids.py`, `chore_scheduler.py`, `polls.py` votes, `pets.py` feeding, `recurring_bills.py`, `ai/usage.py`).
- **Impact:** data stays consistent (constraints hold) but users see a generic error and retry. **Fix:** `INSERT … ON CONFLICT` for upserts; map integrity errors to 409; a global exception handler that maps `IntegrityError` to 409 as a safety net. **Evidence:** `infra_data_tests/races.py`, `households/races.py`, `pets_plants_documents/s2_files.py`, `shopping_food_calendar/t_shopping.out` S10. **Confidence:** High.

### CASA-25 · The test strategy cannot detect concurrency, migration or cross-module defects
- **Severity:** Medium · **Class:** E · **Refs:** `backend/tests/conftest.py:84-171` (SQLite in-memory, `create_all`, one shared session), `.github/workflows/ci.yml` (no PostgreSQL, no `alembic upgrade`, no E2E)
- **Observed:** none of CASA-01, -05 (parallel), -10, -11, -13, -19, -20, -24 can fail the current suite; migrations are never executed in CI; no property-based tests; no frontend component/view tests; no E2E (`frontend/qa/mobile-audit.cjs` is a manual screenshot tool). 46/62 backend test files patch internals; socket emits are globally mocked.
- **Fix:** see TEST_GAP_MATRIX.md and Roadmap P1-T. **Confidence:** High.

---

## 5. Findings – Low

Each row: ID · module · refs · observed → expected · evidence · root cause → fix · regression test · confidence.

| ID | Class | Module / refs | Observed → expected | Evidence | Root cause → recommended fix | Regression test | Conf. |
|---|---|---|---|---|---|---|---|
| CASA-26 | A/E | Files `files.py:241-283` | 8 parallel 200 KB uploads vs 1 MB quota → 7 accepted, 1.40 MB used → quota must hold | `s2_files.py` F1 | SUM-then-insert → household row lock or counter with conditional UPDATE | PG parallel upload | High |
| CASA-27 | E | Files `files.py:335-356` | Orphan cleanup selects file, file is attached, cleanup deletes it → document with 0 pages, bytes gone → never delete attached files | `s2_files.py` F4 (manual interleave) | Unguarded delete → `DELETE … WHERE NOT EXISTS` / `FOR UPDATE SKIP LOCKED` | PG two-session test | High (rare) |
| CASA-28 | A | Files/Pets/Docs `files.py:286-320` | Pet photo PATCH ‖ document create on same file → both reference it (8/15); deleting the document removes the pet photo; doc‖doc → 500 | `s2_files.py` F2/F3 | Unlocked `file_in_use` → lock `StoredFile`, map IntegrityError → 422 `FILE_IN_USE` | PG race | High (API-only) |
| CASA-29 | A/C | Plants, Tags `plants.py:222-244,345-380`, `tag_actions.py:318,484` | Parallel complete / water-all → duplicate care logs (10 for 5 plants); care-task tags always `changed:true`; single-plant water also completes a non-due water task (+20d → +30d); parallel `todo.done` → two events, `done_at` overwritten | `s3_plants_push.py`, `pg_tags.py` T7–T11 | No idempotency per day → E-4 option b (`last_done_at == today` → `changed=false`), conditional updates | PG parallel | High |
| CASA-30 | F/C | Pets `stores/pets.ts:186-198` | One tap deletes another member's feeding (undo toast only, no trace) → confirm when recorded by someone else | `s1_pets.py` S2c | → confirmation + attribution | component test | High |
| CASA-31 | F | Tags `TagScanView.vue` | Feed tag blocks when default slot fed; other slot cannot be logged → allow any unfed slot | `pg_tags.py` T13 | → `can_execute` if any slot unfed, preselect it | API | High |
| CASA-32 | A | AI `services/ai/usage.py:54-58` | First parallel requests of a UTC day get 429 with 5–9 of 50 used → only reject at limit | `pg_ai_firstrow.py` | Row-exists path raises instead of retrying → `INSERT … ON CONFLICT DO UPDATE … WHERE calls < limit` | PG parallel | High |
| CASA-33 | A | AI `client.py:95-110`, `ai.py:191-198` | `APIResponseValidationError`/unexpected exceptions → raw 500 and quota consumed → 502, reservation released | `pg_ai.py` A3 | Unmapped exception → `except anthropic.APIError` + generic release | unit (mock) | High |
| CASA-34 | A/C | AI frontend `stores/ai.ts:101-161` | In-flight suggestion lands in the new household after a switch and can be saved there; "missing ingredients" from AI: no dedupe, active list, partial failure + retry duplicates (L-12) | code reading | No household capture; client loop → capture household; backend bulk endpoint with dedupe | vitest | Medium |
| CASA-35 | A/C | Calendar `event_times.py:76-80` | DST gap: 02:30–03:15 on 2026-03-29 rejected as "end before start"; 02:30–03:45 stored as 03:30–03:45 → reject or normalise with notice; overlap resolves to first occurrence (acceptable) | `t_cal.out` C1/C2 | `replace(tzinfo)` with fold=0 → detect gap after round-trip | `test_event_times.py` gap/overlap | High |
| CASA-36 | A | Finance (amounts, dates) | Amounts ≥ 2^31 Rappen → 500 (int32 columns); `finance-summary?month=9999-12-01` → 500; dates 0001/9999 accepted → bounded validation | `pg_scenarios.py` 7, 13 | `gt=0` only → `le=10^9`, date bounds | API | High |
| CASA-37 | A | Shopping, recipes, events, expenses, bills | Explicit `null` on non-nullable fields → 500 (no data change, unlike CASA-04) → 422 | `pg_nulls.py`, `t_shopping.out` S6 | → same validator as CASA-04 | API | High |
| CASA-38 | A | Finance UI `ExpenseFormDialog.vue:227` | Category cannot be removed in the edit dialog (key omitted) → send `null` | code + API | → send explicit null | vitest | High |
| CASA-39 | A/F | Frontend dates (`ExpenseFormDialog.vue:145`, `BalanceSummary.vue:69`, `ChoresView.vue:50-66`, `TodoList.vue:95-97`), `Todo.due_date` DateTime 00:00Z | Device date used instead of household date; todo due dates west of UTC show the previous day and are overdue on the due day → household date everywhere | `pg_todos.py`, code | → household "today" from `/me`; `Todo.due_date` as `Date` | vitest with TZ | High (travel only) |
| CASA-40 | A/F | Push `push_service.py:232,256,287,362`, `public/push-sw.js:40-57` | Tapping a reminder for household B while the app is on A opens the URL in A ("not found"); badge flips between households → include household in URL and switch | code | → `?hh=` + router handling | E2E | High |
| CASA-41 | E/F | PWA `pwa.ts:9-20` | Update offered by one 60 s toast; no periodic `registration.update()`; long-lived iOS PWAs keep an old frontend against a new backend | config | → update check on visibility change + persistent "Update verfügbar" | manual/E2E | Medium |
| CASA-42 | A | Finance store `finance.ts:143-168` | `budget_updated` ignores `month`; `budget_deleted` unconsumed; bill events do not refresh `pending_bills` → stale "Noch verfügbar"/bill card | vitest `finance_store.test.ts` | → compare month; refetch summary | vitest | High |
| CASA-43 | A/F | Dashboard/badge/tasks (`App.vue:218-258`, `useAppBadge.ts:18-35`, `dashboard.py:217-227`, `tasks.py:48-56`) | Dashboard not invalidated on chore/pet/calendar events; dashboard shows today's chores only while badge counts overdue ones; `/tasks` unused and classifies differently | code + `pg_concurrency.py` | → one "due items" service; generic invalidation | API consistency | High |
| CASA-44 | A/E | Frontend `App.vue:83-87,264` | Every token refresh (≤15 min) reloads all core stores; a stale snapshot can wipe an item just created → reload only on household change/reconnect | `races.test.ts` R7 | → drop token from watch source | vitest | Medium |
| CASA-45 | A/E | Stores (delete rollback, create rollback) | Own DELETE 404 after a remote delete → rollback re-inserts an undeletable ghost; lost create response → rollback hides an item that exists; manual retry uses a new client id → duplicate | `races.test.ts` R4/R9, `pg_realtime.out` P6 | → treat 404 as success; keep unconfirmed items | vitest | High |
| CASA-46 | A | Realtime contract | Materialisation via `/tasks`/scheduler emits no `chore_assignment_created`; reminder add/delete emit `todo_updated` with unchanged version; failed `join_household` (`error` event) unhandled while the dot shows "verbunden"; register-with-code emits no `household_member_joined`; feature-store member lists never refreshed | `pg_concurrency.py`, `pg_reminder_version.out`, code | → emit from scheduler; bump parent version; handle `error`; refresh members | contract tests | High |
| CASA-47 | A | Auth/Push `stores/auth.ts:83-87` | Device whose session silently expired at start keeps receiving that user's pushes (lock screen) → unsubscribe on 401 at start | code | → `disablePush` in 401 branch | vitest | Medium |
| CASA-48 | E | Socket `socket_manager.py:159-239` | `join_household` membership check and `enter_room` can straddle an eviction; `reauth` never re-checks membership | code | → re-check after `enter_room` and in `reauth` | socket integration | Low–Med |
| CASA-49 | A | Frontend `App.vue:290-297`, `api/client.ts:75` | Removal missed while offline → app stays in the household, every call 403 until reload → `fetchMe` on reconnect / on 403 `NOT_HOUSEHOLD_MEMBER` | code | | vitest/E2E | Medium |
| CASA-50 | F | `WidgetSettingsCard.vue:33-61` | Result of a request for household A shown after switching to B → capture household | code | | vitest | Medium |
| CASA-51 | C/F | Chores/Todos | Future assignment completed early blocks the new schedule after an edit (one period skipped); reminders can be added to a done todo (silently never sent); naive `remind_at` treated as UTC (events use household time) | `pg_schedule.py`, code | → clamp on open only; 422; consistent wall-clock rule | API | High |
| CASA-52 | A/B | Recipes `food.py:321-336`, `stores/food.ts:204-206` | Deleting a recipe leaves meal plan entries with neither recipe nor text (state the PUT forbids); other clients still show the recipe | `j4`, `t_food.out` F1 | → copy name into `free_text` (PD-M3) | API | High |
| CASA-53 | A | Food→Shopping `food.py:211-230,494-530` | Parallel "Fehlende Zutaten" → duplicate items and two default lists; dedupe only on the first list and exact lowercase name ("500 g Mehl" vs open "Mehl" on list 2) | `t_food.out` F2b/F2c, `j4` | → lock target list; documented free-text limitation | PG race | High |
| CASA-54 | B | Calendars `calendars.py:178-188` | Two concurrent deletes → household with 0 calendars → lock (part of CASA-20 fix) | `t_cal.out` C10 | | PG race | High |
| CASA-55 | E | Data model (latent) | No user-deletion path exists, but FK rules are inconsistent: `expense_shares.user_id`/`settlements.*` CASCADE (would rewrite balances: simulated delete → Σsaldi 1000, unassigned 3000), six other user FKs NO ACTION (would block) → decide anonymisation before any account deletion | `pg_scenarios.py` 11, `fks.txt` | → PD-D1, RESTRICT on ledger FKs | schema test | High |
| CASA-56 | E | Migrations | Downgrade fails below `0f34ff355756` (`drop_constraint(None …)`); `created_at` nullable in DB but not in models on 8 tables; DB-only server defaults | `drift2.py` | → cleanup migration; CI drift check | CI | High |
| CASA-57 | E | Operations (`docker-compose.prod.yml`, `scripts/backup-*.ps1`, `nginx.conf`, `frontend/Dockerfile`) | Backups on the same host; DB dump and upload archive not a consistent pair; no log rotation, error tracking or alerting; rate limiting assumes Docker pool 172.16.0.0/12 (else all clients share one IP); image build skips `vue-tsc` | config reading | → off-host backup, restore drill, alerting on `/api/health`, configurable trusted proxy range | ops checklist | Medium (prod unverified) |
| CASA-58 | — (docs) | `PROJECT-STATUS.md`, `tag_actions.py:32`, `tags-review.md` | Docs inconsistent: migrations "33"/"37" with heads `w1x2…`/`y1z2…` (actual 40, head `a3b4c5d6e7f8`); "32 tables" (actual 38); bill management UI and recipe CRUD UI claimed but absent; socket table still shows L-03 payload; `TagResolveView.vue` does not exist; tags test count 52/66 (actual 65); admin list omits invite rotation and AI settings | repo reading | → correct docs | — | High |
| CASA-59 | F | Tags `tag_actions.py:326-336` | Backend-generated plant care names are German-only for English users | code | → i18n keys | — | High |
| CASA-60 | C/A | Polls `polls.py:48-53`, `CalendarView.vue:607-609` | Option times returned in UTC (L-13) → "decided on" toast shows the previous day for 00:00–02:00 options; an option without time creates an event "now" (with microseconds) | `t_polls.out` P2/P6 | → household time in API (E-10 b); require time (PD-K2) | API | High |

---

## 6. Business logic findings (consolidated view)

- **Money:** CASA-01, -02, -03, -08, -09, -23, -36, -42 and the latent CASA-55. Sequential arithmetic is correct and well tested; the problems are record integrity, attribution and concurrency.
- **Responsibility and rotation:** CASA-05, -16, -17, -18, -22, -51. The scheduler maths is correct (property-tested); the transitions around it (edit, pause, reactivate, depart, scan) are not.
- **Care and safety (pets, medication):** CASA-13, -14, -15, -30, -31. No silent merging or discarding of medication records was found (correct); the gaps are visibility and duplicate detection.
- **Planning (calendar, polls, meals):** CASA-04, -19, -20, -35, -52, -53, -60; event reminders do not exist and are not planned (PD-K1).
- **Reminders:** CASA-06, -17, -22, -40, -47; exactly-once dispatch verified; delivery after downtime is at-most-once by design (D, should be documented).

## 7. User logic findings

- Feedback that contradicts reality: "Alle sind schon gefüttert" (CASA-13), "War schon erledigt" / success on backlog (CASA-05), bell shown for a cancelled reminder (CASA-06), "verbunden" while not in a room (CASA-46), success toast for a join that was undone (CASA-10).
- Recovery actions that make things worse: Undo of a booked expense (CASA-03), Undo of a todo (CASA-06), rollback ghosts (CASA-45).
- Missing attribution: expenses (no creator/editor), shopping (no "checked by"), todos (no "done by"), settlements ("created by" exists but is not shown), deletions of others' records are untraceable (CASA-02, -15, -30).
- Capabilities claimed but missing: recurring bill management UI, recipe CRUD UI (CASA-58).
- Accessibility: no new defects found beyond prior reviews; not re-audited in a browser (unverified).

## 8. Cross-module inconsistencies

See CROSS_MODULE_DEPENDENCIES.md. The most consequential: expense delete → bill booked state (CASA-03); member departure → push vs badge vs dashboard vs widget (CASA-22); chore pause → push/badge/tasks (CASA-17); meal-poll decide → meal plan → other clients (CASA-19); calendar delete → events → polls (CASA-20); tag execute vs UI completion (CASA-18); household switch/logout → every store (CASA-12).

## 9. Security findings

No new cross-tenant data exposure was found. Verified: membership checks on all 139 household routes, removed members lose REST/file/tag access immediately, push recipients filtered by membership, tag tokens redacted in logs, AI cannot mutate data and receives only the user's own inputs.

| ID | Finding | Classification |
|---|---|---|
| CASA-10 | An orphaned 0-member household remains joinable with a still-valid invite code; the joiner sees all previous data | New (A) |
| CASA-12 (b) | Next user on the same device sees the previous user's data until their own data loads (or instead of it, offline) | New (A) |
| CASA-47 | Logged-out device keeps receiving reminder pushes with titles | New (A) |
| CASA-22 | Widget key revives on rejoin, contrary to `docs/widget.md` | New (C/D) |
| CASA-48 | Socket room join/eviction race; `reauth` does not re-check membership | New (E, reasoned) |
| CASA-21 | Foreign user ids accepted in todos/events; foreign recipe id in event polls (no content leak) | New (B) |
| — | Access token valid 15 min after logout on other devices; rate limits per IP in memory; invite code visible to all members; AI limit multipliable across households (A-01) | Accepted, documented (D) in `PROJECT-STATUS.md` §8 / `docs/security/*` |

## 10. Data integrity findings

CASA-01 (ledger), CASA-04 (JSON null), CASA-10 (household invariants), CASA-20/54 (calendar), CASA-26/27/28 (files),
CASA-52 (meal plan), CASA-55 (FK rules), CASA-56 (migrations). Integrity that holds: unique constraints for
bookings, votes, feedings, assignments, memberships, budgets and meal plan days; all `household_id` FKs cascade;
no orphan rows found after any race (the constraints hold — the failures are 500s or semantic, not dangling references).

## 11. Concurrency findings

| Operation pair | Outcome on PostgreSQL | ID |
|---|---|---|
| PATCH ‖ PATCH expense | Σshares = 2×amount, both 200 / 500 | CASA-01 |
| settlement POST ‖ POST | two rows, debt flips | CASA-08 |
| leave ‖ leave, leave ‖ join | no admin / orphan / undone join / 500 | CASA-10 |
| refresh ‖ refresh | global logout 7–9/40 | CASA-11 |
| feed one ‖ feed all | 3 of 4 pets unfed, "all fed" | CASA-13 |
| give ‖ give medication | two doses logged | CASA-14 |
| chore tag ‖ chore tag | two assignments completed | CASA-05 |
| calendar delete ‖ event create / decide | confirmed event deleted / poll without event | CASA-20 |
| meal PUT ‖ PUT, meal-decide ‖ meal-decide | 500, poll stays open | CASA-19 |
| budget, widget token, register, join, document claim, item into deleted list | 500 | CASA-24 |
| uploads ‖ uploads | quota exceeded | CASA-26 |
| water-all ‖ water-all | duplicate logs | CASA-29 |
| AI first requests of the day | spurious 429 | CASA-32 |
| **Verified safe:** bill booking, poll decide, votes, feeding (single pet), chore materialisation, todo claim, push claims, shopping client-id creates, version bumps | exactly-once | — |

## 12. Architecture findings

- **Versioning is partial by design (D)** – only shopping lists/items, todos and chore assignments carry `version`; the frontend protects only those against stale events. The consequences are concentrated in finance (CASA-01/09) and should be addressed there first rather than generically.
- **Check-then-act without locks (E)** is the common root of CASA-01, -10, -11, -13, -20, -24, -26, -28, -53. A small helper (`lock_household(db, id)` / `lock_row`) and an `IntegrityError → 409` handler would remove most of them.
- **Partial socket payloads (E)** – two events (`meal_plan_updated` from polls, `shopping_items_bulk_updated`) are not full entities; a contract test should validate every emit against the response model (L-03 and CASA-19 are the same defect class).
- **Hard deletes everywhere (C/E)** – history-bearing records (expenses, settlements, medication logs, assignments) have no soft delete or audit trail.
- **Single-process design (D)** – Socket.IO rooms, AI semaphore, rate limits and schedulers are in-process; documented and consistent with `--workers 1`. Push claims are already multi-process safe.
- **No E2E harness (E)** – the most important household journeys (two devices, realtime) are untested end-to-end.

## 13. Prior review status (logic-review.md, current-audit-fixes.md)

| Item | Status | Evidence |
|---|---|---|
| L-01 finance dates in household time | Fixed (server); frontend still sends device date (CASA-39) | finance agent |
| L-02 custom bill booked as even | Fixed | `test_booked_expense_of_custom_bill_is_even_and_editable` |
| L-03 `event_created` partial payload | Fixed; same class open for `meal_plan_updated` (CASA-19); `PROJECT-STATUS.md` socket table stale | code |
| L-04 dashboard overdue at 00:00 UTC | Fixed (Zurich); west-of-UTC devices (CASA-39) | `pg_todos.py` |
| L-05 chore with ex-member in rotation | Fixed | test |
| L-06 pet care `notified_at` reset | Fixed | `s1_pets.py` S4 |
| L-07 stores not reset on switch | Fixed for the switch; in-flight responses, logout and `null` transitions open (CASA-12) | vitest |
| L-08 promoted admin role refresh | Fixed | `auth.ts:394-400` |
| L-09 rotation give-back miscount | Present in code, unreachable with the 7-day horizon | `pg_schedule.py` §6 |
| L-10 paused chore visible | Open and wider: also push/badge (CASA-17) | |
| L-11 next due from today | Open decision (E-1/E-2) | |
| L-12 AI missing ingredients dedupe | Open (CASA-34) | |
| L-13 poll times in UTC | Open; visible consequence (CASA-60) | |
| L-14 reconnect reload | Open, mitigated (most views reload); budget/members not | |
| L-15 ex-member assignee | Open; consequences (CASA-22) | |
| L-16 rotation UI reorder only | Open | `ChoresView.vue:580-600` |
| L-17 AI day in UTC | Open (documented) | |
| L-18 claim 409 | As documented | |
| §6 "todo reopen – ok" | **Incorrect** (CASA-06) | |
| §9 "chore tag – ok" | **Incorrect** beyond the first scan (CASA-05) | |
| §11 "two tabs refresh – both valid" | **Not reliably true** (CASA-11) | |
| §7 last admin / last member leave – ok | Only sequentially (CASA-10) | |
| §3 calendar with events cannot be deleted – ok | Only sequentially (CASA-20) | |
| §4 feed-all race → `[]` – ok | **Incorrect** (CASA-13) | |
| §5 two fields edited concurrently survive | API only; UI overwrites (CASA-09) | |
| current-audit-fixes (photo upload, pet/plant guards, invite guard, HEIC, focus) | Present | code |

## 14. Production readiness verdict

| Area | Verified locally | Verified in production | Risk |
|---|---|---|---|
| Sequential business logic of all modules | Yes (suites + scripts) | No | Low |
| Concurrency behaviour | Yes, on PostgreSQL 16 (this audit) | No | **High** until P0/P1 |
| Migrations (fresh DB) | Yes | No | Low |
| Restore / rollback | Defective (CASA-07) | No | **High** |
| Backups off-host, restore drill | No | Unknown | Medium |
| Web Push delivery on real devices (iOS) | No | Unknown | Medium |
| PWA update lifecycle on installed iOS app | No | Unknown | Medium |
| AI against the real Anthropic API | No (documented) | Unknown | Low |
| Monitoring / alerting / log rotation | Not present | — | Medium |

**Verdict:** Casa is a carefully built application whose individual modules are correct in the common
sequential path, but it is **not production-ready as the authoritative shared record** for money and animal
care until the P0 items are done: CASA-01 (expense locking/versioning), CASA-03 (Undo of booked expenses),
CASA-04 (null validation), CASA-05 (chore tag idempotency), CASA-06 (reminder reopen), CASA-07 (restore
procedure) and CASA-13 (feed-all). CASA-02/08 require product decisions that should be taken in the same
iteration because they define what a "financial record" is. Passing unit tests do not establish production
readiness here: the suite cannot observe the defects that matter most (CASA-25), and no production or
physical-device verification was part of this audit.
