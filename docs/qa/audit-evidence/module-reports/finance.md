# Finance audit (area: finance)

Repo state: working tree of /home/user/haushalt-app (unchanged; `git status` clean after the audit).
All scripts are in `$S/work/finance/` (S = scratchpad). Outputs: `scen.out`, `props.out`, `conc.out`.

| Script | What it does |
|---|---|
| `test_pure_props.py` (pytest + hypothesis) | Property tests on the real `split_evenly`, `validate_custom_shares` and `compute_settlements`. 7 tests pass (3000 examples each for the main ones) |
| `pg_props.py` (hypothesis on PG) | 300 random sequences of up to 25 REST operations each, on fresh households: create even/custom, PATCH amount/participants/split/payer, UI-style full-payload PATCH, delete, settlements (suggested and random), leave, join, book bill. After every step it checks, from the DB and from GET /balances, that sum(shares) equals the amount, that no share is negative, that sum(saldi) equals −unassigned, that applying the suggestions zeroes every balance, and that there are at most n−1 suggestions. **PASSED** |
| `pg_scenarios.py` | Deterministic business scenarios 1–14 (output in `scen.out`) |
| `pg_concurrency.py`, `pg_conc_detail.py`, `pg_conc_detail2.py` | Real concurrency tests with `H.parallel`, 15 rounds each |
| `pg_nulls.py` | Explicit `null` values in PATCH bodies |
| `vt/finance_store.test.ts` + `vt/vitest.finance.config.mts` | Vitest run from the scratchpad against the real `stores/finance.ts` (passes; it asserts the buggy behaviour) |

---

## 1. Inventory

| Feature / endpoint / store | Status |
|---|---|
| `GET/POST /expenses/`, `PATCH/DELETE /expenses/{id}` (`routers/expenses.py`) | Implemented and verified (pytest suite plus PG property test). **Concurrency defects:** F-01, F-02 |
| `split_evenly`, `validate_custom_shares` | Implemented and verified (hypothesis: sum equals amount, max−min ≤ 1, deterministic, duplicates rejected) |
| `GET /expenses/balances`, `services/balance_service.py`, `compute_settlements` | Implemented and verified (hypothesis on the pure function and on PG). Greedy, not minimal (documented) |
| `GET/POST/DELETE /settlements/` | Implemented and verified for balance effect. No idempotency and no plausibility check (F-03) |
| `PUT/GET/DELETE /budget` | Implemented and verified for single requests. Concurrent first PUT gives 500 (F-09) |
| `/recurring-bills/` CRUD + `POST /{id}/book` | Implemented and verified. Booking is exactly-once under 8-way concurrency on PG. Gaps: F-04, F-07, E-5 |
| `GET /finance-summary` (`routers/households.py:310`) | Implemented and verified (month boundaries 31.12→1.1, 29.2.2028, settlements excluded, bills matched via `booked_month`). Edge 500 (F-13) |
| Dashboard finance (`routers/dashboard.py:258`, `compute_user_saldo`) | Implemented and verified (dashboard saldo equals the /balances saldo, scenario 12) |
| `widget.py` | No finance content (grep) |
| Leaving or being removed with a balance (`households.py:161`, `:224`) | Implemented and verified (existing tests plus property test with leave/join) |
| User account deletion | **Not implemented** (no code path). FK rules make it a latent ledger corruption (F-18) |
| Change of household currency | **Not implemented** (no endpoint; `HouseholdUpdateRequest` holds only `name`). Currency is effectively always the default CHF |
| Frontend `stores/expenses.ts`, `stores/settlements.ts` | Implemented. Server-wins merge, no version guard. Behaviour checked only by code reading, beyond the existing `expenses.test.ts` |
| Frontend `stores/finance.ts` | Partial. Budget and bill socket handlers update the summary wrongly or not at all (F-11, verified by vitest) |
| `ExpenseFormDialog.vue` | Implemented. Always sends the full payload (gives lost updates, F-02); the category cannot be cleared (F-15) |
| `ExpensesView.vue` | Implemented. Only the first 100 expenses and 100 settlements are visible (F-06); Undo is unsafe (F-04). **There is no UI to create, edit or delete recurring bills.** `PROJECT-STATUS.md:306` claims a "Rechnungsverwaltung" (bill management) here, so the **docs disagree with the implementation** (F-07) |
| `BalanceSummary.vue` | Implemented. Settlement dialog with a double-submit guard per device only (F-03) |

## 2. Invariants

| Invariant | Where enforced | Operations that can violate it | Status | Existing tests | Missing tests |
|---|---|---|---|---|---|
| I1: SUM(shares.amount) == expense.amount | Service layer only: `expenses.py:303/307/435/443`, `recurring_bills.py:261`. No DB constraint | **Concurrent PATCH (F-01)**; user hard delete (F-18, latent) | **Violated** under concurrency (PG: 10 of 10 rounds); Verified for all sequential paths (300 random sequences) | `test_shares_always_sum_to_amount`, split tests | PG concurrency test; DB-level check (deferred constraint trigger) |
| I2: shares ≥ 0, amount > 0, settlement > 0, from ≠ to | DB CHECK constraints (`models.py:407,460,487-488`) plus pydantic | none found | Verified | settlements tests | – |
| I3: amounts fit int32 | nowhere (pydantic only `gt=0`) | any create/PATCH ≥ 2^31 | **Violated** (500, F-08) | – | boundary test |
| I4: Σ saldo + unassigned == 0 (precisely: Σ saldo == −unassigned) | follows from I1 | F-01 (Σ saldo = −1000 with unassigned 0); F-18 | Violated under F-01, otherwise Verified | `test_balances_unassigned_payer` | property test |
| I5: applying the suggestions zeroes all balances; ≤ (non-zero users − 1) transfers; only debtors pay | `compute_settlements` (`expenses.py:169`) | none (when Σ ≠ 0 it never overshoots and only one side remains) | Verified (hypothesis, n up to 5000) | `test_expense_balances.py` | – (now covered by `test_pure_props.py`) |
| I6: a recorded settlement affects balances exactly once | `balance_service.py:62-78` | duplicate recording by two people (F-03) | Verified for the math; **duplicates not prevented** | `test_settlement_zeroes_out_balances` | idempotency test |
| I7: one booking per bill and month | UNIQUE `(recurring_bill_id, booked_month)` (`models.py:410`), `recurring_bills.py:239-300` | Undo re-creates the expense without the link (F-04); delete then rebook (allowed by design) | Verified on PG (8 threads × 15 rounds → one 201 and seven 409); **bypassed via Undo** | `test_book_idempotent_409` | PG concurrency test; undo scenario |
| I8: one budget per household and month | UNIQUE `uq_budget_household_month` | concurrent first PUT gives 500 (no dup row) | Verified (no duplicates), but the error is 500 | `test_budget_upsert_updates_existing` | concurrency test |
| I9: participants and payer are members, or ex-members already on the record | `household_checks.py` | – | Verified | `test_finance_correctness.py` | – |
| I10: expense currency == household currency | `expenses.py:276`, `settlements.py:~94` | currency change (no endpoint) | Verified | `test_currency.py` | – |
| I11: summary total == Σ expenses with `expense_date` in the month (household month) | `households.py:340-365` | – | Verified (scenario 12) | `test_finance_summary.py` | Feb/Dec boundary tests |

## 3. Findings

### F-01: Concurrent PATCH duplicates expense shares, breaking balances (sum(shares) = 2 × amount)
- **Severity:** High · **Class:** A · **Modules:** `routers/expenses.py` update/delete
- **Refs:** `expenses.py:355` (`db.get` without a lock), `:447-458` (`expense.shares.clear(); db.flush()` then insert)
- **Observed:** Two parallel `PATCH {participant_ids}` on the same expense with disjoint sets: both return **200**, and the expense ends up with **4 shares of 500 on an amount of 1000**. Balances then sum to −1000 with `unassigned=0`, so a creditor gets nothing and everyone is charged twice. With overlapping participants or amount changes, one request gets **500** (`IntegrityError uq_expense_share_user`). DELETE ‖ PATCH gives a **500 `DeadlockDetected`** or **`StaleDataError`**.
- **Evidence:** `pg_conc_detail.py`: `round 1: amount=1000 shares=[500, 500, 500, 500] n=4 sum(saldi)=-1000 unassigned=0` (9 of 10 rounds); `outcomes: {200: 20}`. `pg_concurrency.py` c): `{((200,2),(500,2)), False): 12 …} violations: [(1000, 2000, 4) …]`. `pg_conc_detail2.py`: `7 PATCH||PATCH IntegrityError … uq_expense_share_user`, `2 DELETE … DeadlockDetected`.
- **Root cause:** No row lock or version on `expenses`. Each transaction deletes the share rows it loaded. The second DELETE matches 0 rows, which SQLAlchemy only warns about, and both transactions insert their new shares.
- **Expected:** Serialized updates: sum(shares) == amount always; a conflict returns 409, never a silent corruption.
- **Repro:** Create an even expense with 4 members. Send two PATCH requests at the same time, `participant_ids=[A,B]` and `[C,D]`.
- **Impact:** Silent, persistent wrong debts. Realistic triggers are two devices saving, a client retry while the first request is still running, or two members editing. A later reshare-PATCH repairs it (it clears all shares), but nobody notices.
- **Fix:** At the start of PATCH and DELETE, run `db.query(Expense).filter_by(id=…).with_for_update().one_or_none()`. Add a `version` column with `If-Match`/409. Optionally add a deferred constraint trigger that checks Σshares = amount at commit. Map IntegrityError and OperationalError to 409.
- **Regression test:** PG test, 2 to 4 parallel PATCH (participants, amount) plus DELETE ‖ PATCH. Assert Σ = amount and that the status is in {200, 404, 409}.
- **Confidence:** High.

### F-02: Lost update. The edit dialog always sends the full payload, so a stale dialog overwrites another member's change
- **Severity:** Medium · **Class:** E (`version` missing on `expenses` is documented in `PROJECT-STATUS.md:663,892` as Phase 2, but here the impact is on money)
- **Refs:** `ExpenseFormDialog.vue:221-231` (sends description, amount, payer, date, split, participants every time); `expenses.py:362` (`exclude_unset`, no version)
- **Observed:** Ben changes the amount 100.00 → 250.00. Anna then saves a description change from a dialog she opened earlier, and the amount goes back to **100.00** silently (scenario 5: `Ben patch=200 amount=25000; Anna stale patch=200 -> final amount=10000`). When both save in parallel, the result is a field-wise mix (`h) final: A edit 2000`).
- **Expected:** 409 or a warning when the expense changed since the dialog opened, or the client sends only the fields it changed.
- **Fix:** Add `version` (or an `updated_at` precondition) to `expenses`. Short term, have the dialog send only changed fields.
- **Test:** PG/API: stale full payload after a concurrent change gives 409. Vitest: the dialog diff payload.
- **Confidence:** High.

### F-03: Same payment recorded twice (no idempotency, no plausibility check), so the debt flips to the other person
- **Severity:** Medium · **Class:** B/C · **Refs:** `settlements.py:76-122`; `BalanceSummary.vue:73-103` (the guard is per dialog instance only)
- **Observed:** Debtor and creditor both press "Ausgleichen" (settle) on the same suggestion: **201, 201**. Result: Anna −25.00, Ben +25.00, and a new suggestion "Anna → Ben 25.00" (scenario 4). On PG with parallel requests, 15 of 15 rounds gave two rows (`a) {(((201, 2),), 2): 15}`). Overpayment is also accepted (debt 5.00, recorded 999.99 → 201, scenario 3), as is a "settlement" against the direction of the debt (3b).
- **Impact:** A very likely real-world flow ("Ich hab's eingetragen" / "ich auch", "I entered it" / "me too") creates a reversed debt. Users then "settle back", which doubles the noise.
- **Fix:** Accept a client-generated id (`services/client_ids.py` exists for other modules) to make retries idempotent. Warn, or require confirmation, when the amount exceeds the current |debt| between the two parties, or when an identical settlement (same from/to/amount/date) exists from the last few minutes. Show "erfasst von X" (recorded by X) in the list (`created_by_user_id` already exists).
- **Test:** API: two identical POSTs → second is 409 or flagged. PG parallel test.
- **Confidence:** High.

### F-04: Undo after deleting an expense is unsafe: a booked bill can be booked twice, and ex-member expenses cannot be restored
- **Severity:** Medium · **Class:** A · **Refs:** `ExpensesView.vue:201-223` (undo = `addExpense` without `recurring_bill_id`/`booked_month`, without the original payer check); `recurring_bills.py:239-248`
- **Observed:**
  - (8b) Delete the booked "Internet" expense, then Undo. Undo returns 201 with `recurring_bill_id=None`, the pending bill shows `('Internet', False)`, and a second book returns **201**. The month then holds **2 "Internet" expenses** (`total_spent=12000`).
  - (10) An expense paid by ex-member Carla, who is owed 200.00, is deleted by Anna. Undo returns **422 USERS_NOT_IN_HOUSEHOLD**. Carla's claim is gone (`after={'Anna': 0, 'Ben': 0}`) with no way back except manual reconstruction.
- **Fix:** Use a server-side soft delete with a restore endpoint, or a delayed delete (commit only after the undo window). At minimum, carry `recurring_bill_id`/`booked_month` through the re-create (needs an API field) and allow ex-members on restore.
- **Test:** API scenario 8b/10 as PG integration tests. Vitest that the undo payload keeps the link.
- **Confidence:** High.

### F-05: Any member can edit or delete any expense or settlement, including erasing their own debt, with no audit trail
- **Severity:** Medium · **Class:** C (deliberate "nur admin/member", `PROJECT-STATUS.md:718`) plus E (no audit)
- **Refs:** `expenses.py:347-495`, `settlements.py:126-147` (only `verify_household_access`); `Expense` has no `created_by_user_id`/`updated_by` (`models.py:400-455`); deletes are hard deletes.
- **Observed:** Debtor Ben deletes Anna's 2000.00 rent and both balances go to 0 (scenario 1). Carla, who is not a party, deletes the Anna→Ben settlement and gets 204 (scenario 14). Afterwards nobody can tell who did it.
- **Fix (decision P-1):** At least record `created_by`/`updated_by`, use soft delete with a visible history ("gelöscht von Ben", deleted by Ben), and notify the payer.
- **Confidence:** High.

### F-06: Expenses and settlements beyond the newest 100 are invisible in the UI, but still count in the balances
- **Severity:** Medium · **Class:** A
- **Refs:** `expensesRepository.ts` and `settlementsRepository.ts` `fetchAll(hid)` without params; backend default `limit=100` (`expenses.py:231`, `settlements.py` list); no "load more" in `ExpensesView.vue` (grep `offset` returns no match).
- **Impact:** After a few months of normal use (about 5 expenses per week), older expenses cannot be found, edited or deleted, and balances cannot be reconciled against the list.
- **Fix:** Paginate or load more. Add a "Zeitraum"/month filter (period/month filter) that matches the finance summary.
- **Evidence:** Code reading only. **Confidence:** High.

### F-07: Recurring bills have no management UI; the pending-bill card goes stale on other members' bill changes
- **Severity:** Low–Medium · **Class:** Docs inconsistent with implementation (G or A)
- **Refs:** `stores/finance.ts:78-123` (`createBill`/`updateBill`/`removeBill`) are not called by any `.vue` (grep). `PROJECT-STATUS.md:306` says ExpensesView offers "Rechnungsverwaltung" (bill management). `finance.ts:154-168` update `bills` but not `summary.pending_bills`, which is what `ExpensesView.vue:135-145,380-415` renders.
- **Evidence:** Vitest `finance_store.test.ts` (2nd test): after `handleBillUpdated(amount 9000)`, `handleBillCreated(b2)` and `handleBillDeleted(b1)`, `pending_bills` is still `[[b1, 6000]]`.
- **Impact:** Bills can only be created through the API. Another member's change shows a stale amount, or a deleted bill whose "Buchen" (book) action returns 404, until reload.
- **Fix:** Build the bill management UI or correct the docs. Refetch the summary on `recurring_bill_*` events.
- **Confidence:** High.

### F-08: Amounts ≥ 2^31 Rappen give 500 (int32 columns, no upper bound)
- **Severity:** Low · **Class:** A · **Refs:** `models.py` `Integer` amount columns; pydantic `gt=0` only (`expenses.py:29`, `settlements.py SettlementCreate`, `budgets.py BudgetUpsert`, `recurring_bills.py:26`)
- **Evidence:** scenario 7: `amount=2147483648 → 500`, `10**12 → 500`, and likewise for settlement, budget and bill (`7b/7c/7d → 500`, psycopg2 `NumericValueOutOfRange`). Aggregates are safe (sum is bigint: `paid_rappen 4294967294`, status 200).
- **Fix:** Add `Field(le=…)`, for example 10^9 Rappen, or use BigInteger. **Confidence:** High.

### F-09: Concurrent first `PUT /budget` gives 500
- **Severity:** Low · **Class:** A · **Refs:** `budgets.py:67-105` (check-then-insert)
- **Evidence:** `pg_conc_detail2.py`: `8 PUT budget 201`, `8 PUT budget IntegrityError … uq_budget_household_month` (one 500 per round). No duplicate row.
- **Fix:** Use `INSERT … ON CONFLICT (household_id, month) DO UPDATE`. **Confidence:** High.

### F-10: Explicit `null` in PATCH bodies gives 500
- **Severity:** Low · **Class:** A · **Refs:** `expenses.py:384-391` (`setattr` with None), `recurring_bills.py:156-157`
- **Evidence:** `pg_nulls.py`: `{'description': None} -> 500`, `{'expense_date': None} -> 500`, and bill `name/amount_rappen/active/day_of_month: None -> 500`. The UI never sends these.
- **Fix:** Reject None for non-nullable fields (validator) and return 422. **Confidence:** High.

### F-11: `budget_updated` handler ignores the month; `budget_deleted` is unhandled
- **Severity:** Low · **Class:** A (`budget_deleted` is D, documented in `PROJECT-STATUS.md:605`)
- **Refs:** `stores/finance.ts:143-152`
- **Evidence:** Vitest: with the October summary loaded, a November `budget_updated` event (5000) gives `summary.budget_rappen === 5000` and `remaining` recomputed against October spending.
- **Impact:** The wrong "Noch verfügbar" (still available) figure until reload. Only reachable via the API or clients whose month differs (see F-16).
- **Fix:** Compare `data.month === summary.month`; handle `budget_deleted`. **Confidence:** High.

### F-12: PATCH semantics surprises (API only)
- **Severity:** Low · **Class:** C · **Refs:** `expenses.py:418-432`, `:289-300`
- **Observed:** `PATCH {split_type:"even", description}` on an even expense split among 2 of 3 members re-splits it across **all 3 current members** (6a). `POST` with `participant_ids: []` silently means "all members" (6b). The UI is not affected, because it always sends `participant_ids`.
- **Fix:** Keep existing participants when `split_type` is unchanged; reject `[]` with 422. **Confidence:** High.

### F-13: No plausibility bounds on dates; `finance-summary?month=9999-12-01` gives 500
- **Severity:** Low · **Class:** A · **Refs:** `households.py:329` (`date(month.year + 1, 1, 1)` overflows)
- **Evidence:** scenario 13: `expense_date 0001-01-01 → 201`, `9999-12-31 → 201`; summary for 9999-12 returns 500.
- **Fix:** Bound `expense_date`/`settled_date` (for example ±10 years) and validate `month`. **Confidence:** High.

### F-14: Edit dialog cannot remove a category
- **Severity:** Low · **Class:** A · **Refs:** `ExpenseFormDialog.vue:227` (`category: selectedCategory.value || undefined`) means the key is omitted, and the backend `exclude_unset` keeps the old value. Explicit `null` works server-side (`pg_nulls.py`: `{'category': None} -> 200`).
- **Evidence:** Code reading plus API check. **Confidence:** High.

### F-15: Frontend uses device time, not household time, for dates and months (residual of L-01)
- **Severity:** Low · **Class:** A/F · **Refs:** `ExpenseFormDialog.vue:145` and `BalanceSummary.vue:69` (`localDateString()`, always sent, so the server default `household_today` is never used from the UI); `ExpensesView.vue:111-113` (budget month from `new Date()`), `:141-155` (`nextBillId`).
- **Impact:** Only when the device timezone differs from the household timezone, for example while travelling. In that case the expense date or budget month is off by one around midnight. **Confidence:** High (code reading).

### F-16: Finance view always formats amounts as CHF
- **Severity:** Low · **Class:** D/E (latent) · **Refs:** `ExpensesView.vue:307-574`, `BalanceSummary.vue:32-155`, `ExpenseFormDialog.vue:387` call `formatRappen(x)` with the default `'CHF'`; `DashboardView.vue:121` passes `finance.currency`. Not reachable today because no currency can be set (see Inventory).

### F-17: Editing or deleting an expense after a settlement silently reopens and reverses debts
- **Severity:** Medium (business), but a product decision · **Class:** C
- **Evidence:** scenario 2: after settling, all balances are 0. `PATCH amount 100→60` gives Anna −20, Ben +20 and a suggestion "Anna→Ben 20". DELETE gives Anna −50, Ben +50. The response carries no warning or flag, and there is no history.
- **Fix:** See P-2. **Confidence:** High.

### F-18 (latent): Hard-deleting a user would corrupt the ledger
- **Severity:** Low today (no deletion path in `app/` or `scripts/`) · **Class:** E
- **Refs:** `models.py:477` `expense_shares.user_id ondelete=CASCADE`, `:499,:502` `settlements.from/to_user_id CASCADE`, `:431` `paid_by SET NULL`. DB confirmed (`confdeltype c/c/c/n`).
- **Evidence:** scenario 11 (simulated `DELETE FROM users`). Before: Σsaldi 0, unassigned 0. After: **Σsaldi 1000, unassigned 3000**, and expenses `('A', 9000, shares 6000), ('C', 3000, 2000)`. Settlements with Carla are gone too, and the frontend cannot edit expenses whose payer is NULL (`ExpenseFormDialog` `canSubmit` needs a payer).
- **Fix:** Before any GDPR or account-deletion feature, switch to RESTRICT or SET NULL and anonymise users instead of deleting them. Add a test that pins the FK rules.

### F-19: Settlement suggestions are not minimal (documented)
- **Severity:** Low · **Class:** D · Greedy finds 5 transfers where 4 suffice for saldi `[5, 6, 3, -3, -6, 6, -11]` (`test_greedy_not_minimal_example`). The ≤ n−1 bound and correctness are verified; n=5000 runs in 0.55 s.

### Verified correct (no defect)
- `split_evenly`: sum equals amount, fair within 1 Rappen, deterministic regardless of input order, duplicates rejected.
- Custom shares: the sum is validated exactly, zero shares are allowed, duplicates are rejected.
- 300 random REST sequences on PG (including leave, join, bill booking, payer changes, UI full-payload edits with ex-members): I1, I2, I4 and I5 always held. No 500 occurred sequentially.
- Bill booking is exactly-once under 8-way concurrency (`b) {((201,1),(409,7)), 1): 15}`). Inactive bills give 409. Payer defaulting and override work. A payer who has left gives 422 (the UI preselects the current user, `ExpensesView.vue:159-165`). Members who joined later are included at booking time (Carla 5000/5001). `expense_date` = the bill's day in the current household month.
- Delete then rebook within the same month is allowed (8a, 201). That is consistent with the "booked = an expense exists" rule.
- Finance summary, budget, dashboard and balances agree. The month boundaries 31.12/1.1 and 29.2/1.3.2028 are correct, and settlements are excluded from spending (scenario 12).
- Ex-member debts stay visible and can be settled; old expenses with ex-members stay editable (property test with the full payload: 86 of 86 returned 200).

## 4. Prior review status (finance items)

| Item | Status now |
|---|---|
| L-01 (month and date by UTC) | **Fixed server-side** (`household_today` used in `recurring_bills.py:234`, `budgets.py:119`, `households.py:318`, `expenses.py:317`, `settlements.py:109`). Residual in the frontend: the device date is always sent (F-15) |
| L-02 (booked custom bill becomes an even expense) | **Fixed**: `recurring_bills.py:276` `split_type="even"`; test `test_booked_expense_of_custom_bill_is_even_and_editable` |
| E-5 (`RecurringBill.split_type` without effect) | **Still open**: `custom` is accepted and stored but has no effect (scenario 9c: 201, `split_type=custom`) |
| Logic-review §1 rows (even/custom split, duplicates, sign, settlement, greedy, unassigned, leave with balance, ex-member edit, amount change keeps subset, currency, bill delete SET NULL, remove member with saldo, budget month boundary) | All **re-verified OK** (tests plus property test). "Ausgaben ohne Zahler (User gelöscht)" (expenses without payer, user deleted) is rated "ok" in the review, but the shares CASCADE means the "unassigned" model is incomplete, so Σsaldi ≠ −unassigned → see F-18 |

## 5. Cross-module effects

| Source op | Dependent entities | What can become inconsistent |
|---|---|---|
| Concurrent expense PATCH | expense_shares → balances → dashboard saldo → settlement suggestions | Duplicate shares; balances no longer sum to 0 (F-01) |
| Expense delete (any member) | balances, finance summary, recurring-bill "booked" flag | Debt erased; bill becomes bookable again; Undo re-creates it without the link, so two bookings are possible (F-04) |
| Expense edit or delete after a settlement | balances, suggestions | Debt reverses silently (F-17) |
| Settlement POST twice | balances | Reversed debt (F-03) |
| Leave or remove member | even split defaults, bill booking, payer default | Ex-member is excluded from new bookings (correct); a bill whose default payer left needs an override (UI handles it) |
| Last member leaves | everything | Whole ledger deleted (documented `PROJECT-STATUS.md` "Haushalt verlassen" (leave household)) |
| User hard delete (latent) | shares (CASCADE), settlements (CASCADE), payer (SET NULL) | Ledger corruption (F-18) |
| Bill create, update or delete by another member | `finance.summary.pending_bills` (frontend) | Stale card (F-07) |
| `budget_updated` for another month | `finance.summary` | Wrong budget figure (F-11) |

## 6. Test gaps

| Scenario | Recommended type |
|---|---|
| Parallel PATCH ‖ PATCH and PATCH ‖ DELETE on one expense; Σshares == amount | PG integration (`H.parallel`) |
| Parallel identical settlements / idempotency key | PG integration |
| Parallel bill booking (exists only on SQLite single session) | PG integration |
| Parallel first `PUT /budget` | PG integration |
| Stale full-payload edit (lost update) | API |
| Ledger invariants under random op sequences | Property-based (port `pg_props.py`) |
| `compute_settlements` properties (zeroing, ≤ n−1, no overshoot when Σ≠0) | Property-based (port `test_pure_props.py`) |
| Undo of a booked-bill expense and of an ex-member expense | API plus vitest |
| Amount upper bound, explicit nulls, `month=9999-12-01` | API |
| `finance.ts` socket handlers (budget month, bill events → summary) | Vitest |
| Expense list beyond 100 entries | E2E or vitest |
| FK rules for users (guard against future account deletion) | Migration or schema test |

## 7. Product decisions

| # | Question | Options | Recommendation |
|---|---|---|---|
| P-1 | Who may edit or delete an expense or settlement? | a) every member (today) · b) creator, payer or admin only · c) everyone, but soft delete plus a visible history and a notification to the payer | **c**: keeps the flat household model and makes debt erasure visible |
| P-2 | Edit or delete of expenses dated before the last settlement | a) silently allowed (today) · b) allowed with a warning "Salden ändern sich nachträglich" (balances will change retroactively) · c) locked after settlement | **b** |
| P-3 | Settlement plausibility | a) accept anything (today) · b) warn when amount > current debt between the two parties or an identical one exists · c) hard reject | **b**, plus a client idempotency key |
| P-4 | Retroactive booking of a missed bill month | a) current month only (today) · b) allow `month` parameter (past months) | **b**: otherwise a forgotten month can only be entered as an unlinked manual expense |
| P-5 | E-5 `RecurringBill.split_type` | a) remove the field · b) model shares per bill · c) reject `custom` | **c** short-term, **a** with the bill UI |
| P-6 | Refunds or credits (negative amounts are impossible: CHECK > 0) | a) model a refund as a settlement or a custom expense paid by the refunding person (today: workaround) · b) add `kind=refund` | a is sufficient if documented in the UI help |

## 8. Unverified

- Frontend socket ordering races (an HTTP response for an older state arriving after a newer `expense_updated` event; responses after a household switch in `fetchExpenses`/`fetchBalances`, which have no generation guard): reasoned from code only. Impact is limited because balances are always refetched.
- Multi-worker deployment effects on socket delivery: out of scope (single worker is documented).
- The real iPhone or browser UI flows (Undo toast, double tap): not run in a browser. F-04 is verified through the equivalent API calls the undo handler makes (`ExpensesView.vue:212-221`).
- F-06 (100-row cap) is verified by code reading only. No dataset with more than 100 rows was loaded through the UI.
