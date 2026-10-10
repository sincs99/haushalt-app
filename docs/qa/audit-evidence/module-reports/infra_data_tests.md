# Area: infra_data_tests (Data integrity & migrations, production readiness, test quality)

Repo state audited: HEAD `e053c71` (branch `claude/adoring-goldberg-3zhyfm`), which equals `origin/master` on GitHub
(`git ls-remote origin master` → `e053c715…`). The local `master` ref (`e759095`, PR #19) is stale (145 commits behind);
this is only a stale local ref, not a missing merge. All features documented in PROJECT-STATUS (#20–#33: plants, AI, tags,
refresh cookie, invite expiry, widget…) are on remote master.

Scripts (all under `$S/work/infra_data_tests/`):
- `drift2.py` — alembic `compare_metadata` of the migrated PG schema against `Base.metadata`
- `fks.txt` — FK/ondelete inventory read from `pg_constraint` after `alembic upgrade head`
- `races.py` — concurrent upserts/joins/registers/leaves on PG (H.parallel)
- `leave_race.py` — 40× "the last two members leave at the same moment"
- `restore_rollback.sh` — documented rollback path: backup → update → `pg_restore --clean --if-exists` of the old dump

---

## 1. Inventory

| Item | Status |
|---|---|
| Alembic migration chain (40 revision files, 1 merge revision `450c52341372`, single head `a3b4c5d6e7f8`) | Implemented + verified (`alembic heads` → 1 head; `upgrade head` on empty PG succeeds; `tests/test_db_integrity.py` asserts a single head) |
| Model ↔ migrated-schema parity | Implemented + verified on PG (`drift2.py`): **no** missing or extra tables, columns, FKs, ondelete settings, indexes, unique constraints or type differences. 25 benign diffs: server defaults that exist only in the DB, and `created_at` columns that allow NULL in the DB but not in the model (see F-7) |
| Downgrade path | Partial: `downgrade base` runs down to `0f34ff355756` and then fails (`op.drop_constraint(None, …)`, `0f34ff355756_add_ondelete_to_shopping_items_fks.py:37-38`). The merge revision has `downgrade: pass` (correct) |
| FK ondelete inventory (84 FKs) | Verified from the PG catalog. All `household_id` FKs CASCADE |
| User deletion path | **None exists** (no endpoint deletes `User`; grep `db.delete(user` → nothing). User-FK `CASCADE`/`NO ACTION` rules are therefore never triggered (latent) |
| Household deletion | Only when the last member leaves (`households.py:183-195`). DB rows CASCADE; upload files are deleted on a best-effort basis |
| Idempotency through unique constraints | 19 unique indexes (list in §2). `IntegrityError` is caught only in `client_ids.py` (todos/shopping), `chore_scheduler.py:220`, `polls.py:340`, `pets.py:426/563`, `recurring_bills.py:298` and `ai/usage.py:62` |
| Backups (`scripts/backup-db.ps1`) | Implemented. The script itself is unverified (no pwsh here). Core `pg_dump -Fc` → `pg_restore` round trip with the same schema: verified locally |
| Restore (`scripts/restore-db.ps1`) | **Defective for the documented rollback use case** (F-1), verified on PG |
| Upload volume persistence | Implemented (named volume `uploaddata`, both compose files). Included in backup and restore |
| Migrations at startup | `backend/Dockerfile` CMD runs `alembic upgrade head && exec uvicorn … --workers 1`. Correct for a single replica; not safe for several replicas (D, documented in the Dockerfile comment) |
| Worker count / in-process state | `--workers 1` is hard-coded with a rationale. Socket.IO rooms, `threading.BoundedSemaphore` (`services/ai/client.py:51`) and the asyncio schedulers are process-local. Push claims are multi-process safe (`push_service.py:190 _claim`, `notified_at IS NULL` UPDATE) |
| Health checks | Backend `/api/health` checks the DB (`main.py:202`), and prod compose has a healthcheck. Postgres has a healthcheck. The frontend container has none |
| Logging / monitoring | Only uvicorn default logging plus nginx access logs (token-redacted). No log rotation config, no error tracking, no metrics or alerting. Production-unverified |
| Secrets | Mandatory `${VAR:?}` in compose. Startup refuses insecure JWT secrets and wildcard CORS (`main.py:91-104`, `test_startup_config.py`) |
| Dependency pinning | Backend: all pinned with `==`. Frontend: caret ranges, but `package-lock.json` plus `npm ci` in Docker and CI make builds reproducible |
| PWA cache headers | Verified by reading `frontend/nginx.conf`: `/assets/` immutable 1y; `/sw.js`, `/manifest.webmanifest` and the `/` fallback (index.html, `push-sw.js`, `registerSW.js`) use `no-cache`. `navigateFallbackDenylist` excludes `/api/` and `/socket.io/`. Correct |
| Web Push config | VAPID keys optional; the scheduler starts only when `push_enabled` (`main.py:128`). Prod behaviour unverified |
| CI (`.github/workflows/ci.yml`) | Runs: ruff, pytest (SQLite) with coverage, locale check, vue-tsc, vitest with coverage, pip-audit and npm audit. Does **not** run: Postgres, `alembic upgrade`, drift check, Docker build, E2E |
| Test counts | Verified: backend **837 collected in 62 files**, frontend **473** (`vitest list`) in 33 files. Matches PROJECT-STATUS line 50 |
| E2E | None. `frontend/qa/mobile-audit.cjs` is a manual Playwright layout screenshot tool (needs global Playwright, dev server and seed data). No behavioural journeys, not in CI |
| Docs: migration count / head | **Inconsistent** (F-9) |
| Docs: table count | **Inconsistent**: PROJECT-STATUS says 32 tables (lines 93, 629); the models have **38** |
| Docs: AI model name | Consistent: `client.py:40 MODEL = "claude-opus-5-5"`, README "Claude Opus 5.5", PROJECT-STATUS `claude-opus-5-5` |

## 2. Invariants

| Invariant | Where enforced | Violating operations | Status | Existing tests | Missing tests |
|---|---|---|---|---|---|
| A household that still exists has ≥1 member and ≥1 admin | `households.py:177-210` (count, then delete or promote) | Concurrent `/leave` by the last two members | **Violated** (PG: 11/40 runs left a household with 0 members, never deleted) | `test_leave_remove.py`, `test_member_lifecycle.py` (sequential only) | PG concurrency test |
| One budget per (household, month) | `uq_budget_household_month` | Concurrent `PUT /budget` | Constraint holds; second writer gets an uncaught **500** (PG) | `test_budget_scoping.py` | PG race test, 409/retry path |
| One meal-plan entry per (household, date) | `uq_meal_plan_household_date` | Concurrent `PUT /meal-plan/{date}` | Holds; **500** for the loser (PG) | `test_food_scoping.py` | Same as above |
| One email per user | `users_email_key` | Concurrent `/register` with the same email | Holds; 5/6 requests **500** (PG). Rate limit 3/h makes this rare | `test_register.py` | — (low value) |
| One membership per (household, user) | `uq_household_user` | Concurrent `/join` | Holds (PG: 1×200, 5×409); an IntegrityError → 500 is possible in a tighter interleave (reasoned) | `test_household_join.py` | — |
| One widget token per (user, household) | `uq_widget_token_user_household` | Concurrent `POST /widget-token` | Holds; PG: 3×201 + 3×500. Two callers got 201 with a token that is no longer valid | `test_widget.py` | — |
| One booking per bill and month | `uq_expense_bill_booked_month` + catch `recurring_bills.py:298` | Concurrent book | Verified by constraint + handler (another area tests the race) | `test_recurring_bill_book.py`, `test_db_integrity.py` | — |
| One vote per poll and user | `uq_poll_vote_poll_user` + catch `polls.py:340` | — | Verified (constraint) | `test_db_integrity.py` | — |
| One chore assignment per (chore, date) | `uq_chore_assignment_per_date` + savepoint `chore_scheduler.py:213-223` + `FOR UPDATE` | Concurrent materialisation | Verified by code. The chores area covers PG | `test_chores.py` | — |
| A restored backup equals the backed-up state | `restore-db.ps1:139` | Restoring a dump taken before a migration (documented rollback) | **Violated** (F-1) | none | Scripted restore test in CI |
| The schema produced by migrations equals the models | Manual discipline | Any new migration | Verified now (no structural drift); **untested in CI** | `test_db_integrity` (single head only) | CI job: PG + `alembic upgrade head` + `compare_metadata` |
| Push reminders are sent at most once, even with several processes | `push_service.py:190 _claim` | — | Verified by code reading | `test_push*.py` | — |

## 3. Findings

### F-1 Restore of a pre-update backup (documented rollback) leaves the DB half-restored; the next start crashes
- **Severity:** High · **Class:** A (procedure defect) · **Modules:** `scripts/restore-db.ps1:139`, `docs/deployment.md:210-216`, Alembic
- **Observed:** `pg_restore --clean --if-exists` drops only the objects that exist in the dump. Tables added by the update (here `widget_tokens`) keep FKs to `users` and `households`, so dropping those two tables fails. Their **current** rows stay, and the COPY of the backup rows fails with a duplicate PK. All other tables return to the backup state. `alembic_version` goes back to the old revision while the new tables remain. The script treats exit code 1 as a probable warning (`restore-db.ps1:156-160`, yellow "kann durch Warnungen verursacht werden"). The next forward update (`alembic upgrade head` in the container CMD) fails with `DuplicateTable`, so the backend is stuck in a restart loop.
- **Evidence (`restore_rollback.sh` on PG 16):**
  ```
  pg_restore: error: … cannot drop table public.users because other objects depend on it
  pg_restore: error: COPY failed for table "users": ERROR: duplicate key value violates unique constraint "users_pkey"
  pg_restore: warning: errors ignored on restore: 10   / exit=1
  alembic|y1z2a3b4c5d6
  users|new@x.ch|New                         <- user created AFTER the backup survives
  users|old@x.ch|ChangedAfterBackup          <- post-backup change survives
  households|HH-changed
  widget_tokens table|widget_tokens          <- table of the newer schema still present
  == backend start: alembic upgrade head → psycopg2.errors.DuplicateTable: relation "widget_tokens" already exists
  ```
- **Expected:** after a restore the DB matches the dump exactly, or the restore aborts loudly.
- **Root cause:** `--clean` with a partially overlapping schema, no `--single-transaction`/`--exit-on-error`, the backend is not stopped and the DB is not recreated.
- **Business impact:** in an emergency rollback the household gets a mixed DB (users and households from "now", everything else from "then"; members, expenses and shares may not match), without a clear error. The app then fails to start on the next update.
- **Fix:** stop `backend`; `DROP SCHEMA public CASCADE; CREATE SCHEMA public` (or `dropdb`/`createdb`); then `pg_restore --single-transaction --exit-on-error`; treat any non-zero exit as failure; start the backend. Document that a rollback restore requires checking out the matching old code.
- **Regression test:** CI or script test: migrate to N-1, seed, dump, upgrade to head, restore, then assert row equality and that `alembic upgrade head` succeeds.
- **Confidence:** High (reproduced with the same pg_restore flags; the PowerShell wrapper itself was not executed).

### F-2 The last two members leaving at the same time orphan the household or return a 500
- **Severity:** Medium · **Class:** A · **Modules:** `backend/app/routers/households.py:176-210`
- **Observed (`leave_race.py`, 40 runs on PG):**
  ```
  5 x  results=('204','204') household_exists=False members=0
  11 x results=('204','204') household_exists=True  members=0     <- orphan household, all data kept, files never deleted
  24 x results=('204','StaleDataError') household_exists=True members=1   <- HTTP 500
  ```
- **Root cause:** check-then-act. Both requests count 2 members (`len(all_members) <= 1` false), and each deletes only its own membership. The admin's request also promotes the other member (UPDATE on a row being deleted → `StaleDataError`). There is no row lock on the household or member rows.
- **Impact:** a household with zero members whose data (expenses, documents, photos) is never deleted (privacy/retention) and that nobody can reach. Otherwise a 500 for one user. In practice this is rare (needs near-simultaneous clicks).
- **Fix:** `SELECT … FROM households WHERE id=… FOR UPDATE` (or lock all member rows `FOR UPDATE`) before counting. Afterwards, re-check and delete the household if no members remain.
- **Test:** PG integration test with H.parallel.
- **Confidence:** High.

### F-3 Upserts and creates backed only by a unique constraint return HTTP 500 under concurrency
- **Severity:** Low–Medium · **Class:** A · **Modules:** `budgets.py:67-110`, `food.py:400-421` (meal plan), `widget.py:102-127`, `auth.py:250-306` (register), `households.py:482+` (join), `push.py:58-84` (same endpoint, reasoned)
- **Observed (`races.py`, PG, 6 parallel requests):** budget PUT same month → `200×4, 201×1, IntegrityError×1`; meal-plan PUT same date → `200×5, IntegrityError×1`; widget-token create → `201×3, IntegrityError×3`; register same email → `200×1, IntegrityError×5`. (TestClient re-raises; in production each is an HTTP 500.)
- **Impact:** both partners setting the month budget or the same day's meal plan at once means one sees an error toast and may retry. With the widget token, two callers get a 201 but only one token is valid. No data corruption: the constraints hold.
- **Fix:** use `INSERT … ON CONFLICT DO UPDATE` (PG) for budget and meal plan; catch `IntegrityError` → 409 for register/join; lock or upsert for the widget token.
- **Confidence:** High.

### F-4 History-destroying cascades and a user-FK mix that will block any future account deletion
- **Severity:** Low now (latent) · **Class:** E / C · **Modules:** migrations/models (inventory in `fks.txt`)
- Rules that destroy history when **a user is deleted**: `expense_shares.user_id CASCADE` (changes expense totals relative to shares, so balances shift), `settlements.from_user_id/to_user_id CASCADE` (settlements vanish, so balances reopen), `push_subscriptions`, `refresh_tokens` and `widget_tokens` CASCADE (fine).
- `NO ACTION` rules that **block** a user deletion: `household_members.user_id`, `events.created_by_user_id`, `event_polls.created_by_user_id`, `event_poll_votes.user_id`, `feeding_logs.fed_by_user_id`, `medication_logs.given_by_user_id`.
- There is currently **no user deletion path** (verified by grep), so nothing fires today. The model is inconsistent for a future "delete account" or GDPR feature. Expense and settlement data would be silently rewritten, while other deletions would fail.
- Entity deletes that cascade history (product decisions, see §7): chore delete → all `chore_assignments` (any member may delete, `chores.py:336-353`); pet delete → `feeding_logs` + `medications` → `medication_logs`; medication delete → logs; plant delete → care logs.
- Calendar delete is guarded (refuses while events exist, `calendars.py:190`). The guard is check-then-act, so an event created concurrently would be CASCADE-deleted (reasoned, unverified).
- **Recommendation:** decide the account-deletion semantics now (anonymise vs delete). Change `expense_shares.user_id` and `settlements.*_user_id` to `RESTRICT` or `SET NULL` plus a "former member" pattern.
- **Confidence:** High for the inventory; impact reasoned.

### F-5 CI never runs migrations or PostgreSQL; schema drift and PG-only behaviour are untested
- **Severity:** Medium · **Class:** E · **Modules:** `.github/workflows/ci.yml`, `backend/tests/conftest.py:84-171`
- The test DB is SQLite in-memory built with `Base.metadata.create_all`. The migrations are never executed in CI; only `test_db_integrity.py` parses the script directory for a single head. Every request in a test shares **one** Session (`_override_get_db` yields the same `db`), so there is no transaction isolation, no real commit/rollback per request, and no concurrency. F-2 and F-3 cannot be detected by the suite. `test_pool_contention.py` uses SQLite QueuePool, not PG.
- Today the migrated schema matches the models structurally (verified, §1), so this is a gap rather than an active defect.
- **Fix:** add a CI job with a `postgres:16` service that runs `alembic upgrade head`, `compare_metadata` (fail on structural diffs), `downgrade -1/upgrade head` for the newest revision, and a small PG integration suite (races from this audit).
- **Confidence:** High.

### F-6 Upload file written before the DB commit; quota check is not atomic
- **Severity:** Low · **Class:** A/E · **Modules:** `routers/files.py:252-281`, `files.py:335-356`
- `store_upload` writes to disk (`_storage.save`) and only flushes. If the later commit fails, the file stays on disk with no row, and `delete_orphan_files` only finds DB rows, so it is never cleaned up. `check_storage_quota` is read-then-write, so parallel uploads can exceed the quota (reasoned; the upload area may have verified it).
- **Confidence:** Medium (code reading).

### F-7 Benign model/DB drift: nullability and server defaults
- **Severity:** Low · **Class:** E
- `created_at` is nullable in the DB but `nullable=False` in the model for `budgets` (and `updated_at`), `calendars`, `pet_care_tasks`, `plant_care_tasks`, `plants`, `recurring_bills`, `stored_files` and `widget_tokens`. Raw SQL inserts can create NULLs that the ORM and schemas do not expect. The DB has defaults the model lacks (`gen_random_uuid()`, `now()`, `push_subscriptions.locale 'de'`, …), so a future autogenerate will propose dropping them.
- **Fix:** one cleanup migration (`SET NOT NULL` after a backfill) and add `server_default` to the models.
- **Evidence:** `drift2.py` output (25 diffs, all of these two kinds).

### F-8 Downgrade chain broken below `0f34ff355756`
- **Severity:** Low · **Class:** A · `migrations/versions/0f34ff355756_add_ondelete_to_shopping_items_fks.py:37-38` `op.drop_constraint(None, 'shopping_items', type_='foreignkey')`
- `alembic downgrade base` → `CompileError: Can't emit DROP CONSTRAINT … it has no name`. Downgrades of all 38 later revisions work (verified by running `downgrade base` on PG; it stopped at this revision). Practically irrelevant (nobody downgrades to 2026-08), but it shows downgrades are not tested.

### F-9 Documentation inconsistencies
- **Severity:** Low · **Class:** Docs inconsistent
- `docs/PROJECT-STATUS.md:50`: "37 Alembic-Migrationen (einziger Kopf `y1z2a3b4c5d6`)"; `:133`: "33 Versionen …, einziger Kopf `w1x2y3z4a5b6`"; `:629`: "33 Versionen"; `:917`: "37 Versionen"; `:1310`: head `y1z2a3b4c5d6`. **Actual: 40 revision files, head `a3b4c5d6e7f8`** (`add_widget_tokens`; `z2a3b4c5d6e7` and `a3b4c5d6e7f8` came after).
- `PROJECT-STATUS.md:93, 629`: "32 Tabellen". **Actual: 38** tables in `Base.metadata`.
- Test counts are **consistent**: 837 / 62 files and 473 / 33 files (verified).
- `README.md:20`: "Tests … SQLite in-memory, kein Postgres nötig". This is correct, but no doc warns that PG behaviour and migrations are untested.
- `docs/deployment.md:210-216` presents the restore as the rollback path for a migration. This is unsafe (F-1).

### F-10 Production operations gaps
- **Severity:** Low–Medium · **Class:** E (production-unverified)
- Backups are written to `backups/` **on the same host** and are only optional to copy elsewhere (`deployment.md:293`). The DB dump and the upload tar run sequentially while the app is live, so they are not a consistent pair (rare mismatch). No automated restore test (§6.3 describes one, which F-1 shows would expose the issue only if run across a migration).
- `restore-db.ps1` does not stop the backend before `pg_restore --clean`. Live connections can block DROPs or write in between (reasoned).
- There are no log rotation options on the containers (Docker json-file default is unbounded), no error tracking and no alerting. The health endpoint exists but nothing watches it.
- `FORWARDED_ALLOW_IPS=172.16.0.0/12` and nginx `set_real_ip_from 172.16.0.0/12`: if Docker or NPM use another address pool (e.g. 192.168.x), every client gets the proxy IP. Login and register rate limits then become global, e.g. "3/hour" registrations for everyone. This is documented in comments only. Production-unverified.
- `frontend/Dockerfile` runs `npx vite build` (not `npm run build`), so the image build skips `vue-tsc` (CI runs it separately; minor).
- Multiple replicas: startup `alembic upgrade head` would race, and Socket.IO rooms, the AI semaphore and the orphan cleanup are per process. This is acceptable because `--workers 1` and a single replica are the documented design (D).

## 4. Prior review status (items touching this area)

| Item | Status now |
|---|---|
| L-15 / E-6 (assignments of a member who left stay set) | Still open as documented. `leave_household`/`remove_member` do not touch `todos.assigned_to_user_id` or `shopping_items.assigned_to_user_id` (code: `households.py:160-270`). FK `SET NULL` only fires on user deletion, which does not exist |
| E-7 (rotation not cleaned on leave) | Still as documented (`households.py:172` docstring) |
| Other L-/E- items | Outside this area |
| `docs/qa/current-audit-fixes.md` | States "keine neue Datenbankmigration". Consistent with the code (no migration after `a3b4c5d6e7f8`) |

## 5. Cross-module effects

- Last-member leave → `households` CASCADE → every module's data plus best-effort file deletion. In the race (F-2) nothing is deleted, the household stays forever, and uploads keep counting toward a quota nobody uses.
- (Future) user deletion → `expense_shares` CASCADE → expenses whose shares no longer sum to the amount, so the balance service output changes retroactively. `settlements` CASCADE → settled debts reappear.
- Chore delete → `chore_assignments` CASCADE → the dashboard and completion history ("wer hat wie oft geputzt") lose past data.
- Pet delete → `feeding_logs`, `medications` → `medication_logs` CASCADE; photo `StoredFile` deleted explicitly (`pets.py:518`).
- Restore across a migration (F-1) → users and households from "now", memberships, expenses and the rest from "then". This means user rows without memberships and memberships pointing to the backup state.

## 6. Test gaps

| Scenario | Recommended type |
|---|---|
| `alembic upgrade head` on empty PG + `compare_metadata` structural diff = 0 | CI PG integration |
| Newest migration `downgrade -1` / `upgrade head` round trip | CI PG integration |
| Backup → migrate → restore → app starts and data equals the dump | Scripted ops test (could run in CI with docker compose) |
| Concurrent last-two-members leave; concurrent budget/meal-plan upsert; concurrent widget token | PG integration with threads |
| Multi-user journey: A creates an expense → B settles → A leaves → balances and history correct | API journey test (PG) |
| Real browser E2E: login → household → shopping list sync between two sessions via Socket.IO | E2E (Playwright), none exists |
| Money invariants (shares sum = amount, balances sum = 0) over random splits and member changes | Property-based (hypothesis is available in the venv; none in the repo, `grep hypothesis tests` → 0) |
| Frontend views/components | None tested (all 33 vitest files cover stores, utils and composables). Stores without a test file: `dashboard.ts`, `documents.ts`, `polls.ts` |
| Thin backend areas by count | `test_expense_events.py` 5, `test_finance_summary.py` 5, `test_todo_scoping.py` 5, `test_note_scoping.py` 5, budgets only via `test_budget_scoping.py` 7, polls behaviour only via `test_db_integrity` / `test_meal_poll`. Many files are `*_scoping` (403 checks), not business rules |
| Mocking | 46 of 62 test files use `patch`/`monkeypatch`. Socket emits are globally mocked in conftest, so emit payload correctness is asserted only where tests inspect the mock |

## 7. Product decisions

1. **Account deletion semantics** (needed before any GDPR or "delete account" feature): a) anonymise the user and keep all rows (recommended; matches the existing "ehemaliges Mitglied" pattern); b) hard delete with SET NULL everywhere; c) keep the current mixed CASCADE/NO ACTION (not viable). Recommendation: a, plus change the `expense_shares` and `settlements` FKs to RESTRICT.
2. **Chore/pet/medication delete destroys history**: a) keep the hard delete (today); b) soft delete or archive (`active=false` exists for chores, so the UI could offer pause instead of delete); c) admin-only delete. Recommendation: b for chores and medications.
3. **Rollback strategy**: a) restore an old dump with old code (today; needs F-1 fixed); b) forward-only migrations plus restore only for disaster recovery. Recommendation: b, plus a fixed restore script.

## 8. Unverified

- PowerShell scripts were not executed (no `pwsh`). The `pg_dump`/`pg_restore` commands they use were reproduced directly on PG 16.
- Docker image builds and compose startup were not run. Production nginx, NPM, TLS, VAPID and real push delivery were not tested.
- The Docker address-pool mismatch effect on rate limiting (F-10) is reasoned from config.
- Calendar-delete vs concurrent event-create race (F-4) and quota race (F-6) are reasoned, not run.
- Full test runs (pass/fail, coverage %) were not run here (collect only, per instructions). The 94 % / 77.49 % coverage figures are taken from the docs, unverified.
