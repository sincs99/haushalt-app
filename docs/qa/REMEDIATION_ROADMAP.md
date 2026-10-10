# Remediation Roadmap

**Date:** 2026-10-10 · Companion to [FULL_LOGIC_AUDIT.md](FULL_LOGIC_AUDIT.md) and
[PRODUCT_DECISIONS.md](PRODUCT_DECISIONS.md).

Priorities: **P0** immediate security, data loss or financial correctness · **P1** broken essential workflows and
major consistency problems · **P2** reliability, maintainability, UX · **P3** optional enhancements.
Effort: **S** ≤ 1 day · **M** 2–5 days · **L** > 1 week (one developer, including tests).

Rule for every item: write the regression test from TEST_GAP_MATRIX.md first and show it failing.

---

## Foundation (do first — several items depend on it)

| ID | Item | Effort | Enables |
|---|---|---|---|
| F0-1 | **PostgreSQL integration test lane** in CI: `postgres:16` service, `alembic upgrade head`, a `pg` pytest marker with a per-request-session client (port `audit-evidence/pgharness.py`), `H.parallel` helper | M | every concurrency fix below (otherwise none of them can be regression-tested) |
| F0-2 | Shared backend helpers: `lock_household(db, id)` (`SELECT … FOR UPDATE`), `lock_row(model, id)`, and a global `IntegrityError`/`StaleDataError` → 409 exception handler (safety net) | S | P0-1, P1-1, P1-3, P1-8, P1-10 |
| F0-3 | Generic "explicit null on non-nullable field → 422" validator for all `*Update` schemas; `JSON(none_as_null=True)` on NOT NULL JSON columns | S | P0-3, CASA-37 |

## P0 — immediate

| ID | Item | Findings | Depends on | Effort |
|---|---|---|---|---|
| P0-1 | Lock expense row in PATCH/DELETE; add `version` to `expenses` (SyncVersionMixin) and `If-Match` → 409; map integrity errors to 409 | CASA-01, part of CASA-09 | F0-1, F0-2 | M |
| P0-2 | Undo of expense deletion: server-side soft delete + restore endpoint keeping `recurring_bill_id`/`booked_month` and ex-member participants (or, as a stop-gap within a day: no Undo for booked/ex-member expenses, confirm dialog instead) | CASA-03 | PD-F1 (soft delete) for the full fix; stop-gap none | S (stop-gap) / M |
| P0-3 | Reject explicit nulls; repair any JSON `null` already stored (`UPDATE events SET participant_ids='[]' WHERE participant_ids::text='null'`, same for `recipes.ingredients`) | CASA-04 | F0-3 | S |
| P0-4 | Chore tag: "current period" independent of completion; `ALREADY_DONE` on repeat; return assignment id from resolve and require it on execute | CASA-05, CASA-18 | — | S–M |
| P0-5 | Todo reopen keeps reminders: stop marking reminders on completion (scheduler already skips done todos) or reset future ones on reopen; hide bell when `notified_at` set | CASA-06 | — | S |
| P0-6 | Restore procedure: stop backend, recreate schema/DB, `pg_restore --single-transaction --exit-on-error`, fail on non-zero exit; document "rollback = old code + old dump"; rehearse once | CASA-07 | PD-D2 | S |
| P0-7 | Feed-all: per-pet `ON CONFLICT DO NOTHING RETURNING`; report created rows; UI says "all fed" only if the refreshed status confirms it | CASA-13 | F0-1 | S |

**Decisions to take in the same iteration (no code before they are taken):** PD-F1, PD-F2, PD-F3 (they define
what a financial record is and determine P1-2/P1-4).

## P1 — essential workflows and consistency

| ID | Item | Findings | Depends on | Effort |
|---|---|---|---|---|
| P1-1 | Membership transactions under `lock_household`: re-count after delete; auto-promote when no admin remains; delete household at 0 members (and a periodic sweep for existing 0-member households incl. files); map `StaleDataError` → 409 | CASA-10 | F0-2, PD-H3 | M |
| P1-2 | Financial audit trail: `created_by/updated_by/deleted_by` on expenses, soft delete for expenses and settlements, history visible in ExpensesView, warning on retroactive change | CASA-02 | PD-F1, PD-F2, P0-1 | L |
| P1-3 | Refresh-token rotation in one commit with a row lock; grace path follows the replacement chain | CASA-11 | F0-1 | S–M |
| P1-4 | Settlement idempotency key (`client_ids.py`) + plausibility warning + show "erfasst von" | CASA-08 | PD-F3 | S–M |
| P1-5 | Frontend session isolation: household/session generation counter checked after every await in all stores; reset all stores on logout and on any `currentHouseholdId` change (incl. `null`); unsubscribe push on silent session end | CASA-12, CASA-47, CASA-50, CASA-34 (AI part) | — | M |
| P1-6 | Chore transitions: clamp materialisation to `anchor_date`; emit assignment deletions on schedule change; on pause delete open future assignments (or filter `Chore.active` in push/attention/dashboard/tasks); re-anchor on reactivation | CASA-16, CASA-17 | PD-C1 | M |
| P1-7 | Meal-poll decide emits full `MealPlanEntryResponse`; confirm/409 on occupied date; `ON CONFLICT` for meal plan PUT; socket contract test for all emits | CASA-19 | PD-M1, F0-1 | S–M |
| P1-8 | Calendar delete/create/decide under a calendar row lock; FK `RESTRICT` + `passive_deletes` instead of ORM cascade | CASA-20, CASA-54 | F0-2 | S |
| P1-9 | Membership validation for todo assignees, event participants (dedupe), event-poll recipes (allow ex-members already on record) | CASA-21 | — | S |
| P1-10 | Concurrency → 409 everywhere: budget and meal plan via `ON CONFLICT DO UPDATE`; register/join/widget token/document claim/item-into-deleted-list mapped to 409/404 | CASA-24 | F0-2 | M |
| P1-11 | Departure consistency: attention/widget/dashboard treat ex-member assignees as unassigned; clear default bill payer; delete widget tokens on leave/remove; (later) clean assignees/rotation/open-poll votes in the leave transaction | CASA-22 | PD-H1, P1-1 | S (first step) / M |
| P1-12 | Medication: keep "give" available with last-dose info and confirmation; client id for give; block deletion with logs (offer deactivate); archive state for pets | CASA-14, CASA-15 | PD-P1, PD-P2 | M |
| P1-13 | Expense/settlement pagination or month filter | CASA-23 | — | S–M |
| P1-14 | Lost updates: dialogs send only changed fields (expenses, notes, shopping sheet, todos) | CASA-09 | — (P0-1 adds 409 for expenses) | S |
| P1-15 | Test lanes: CI drift check + newest-migration downgrade/upgrade; property tests (finance, scheduler); first E2E suite with two browser contexts (6 journeys from TEST_GAP_MATRIX #30) | CASA-25, CASA-56 | F0-1 | L |

## P2 — reliability, maintainability, UX

| ID | Item | Findings | Effort |
|---|---|---|---|
| P2-1 | Tag/care idempotency per household day; `plant.water` with target completes only due tasks; feed tag allows any unfed slot; parallel `todo.done` via conditional update | CASA-29, CASA-31 | S–M |
| P2-2 | Files: quota under household lock or counter; exclusive file ownership with row lock; guarded orphan cleanup; write-then-commit cleanup of disk orphans | CASA-26, CASA-27, CASA-28 | M |
| P2-3 | Realtime contract fixes: emit on scheduler materialisation; bump todo version on reminder changes; handle `join_household` error; `household_member_joined` on register; refresh member lists; `budget_deleted` and budget month check; refresh `pending_bills` on bill events; dashboard/badge invalidation for chore/pet/calendar events | CASA-42, CASA-43, CASA-46 | M |
| P2-4 | Do not reload all stores on token refresh; treat DELETE 404 as success; keep unconfirmed creates instead of rolling back | CASA-44, CASA-45 | S–M |
| P2-5 | Push URLs carry household id and switch household on open; badge per current household | CASA-40 | S |
| P2-6 | Reconnect and 403 `NOT_HOUSEHOLD_MEMBER` trigger `/me`; socket `reauth` re-checks membership | CASA-48, CASA-49 | S |
| P2-7 | Household date in the frontend (from `/me`); `Todo.due_date` as `Date` (migration) | CASA-39 | M |
| P2-8 | DST gap handling for events; poll option times in household time; require time for event-poll options | CASA-35, CASA-60 | S |
| P2-9 | Amount and date bounds (`le=10^9` Rappen, ±10 years); category clearable in the dialog | CASA-36, CASA-38 | S |
| P2-10 | AI: `INSERT … ON CONFLICT` reservation; map all `anthropic.APIError` and release on unexpected exceptions; AI "missing ingredients" via backend bulk endpoint | CASA-32, CASA-33, CASA-34 | S |
| P2-11 | Food: recipe delete keeps name as free text; lock list for "missing ingredients"; one default-list creation | CASA-52, CASA-53 | S |
| P2-12 | Operations: off-host backup, consistent DB+uploads snapshot (stop or quiesce), restore drill per release, alerting on `/api/health`, Docker log rotation, configurable trusted proxy range, `npm run build` (with typecheck) in the frontend image | CASA-57 | M |
| P2-13 | PWA update: periodic `registration.update()` on visibility change, persistent "Update verfügbar" | CASA-41 | S |
| P2-14 | Migrations hygiene: fix downgrade of `0f34ff355756`, `SET NOT NULL` for `created_at` columns, add server defaults to models | CASA-56 | S |
| P2-15 | Documentation corrections (counts, heads, tables, socket table, bill/recipe UI claims, tag file names, admin list); document reminder delivery semantics after downtime (PD-D3) | CASA-58 | S |
| P2-16 | Account-deletion readiness: FK rules RESTRICT for ledger, anonymisation design | CASA-55, PD-D1 | M |

## P3 — optional enhancements

| ID | Item | Source | Effort |
|---|---|---|---|
| P3-1 | Recurring bill management UI (create/edit/delete) and retro-booking of missed months | CASA-58, PD-F4, PD-F5 | M |
| P3-2 | Recipe create/edit UI | CASA-58 | M |
| P3-3 | Event reminders | PD-K1 | M |
| P3-4 | Rotation member add/remove in the UI | PD-C3 / L-16 | S |
| P3-5 | Duplicate-item hint on shopping add; structured quantities later | PD-S1, PD-S2 | S / L |
| P3-6 | "Erledigt von"/"abgehakt von" attribution for todos and shopping | UX | S |
| P3-7 | AI advice: per-task old→new preview; per-user AI limit | PD-P5, PD-A2 | S |
| P3-8 | Backend i18n for generated labels | CASA-59 | S |
| P3-9 | Dashboard multi-day events; dashboard shows overdue chores; remove unused `/tasks` | PD-K3, PD-C2 | S |
| P3-10 | Offline M1+ prerequisites: tombstones for client ids, "404 on DELETE = success", outbox with stable ids | offline-first-phase2, CASA-45 | L |

## Dependency graph (simplified)

```
F0-1 (PG CI lane) ──┬─> P0-1 ─> P1-2 (audit trail) ─> P0-2 (full undo fix)
                    ├─> P0-7, P1-3, P1-7, P1-10, P1-15
F0-2 (lock helpers) ┼─> P0-1, P1-1 ─> P1-11 (departure cleanup)
                    └─> P1-8, P1-10
F0-3 (null rule) ───> P0-3
PD-F1/F2/F3 ───────> P1-2, P1-4, P0-2 (full)
PD-C1 ─────────────> P1-6
PD-P1/P2 ──────────> P1-12
PD-H1/H3 ──────────> P1-1, P1-11
```

## Suggested sequencing

1. **Iteration 1 (≈ 1 week):** F0-1, F0-2, F0-3, P0-1 … P0-7 (stop-gap for P0-2); take decisions PD-F1/F2/F3, PD-H1/H3, PD-C1, PD-P1/P2, PD-M1.
2. **Iteration 2 (≈ 2 weeks):** P1-1, P1-3, P1-4, P1-5, P1-6, P1-7, P1-8, P1-9, P1-10, P1-14.
3. **Iteration 3 (≈ 2–3 weeks):** P1-2 (+ full P0-2), P1-11, P1-12, P1-13, P1-15 (E2E).
4. **Then:** P2 by impact (P2-1, P2-3, P2-12 first), P3 as product capacity allows.

Exit criterion for "production-ready as shared ledger and care record": all P0 done with PG regression tests in
CI, P1-1/P1-2/P1-4/P1-5/P1-12 done, one restore drill and one physical-device push/PWA check recorded.
