# Remediation Status

**Date:** 2026-10-10 · Branch `claude/adoring-goldberg-3zhyfm` · Companion to [FULL_LOGIC_AUDIT.md](FULL_LOGIC_AUDIT.md),
[REMEDIATION_ROADMAP.md](REMEDIATION_ROADMAP.md), [PRODUCT_DECISIONS.md](PRODUCT_DECISIONS.md).

The audit documents themselves are left unchanged as the record of the state at `e053c71`. This file tracks what
was done afterwards. Every fix was written test-first; concurrency fixes are covered by the new PostgreSQL test lane
(`backend/tests/pg/`, CI job `backend-postgres`).

## 1. Product decisions taken by the owner

| ID | Decision |
|---|---|
| PD-F1/F2 | All members may still edit/delete; soft delete + created/updated/deleted by + visible history + warning "Salden ändern sich nachträglich"; former members shown prominently in the balance overview |
| PD-F3 | Settlements: client-id idempotency + plausibility warnings (never a hard block) |
| PD-F4/F5/F7 | Retro-booking of the past 12 months; `custom` split rejected for bills; expenses versioned (`If-Match` → 409), dialogs send only changed fields |
| PD-H1/H3 | Departure releases open responsibilities (todos, shopping, open chore assignments, rotation, bill default payer, open-poll votes, widget token); membership changes locked per household; auto-promotion whenever no admin exists |
| PD-C1/C2 | Pausing deletes open assignments ≥ today; reactivation re-anchors; dashboard shows today + overdue chores; `GET /tasks` removed |
| PD-P1–P4 | Medication: give always possible with last-dose hint and < 4 h confirmation, client-id idempotency, deletion with history → 409 (deactivate instead); pets archivable, archived pets excluded everywhere; interval change recomputes the due date |
| PD-M1–M3 | Meal-poll decide on an occupied day → 409 unless `replace=true`, UI asks; one bulk add-to-shopping endpoint with cross-list dedupe; deleted recipes stay as free text in the plan |
| PD-T1/T2 | Tag scans idempotent per household day; feed tag accepts any unfed slot |
| PD-K1–K5 | Event reminders per event (none/15 min/1 h/1 day); event-poll options require a time; multi-day events on dashboard/widget; DST gap → 422; poll times in household time |
| PD-D1/D2 | Ledger FKs RESTRICT (anonymisation documented, no deletion feature); forward-only migrations, restore for disaster recovery |
| PD-A2 | Per-user AI daily limit (`AI_DAILY_LIMIT_PER_USER`, default 20) |
| P3 | Recurring-bill management UI, event reminders and recipe UI implemented |

Decisions taken by the lead without explicit owner input (open for veto): retro-booked months are split among the
**current** members; soft-deleted rows have no retention limit; a second plant completion on the same day discards
its note; pausing also removes today's open assignment; old clients without the tag `confirm` object fall back to
"current period only"; RESTRICT also on `expenses.paid_by_user_id`; restore keeps the previous DB unless `-DropOld`.

## 2. Status per finding

✅ fixed and covered by tests · ◐ partially fixed · ○ open · ⚠ fixed, not verifiable in this environment

| ID | Status | How (tests) |
|---|---|---|
| CASA-01 | ✅ | Row lock + `version`/`If-Match` (`tests/pg/test_pg_finance.py` parallel PATCH/DELETE); audit script `journeys/v2_shares.py` now: 0/10 violations, `j3`: 40/40 without 500 |
| CASA-02 | ✅ | Soft delete, attribution, history view, `before_last_settlement` warning, former-member block in BalanceSummary (`test_soft_delete_*`, `test_balances_flag_former_members`) |
| CASA-03 | ✅ | `POST /expenses/{id}/restore` keeps bill link and ex-member participants; partial unique index (`test_restore_booked_expense_keeps_bill_link`, PG restore‖rebook) |
| CASA-04 | ✅ | `PatchModel` rejects explicit null (51 parametrised cases), `NonNullJSON`, data-repair migration `fnd1a2b3c4d5`; `journeys/v1_nulls.py` now 422/200 |
| CASA-05 | ✅ | Current period independent of completion, `ALREADY_DONE` (`TestChoreDone`, `tests/pg/test_pg_tags.py`) |
| CASA-06 | ✅ | Done no longer cancels reminders; reopen re-arms future ones; bell hidden when sent (`test_todo_reminder_lifecycle.py`) |
| CASA-07 | ⚠ | `restore-db.ps1` rewritten, `restore-db.sh`, `restore-drill.sh` in CI; the PowerShell script and the Docker paths were not executed here |
| CASA-08 | ✅ | Client id + `POST /settlements/check` warnings under household lock (`test_settlement_*`, PG parallel) |
| CASA-09 | ✅ | Diff-only PATCH for expenses, shopping sheet, recipes, events, notes, todos; 409 for stale expenses |
| CASA-10 | ✅ | `lock_household`, `ensure_admin`, 0-member deletion, repair migration `hh1a2b3c4d5e` (`tests/pg/test_households_membership.py`) |
| CASA-11 | ✅ | Locked single-commit rotation, grace follows the chain (`tests/pg/test_auth_refresh_race.py`) |
| CASA-12 | ✅ | Shared generation guard in every store fetch, reset on logout and on any household change (`householdIsolation.test.ts`, 102 cases) |
| CASA-13 | ✅ | Savepoint per pet, only created rows returned (`tests/pg/test_pg_pets.py`) |
| CASA-14 | ✅ | Give always available with last-dose hint and confirmation; client-id idempotency |
| CASA-15 | ✅ | `MEDICATION_HAS_HISTORY`/`PET_HAS_HISTORY` 409, pet archive |
| CASA-16 | ✅ | Materialisation clamped to `anchor_date`; `chore_assignments_deleted` event |
| CASA-17 | ✅ | Pause deletes open assignments, reactivation re-anchors, `Chore.active` filters |
| CASA-18 | ✅ | `confirm` pinning on resolve/execute, 409 `TAG_CONFIRMATION_STALE`; fallback for old clients |
| CASA-19 | ✅ | Full socket payload, `MEAL_PLAN_OCCUPIED`, `ON CONFLICT` upsert |
| CASA-20 | ✅ | Calendar/household locks, FK RESTRICT (`tests/pg/test_pg_calendar.py`) |
| CASA-21 | ✅ | Assignee/participant/recipe validation |
| CASA-22 | ✅ | `release_departing_member` in the leave/remove transaction; attention treats ex-members as unassigned; widget tokens deleted |
| CASA-23 | ✅ | Paging (50, "Mehr laden") + month filter |
| CASA-24 | ✅ | Global `IntegrityError`/`StaleDataError` → 409 `CONFLICT_RETRY`; specific codes for register/join/widget/meal plan/files/shopping |
| CASA-25 | ◐ | PostgreSQL lane in CI (66 tests), drift check, downgrade/upgrade, restore drill, property tests (finance, scheduler); **E2E suite still missing** |
| CASA-26 | ✅ | Quota under household lock (`tests/pg/test_pg_files.py`) |
| CASA-27 | ✅ | `SKIP LOCKED` cleanup with re-check; disk-orphan sweep; file removed on failed commit |
| CASA-28 | ✅ | `lock_files`, `FILE_IN_USE` |
| CASA-29 | ✅ | Conditional update per household day (router + tags) |
| CASA-30 | ✅ | Confirmation before deleting someone else's feeding |
| CASA-31 | ✅ | Any unfed slot |
| CASA-32 | ✅ | Upsert reservation (`tests/pg/test_pg_ai.py`) |
| CASA-33 | ✅ | All `anthropic.APIError` → 502, reservation released on unexpected errors |
| CASA-34 | ✅ | AI results dropped after household switch; AI missing ingredients via bulk endpoint |
| CASA-35 | ✅ | `EVENT_TIME_NONEXISTENT` |
| CASA-36 | ✅ | Amount ≤ 10^9, dates ±10 years, month validation |
| CASA-37 | ✅ | `PatchModel` |
| CASA-38 | ✅ | Category clearable |
| CASA-39 | ✅ | `/me` returns household timezone; finance, chores, todos, tag scan use household date |
| CASA-40 | ✅ | `?hh=` in push URLs, household switch on open, badge per household |
| CASA-41 | ⚠ | Update check on visibility/interval, persistent update entry; not tested on an installed iOS PWA |
| CASA-42 | ✅ | Budget month check, `budget_deleted`, summary refresh on bill events |
| CASA-43 | ✅ | Dashboard = badge rule; extra invalidation events; `/tasks` removed |
| CASA-44 | ✅ | `useRealtimeSession`: token refresh only re-auths the socket |
| CASA-45 | ✅ | 404 on DELETE = success; unconfirmed items kept; retry reuses client id |
| CASA-46 | ✅ | Emit on every materialisation; reminder changes bump todo version; join ack/retry; member-joined on register |
| CASA-47 | ✅ | Push unsubscribed on silent session end / cross-tab logout |
| CASA-48 | ✅ | Membership re-check after `enter_room` and in `reauth` |
| CASA-49 | ✅ | `revalidateMembership` on reconnect, 403 and socket error |
| CASA-50 | ✅ | `useWidgetToken` household guard |
| CASA-51 | ✅ | Clamp only on open assignments; reminders on done todo → 422; naive `remind_at` = household time |
| CASA-52 | ✅ | Recipe name copied into `free_text` |
| CASA-53 | ✅ | Bulk endpoint under household lock, cross-list dedupe |
| CASA-54 | ✅ | Locked count of calendars |
| CASA-55 | ✅ | Ledger FKs RESTRICT (migration `ops1a2b3c4d5`), anonymisation documented |
| CASA-56 | ✅ | Downgrade to base works; server defaults and nullability aligned; drift check includes defaults |
| CASA-57 | ⚠ | Backup/restore options, log rotation, health checks, trusted proxy ranges, typecheck in image build; not run against Docker/production |
| CASA-58 | ✅ | `PROJECT-STATUS.md`, `README.md`, `tags-review.md`, docstring corrected |
| CASA-59 | ✅ | Care-type keys translated in the frontend |
| CASA-60 | ✅ | Poll option times in household time; options require a time |

## 3. Verified state after remediation

| Check | Result |
|---|---|
| Backend SQLite lane | 1093 passed, 66 skipped (PG tests), coverage 95 % |
| Backend PostgreSQL lane | 66 passed |
| Frontend vitest | 727 passed in 56 files; statements 83.4 %, branches 77.9 % |
| Typecheck, locales (1312 keys), ruff | pass |
| Alembic | 46 revision files, single head `cal1a2b3c4d5`; full downgrade to base and upgrade verified |
| Audit reproduction scripts | `v2_shares.py`, `j3_expense_concurrent_patch.py`, `v1_nulls.py`, `j1_finance_leave.py` re-run on the fixed code |

## 4. Still open / not verifiable here

- **E2E tests** with two browser contexts (TEST_GAP_MATRIX #30) do not exist yet.
- **Not executed in this environment:** real browser or iPhone checks of the new UI (recipe manager, bill management, history, decide dialog, reminder select, update entry); real Web Push delivery; PowerShell scripts; Docker images, nginx and compose healthchecks; production proxy ranges.
- **Not modelled:** membership history, so retro-booked months use current members. Event participants of former members are kept as they are (PD-H1 did not list them).
