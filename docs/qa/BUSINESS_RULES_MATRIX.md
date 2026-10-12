# Business Rules Matrix

**Date:** 2026-10-10 · Companion to [FULL_LOGIC_AUDIT.md](FULL_LOGIC_AUDIT.md). Finding IDs (`CASA-nn`) refer to that document.

Status values: **Verified** (evidence on PostgreSQL, property test or existing test that exercises the rule) ·
**Violated** (counter-example reproduced) · **Partially verified** (holds in some paths/conditions only) ·
**Unverified** (not exercised; reasoned only) · **Requires product decision** (no established rule).

"Entry points" lists where the operation can be triggered: UI = normal REST via frontend, API = REST directly,
Sock = realtime propagation, Tag = NFC/QR, Sched = background scheduler, AI = AI-assisted flow.

---

## 1. Households, users, permissions

| # | Invariant | Expected behaviour | Enforced at | Can be violated by | Entry points | Status | Tests | Missing tests |
|---|---|---|---|---|---|---|---|---|
| H1 | Every existing household has ≥ 1 member | Last leaver deletes the household and its files | `households.py:183-195` | Concurrent leave of the last two members | UI | **Violated** (CASA-10) | `test_leave_last_member_deletes_household` (sequential) | PG race |
| H2 | A household with members has ≥ 1 admin | Senior member auto-promoted | `households.py:197-208` | Concurrent leave of admin + senior member | UI | **Violated** (CASA-10) | `test_leave_admin_auto_promote` | PG race |
| H3 | A 200 join means the user is a member | — | `households.py:482-550` | Join ‖ last-member leave | UI | **Violated** (CASA-10) | — | PG race |
| H4 | Only members access household data | 403 for non-members on every route | `deps.py:32-46` on 139 routes | — | UI/API/Tag/files | **Verified** | `test_*_scoping.py`, route audit | — |
| H5 | A removed member loses access immediately | REST 403, socket evicted, cannot rejoin with old code | `deps.py`, `socket_manager.py:269-284`, code rotation | Socket join‖evict race; widget key on voluntary leave | UI/Sock/widget | **Partially verified** (CASA-22, CASA-48) | `test_removed_member_*` | socket integration |
| H6 | Admin-only: rename, rotate code, remove member, tag CUD, AI opt-in | — | `verify_household_admin` | — | UI/API | **Verified** | `test_admin_guard.py` | — |
| H7 | Who may delete others' records (expenses, settlements, pets, documents…) | — | none (any member) | — | UI/API | **Requires product decision** (PD-H2) | — | — |
| H8 | Departed member's open responsibilities | ? | none | leave/remove | UI | **Requires product decision** (PD-H1); current behaviour inconsistent across surfaces (CASA-22) | — | attention with ex-member |
| H9 | Refresh token: one successor; benign concurrent refresh never logs out | — | `auth.py:349-421` | Concurrent / triple refresh | UI (tabs) | **Violated** (CASA-11) | `test_grace_window_allows_second_tab_refresh` | PG race |
| H10 | Frontend shows only data of current household and current user | Reset + discard late responses | `householdScope.ts`, guards in 3 stores | Late responses (12 stores), logout→login, A→null→C | UI | **Violated** (CASA-12) | `householdScope.test.ts` | per-store race tests |
| H11 | Push goes only to current members | — | `push_service.py` recipient queries | Logged-out device with stale subscription | Sched | **Partially verified** (CASA-47) | `test_push.py` | auth 401 → unsubscribe |
| H12 | Widget key valid only while member | Deleted on leave | lazy check `widget.py:184-207` | leave → rejoin | widget | **Violated** vs docs (CASA-22) | `test_key_dies_when_user_leaves_household` | rejoin test |

## 2. Finance

| # | Invariant | Expected | Enforced at | Can be violated by | Entry points | Status | Tests | Missing |
|---|---|---|---|---|---|---|---|---|
| F1 | Σ shares = expense amount | Always, at commit | service layer `expenses.py:303/307/435/443`, `recurring_bills.py:261` | Concurrent PATCH; (latent) user delete | UI/API | **Violated** (CASA-01); sequential paths **Verified** (300 random sequences) | `test_shares_always_sum_to_amount` | PG concurrency; DB-level check |
| F2 | Rounding deterministic, fair within 1 Rappen, no lost cents | — | `split_evenly` | — | UI/API/Sched (bill) | **Verified** (hypothesis 3000 examples) | `test_even_split_with_remainder` | port property tests |
| F3 | No duplicate participants | 422 | `split_evenly`, `validate_custom_shares` | — | UI/API | **Verified** | `test_finance_correctness.py` | — |
| F4 | Σ saldo = −unassigned | — | follows from F1 | CASA-01; latent CASA-55 | — | **Violated** under F1 violation | `test_balances_unassigned_payer` | property test |
| F5 | Applying suggestions zeroes all balances in ≤ n−1 transfers; only debtors pay | — | `compute_settlements` | — | — | **Verified** (n ≤ 5000); not minimal (D) | `test_expense_balances.py` | port property test |
| F6 | A real payment is recorded exactly once | — | none | Both parties record; retries | UI | **Violated** (CASA-08) | — | idempotency |
| F7 | Settlement plausibility (≤ current debt, correct direction) | ? | none | — | UI/API | **Requires product decision** (PD-F3) | — | — |
| F8 | Settled history changes are visible and attributable | ? | none (hard delete, no creator on expense) | Any member edit/delete | UI | **Requires product decision** (PD-F1/F2); impact shown in CASA-02 | — | journey test |
| F9 | Concurrent edits do not silently overwrite each other | 409 or field merge | none (no version on expenses) | Stale full-payload dialog | UI | **Violated** (CASA-09) | — | stale PATCH → 409 |
| F10 | One booking per bill and household month | 409 on second | UNIQUE `(recurring_bill_id, booked_month)` + catch | Delete + Undo (link lost) | UI/API | **Verified** for booking (8-way); **Violated** via Undo (CASA-03) | `test_book_idempotent_409` | undo scenario |
| F11 | Booking month = household month | — | `household_today` | Device date in UI | UI | **Verified** server (L-01 fixed); UI residual (CASA-39) | `test_household_time.py` | — |
| F12 | Bill split = even over current members | — | `recurring_bills.py:255-261` | `split_type="custom"` stored but ignored | API | **Requires product decision** (E-5 / PD-F5) | `test_booked_expense_of_custom_bill_is_even_and_editable` | — |
| F13 | Bill payer must be a current member | 422 otherwise | `assert_users_in_household` | Default payer left → 422 | UI | **Verified** (UI preselects current user); default payer stale (CASA-22) | — | — |
| F14 | One currency per household; mismatch 422 | — | `expenses.py:276`, settlements | — (no currency-change endpoint) | UI/API | **Verified** | `test_currency.py` | — |
| F15 | Budget/summary month totals = Σ expenses with `expense_date` in household month; settlements excluded | — | `households.py:340-365`, `budgets.py` | — | UI | **Verified** (31.12/1.1, 29.2) | `test_finance_summary.py` | boundary tests |
| F16 | Ex-member debts remain visible and settleable | — | `assert_settlement_parties` | Undo of ex-member expense (422) | UI | **Verified**; Undo **Violated** (CASA-03) | `test_ex_member_debt_*` | — |
| F17 | All history is reachable in the UI | — | none (limit 100) | > 100 entries | UI | **Violated** (CASA-23) | — | pagination |
| F18 | Amounts within storage range | 422 for out-of-range | none | ≥ 2^31 Rappen | API | **Violated** → 500 (CASA-36) | — | boundary |
| F19 | User deletion never rewrites balances | — | FK rules (CASCADE on shares/settlements) | Future account deletion | — | **Requires product decision** (PD-D1); latent (CASA-55) | — | schema pin test |

## 3. Chores & rotation

| # | Invariant | Expected | Enforced at | Violated by | Entry | Status | Tests | Missing |
|---|---|---|---|---|---|---|---|---|
| C1 | ≤ 1 assignment per (chore, date) | — | UNIQUE + savepoint + `FOR UPDATE` | — | UI/Sched/Tag/tasks | **Verified** (PG, 12 parallel) | `test_materialize_idempotent` | PG test in suite |
| C2 | Rotation deterministic, skips non-members | — | `_resolve_next_assignee` | — | — | **Verified** (property test) | `test_rotation_skips_departed_member` | — |
| C3 | Date maths correct at month/year ends, leap years, biweekly parity | — | `next_due_dates` | — | — | **Verified** (5000 examples) | `test_monthly_day31_*` | port property test |
| C4 | After a schedule edit no open assignment lies before the new anchor | — | none | PATCH weekday/day | UI | **Violated** (CASA-16) | — | API with patched today |
| C5 | Paused chore produces no work and no notifications | — | only "no new assignments" | Materialised assignments | Sched/UI | **Violated** (CASA-17) | — | push/badge test |
| C6 | Reactivation starts fresh | ? | none | PATCH active=true | UI | **Violated / decision** (CASA-17, PD-C1) | — | API |
| C7 | Renaming never changes assignments | — | `chores.py:290-293` | — | UI | **Verified** | `test_rename_with_full_payload_keeps_assignments` | — |
| C8 | "Du bist dran" to current assignee, once | — | `_claim`, reset on reassign | — | Sched | **Verified** (6 workers) | `test_chore_notifies_assignee_once_in_the_morning` | multi-worker in suite |
| C9 | One scan completes at most the current period | — | `current_chore_assignment` | Repeated/parallel scan | Tag | **Violated** (CASA-05) | `test_prefers_current_period_over_older_backlog` (one scan) | double scan |
| C10 | Execute acts on the confirmed assignment | — | none | Completion between resolve and execute | Tag | **Violated** (CASA-18) | — | PG |
| C11 | All clients observe the same assignments | — | socket events | Schedule edit (no delete event); scheduler materialisation (no emit) | Sock | **Violated** (CASA-16, CASA-46) | — | contract test |
| C12 | Departed member's turns | ? | scheduler skips future; materialised stay | leave | — | **Requires product decision** (PD-H1, E-7) | — | — |

## 4. Todos, reminders, unified tasks

| # | Invariant | Expected | Enforced at | Violated by | Entry | Status | Tests | Missing |
|---|---|---|---|---|---|---|---|---|
| T1 | Claim: exactly one winner | — | conditional UPDATE | — | UI | **Verified** (PG 8 parallel) | `test_todo_claim.py` | — |
| T2 | Reminder fires once; never for a done todo | — | `_claim`, done marks reminders | Done → undo | UI/Tag | **Violated** for undo (CASA-06) | `test_done_and_stale_reminders_claimed_but_not_sent` | reopen test |
| T3 | Assignee is a household member | 422 otherwise | none | API create/patch | UI/API | **Violated** (CASA-21) | — | API |
| T4 | "Due today" is not overdue on its day; same classification on all surfaces | — | `dashboard.py:177-181`, `attention.py:87`, `TodoList.vue:95-97` | Device west of UTC; `/tasks` vs dashboard vs badge | UI | **Partially verified** (Zurich OK; CASA-39, CASA-43) | `test_dashboard_todo_due_today_is_not_overdue` | cross-surface |
| T5 | Deleting a todo removes its reminders | — | CASCADE | — | UI | **Verified** | — | — |
| T6 | Repeated `todo.done` scan is a no-op | `changed=false` | sequential check | Parallel scans | Tag | **Partially verified** (CASA-29) | `test_tags.py` | PG parallel |

## 5. Shopping

| # | Invariant | Expected | Enforced at | Violated by | Entry | Status | Tests | Missing |
|---|---|---|---|---|---|---|---|---|
| S1 | Create with client id is idempotent | 200 existing, no 2nd event | `client_ids.py` | — | UI | **Verified** | `test_offline_sync.py` | — |
| S2 | A deleted item stays deleted | — | none (no tombstones) | Delayed same-id retry | API (no M0 UI path) | **Violated – documented limitation** (D) | `test_item_delete_twice_is_204_then_404` | — |
| S3 | Stale socket events never overwrite newer state | — | `upsertVersioned` | Bulk event without version | Sock | **Partially verified** | `syncRaces.test.ts` | bulk |
| S4 | Concurrent edits of different fields both survive | — | PATCH applies sent fields only | Edit sheet sends full snapshot | UI | **Violated in UI** (CASA-09) | — | component test |
| S5 | Store names grouped case-insensitively, canonical spelling | — | `canonical_stores` | — | UI | **Verified** | `test_shopping_stores.py` (23) | — |
| S6 | Same item added twice | ? | none | — | UI | **Requires product decision** (PD-S1) | — | — |
| S7 | "Missing ingredients" never duplicates open items | — | exact-name check on first list | Concurrent imports; AI path; other lists; quantities in text | UI/AI | **Partially verified** (CASA-53, CASA-34) | `test_add_missing_to_shopping_skips_duplicates` | PG race |

## 6. Calendar & polls

| # | Invariant | Expected | Enforced at | Violated by | Entry | Status | Tests | Missing |
|---|---|---|---|---|---|---|---|---|
| K1 | Times are household wall-clock, stored UTC | — | `event_times.py` | DST gap | UI | **Partially verified** (CASA-35) | `test_event_times.py` | gap/overlap |
| K2 | All-day events keep their date; edits don't shift times | — | `event_times.py` | — | UI | **Verified** | `test_all_day_event_keeps_its_date` | — |
| K3 | Range queries include last day and multi-day events | — | `range_bounds` | Dashboard/widget (start day only) | UI | **Verified** for calendar; dashboard decision (PD-K3) | `test_week_range_includes_sunday` | — |
| K4 | Calendar with events cannot be deleted; ≥ 1 calendar | 422 | count checks | Concurrent create/decide/delete | UI | **Violated** under concurrency (CASA-20, -54) | sequential tests | PG race |
| K5 | Poll decided at most once, ≤ 1 event | — | conditional UPDATE | — | UI | **Verified** (PG 10×3) | `test_decided_poll_cannot_be_decided_again` | PG in suite |
| K6 | One vote per person per poll; none after decision | — | UNIQUE + checks | — | UI | **Verified** | `test_one_vote_per_user_and_poll` | — |
| K7 | Decided event poll has its event | — | none | Calendar delete race | UI | **Violated** (CASA-20) | — | PG |
| K8 | Event fields well-formed | — | Pydantic (create) | PATCH explicit null | API | **Violated** (CASA-04) | — | API |
| K9 | Participants are members | — | none | API | UI/API | **Violated** (CASA-21) | — | API |
| K10 | Ex-member votes in open polls | ? | none | leave | — | **Requires product decision** (PD-H1) | — | — |
| K11 | Events are reminded | ? | not implemented | — | — | **Requires product decision** (PD-K1) | — | — |

## 7. Food & meal planning

| # | Invariant | Expected | Enforced at | Violated by | Entry | Status | Tests | Missing |
|---|---|---|---|---|---|---|---|---|
| M1 | One entry per household and date | — | UNIQUE | Concurrent PUT/decide → 500 | UI | **Partially verified** (CASA-19) | — | PG race |
| M2 | Entry has recipe or free text | — | PUT validation | Recipe delete | API | **Violated** (CASA-52) | — | API |
| M3 | Meal-poll decision does not silently replace a planned meal | ? | none (upsert) | — | UI | **Requires product decision** (PD-M1) | — | — |
| M4 | All clients show the decided meal | — | socket | `{date}` payload | Sock | **Violated** (CASA-19) | — | contract test |
| M5 | Recipe ingredients is a list | — | validator | PATCH null | API | **Violated** (CASA-04) | — | API |
| M6 | AI recipe output validated before saving | — | clipped + `RecipeCreate` | — | AI | **Verified** | `test_recipe_suggestion_can_be_saved_via_recipe_endpoint` | — |

## 8. Pets & medication

| # | Invariant | Expected | Enforced at | Violated by | Entry | Status | Tests | Missing |
|---|---|---|---|---|---|---|---|---|
| P1 | ≤ 1 feeding per pet/day/slot (household day) | 409 | UNIQUE | — | UI/Tag | **Verified** (PG) | `test_feeding_duplicate_returns_409` | — |
| P2 | Feed-all feeds every unfed pet or reports precisely | — | all-or-nothing | Concurrent single feeding | UI/Tag | **Violated** (CASA-13) | — | PG race |
| P3 | Every real dose can be recorded; duplicates are surfaced, never silently merged | — | none | UI hides button; parallel give | UI | **Violated / decision** (CASA-14, PD-P1) | — | component + API |
| P4 | Medication/feeding history is preserved and auditable | — | logs immutable individually | Delete medication/pet cascades | UI | **Violated / decision** (CASA-15, PD-P2) | — | API |
| P5 | Care completion: next due = today + interval; `notified_at` reset on due change | — | `pets.py:885-917` | — | UI/Tag | **Verified** (L-06 fixed) | `test_update_care_task_due_date_resets_notified_at` | — |
| P6 | Next due from today vs from due date; interval change recomputes due | ? | today-based | — | — | **Requires product decision** (E-1/E-2) | — | — |

## 9. Plants

| # | Invariant | Expected | Enforced at | Violated by | Entry | Status | Tests | Missing |
|---|---|---|---|---|---|---|---|---|
| PL1 | Water-all touches only due water tasks | — | `plants.py:353-361` | — | UI/Tag | **Verified** | `test_water_all_only_due_water_tasks` | — |
| PL2 | One care log per real completion | — | none | Parallel complete/water-all; repeated scans; single-plant water completes non-due task | UI/Tag | **Violated** (CASA-29) | — | PG parallel |
| PL3 | Applying AI advice never duplicates tasks; never overwrites labelled tasks; appends notes | — | `planAdvice` with fresh read | — | AI/UI | **Verified** (code + store tests) | `plants.test.ts` | — |
| PL4 | AI interval change takes effect | ? | interval only | — | AI | **Requires product decision** (E-2) | — | — |
| PL5 | Push once per due cycle | — | `_claim`, reset on due change | — | Sched | **Verified** | `test_complete_resets_notified_at` | — |

## 10. Documents & files

| # | Invariant | Expected | Enforced at | Violated by | Entry | Status | Tests | Missing |
|---|---|---|---|---|---|---|---|---|
| D1 | A file belongs to ≤ 1 of {document, pet photo, plant photo} | — | UNIQUE (documents) + `file_in_use` | Concurrent claims | API | **Violated** under concurrency (CASA-28) | `test_file_references.py` | PG race |
| D2 | A document has ≥ 1 file | 422 on last removal | `documents.py:487-494` | Orphan cleanup race | Sched | **Violated** (CASA-27, rare) | `DOCUMENT_LAST_FILE` test | interleaving |
| D3 | Household storage ≤ quota | 422 | SUM check | Parallel uploads | UI | **Violated** (CASA-26) | `test_files_upload_respects_quota` | PG parallel |
| D4 | Multi-page upload is all-or-nothing | — | rollback + storage cleanup | — | UI | **Verified** (PG) | — | — |
| D5 | Removed members cannot read files | 403 | `verify_household_access` | — | files | **Verified** | `test_files_scoping.py` | — |
| D6 | Expiry reminders re-armed only on date change | — | `documents.py:404-410` | — | Sched | **Verified** | `test_changing_expiry_resets_notifications` | — |
| D7 | Household deletion removes stored files | — | `households.py:183-194` | Orphan household (CASA-10); upload during deletion (unverified) | — | **Partially verified** | `test_last_member_leaving_deletes_household_files` | — |

## 11. Tags

| # | Invariant | Expected | Enforced at | Violated by | Status | Tests |
|---|---|---|---|---|---|---|
| G1 | Tag mutations have the same side effects as the standard workflow | — | delegation to router functions | — | **Verified** (code comparison + emits) | `test_resolve_and_execute*` |
| G2 | Token alone authorises nothing; foreign 403; disabled 410; rotated 404; deleted target 404 | — | `tags.py:236-277` | — | **Verified** | many |
| G3 | Repeated scans are idempotent | `changed=false` | per action | chore (CASA-05), care/water (CASA-29) | **Violated** | partial |
| G4 | Execute acts on the confirmed target | — | none | CASA-18 | **Violated** | — |
| G5 | Success feedback reflects reality | — | `changed` flag | feed-all race (CASA-13), care tasks always `changed:true` | **Violated** | — |

## 12. AI assistant

| # | Invariant | Expected | Enforced at | Violated by | Status | Tests |
|---|---|---|---|---|---|---|
| A1 | Daily limit per household never exceeded | — | conditional UPDATE | — | **Verified** (PG 12/20 parallel) | `test_daily_limit_*` |
| A2 | Requests rejected only when the limit is reached | — | `reserve_call` | First-row race | **Violated** (CASA-32) | — |
| A3 | Unbilled failures do not consume quota | — | release for mapped errors | Unmapped exceptions | **Partially verified** (CASA-33) | `test_sdk_errors_are_mapped_and_not_counted` |
| A4 | AI cannot mutate household data; output treated as untrusted | — | no tools; schema validation; re-validation on save | — | **Verified** | `test_user_input_is_data…` |
| A5 | Opt-in and key checked before quota reservation | — | dependency | — | **Verified** | tests |
| A6 | AI result belongs to the household it was requested for | — | none in frontend | Household switch mid-request | **Violated** (CASA-34) | — |

## 13. Cross-cutting

| # | Invariant | Status | Ref |
|---|---|---|---|
| X1 | Every socket payload inserted into a store is a full entity | **Violated** (`meal_plan_updated` from polls) | CASA-19 |
| X2 | Every server-side deletion is propagated to other clients | **Violated** (chore schedule edit, budget delete, pet cascade → dashboard) | CASA-16, CASA-42, CASA-43 |
| X3 | Concurrency never produces HTTP 500 | **Violated** | CASA-24 |
| X4 | Explicit null on non-nullable fields is rejected (422) | **Violated** | CASA-04, CASA-37 |
| X5 | Emits happen after commit | **Verified** (110 call sites) | — |
| X6 | Service worker never serves authenticated API data | **Verified** (config) | — |
| X7 | Migrated schema = models | **Verified** structurally; benign drift | CASA-56 |
| X8 | A restore reproduces the backup exactly | **Violated** | CASA-07 |
