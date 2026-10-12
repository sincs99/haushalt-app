# Test Gap Matrix

**Date:** 2026-10-10 · Companion to [FULL_LOGIC_AUDIT.md](FULL_LOGIC_AUDIT.md).

## 1. Current state (verified on this checkout)

| Suite | Count | Result | Notes |
|---|---|---|---|
| Backend pytest | 837 tests / 62 files | all pass, coverage 94 % | SQLite in-memory via `Base.metadata.create_all`; **one shared Session for all requests** (`conftest.py:_override_get_db`); socket emits globally mocked; 46/62 files use `patch`/`monkeypatch` |
| Frontend vitest | 473 tests / 33 files | all pass; statements 77.49 %, branches 72.14 % | Stores, utils, composables only; **no component or view tests**; stores `dashboard`, `documents`, `polls` have no test file |
| Typecheck / locales / ruff | — | pass | 1173 locale keys in sync |
| CI | ruff, pytest(SQLite), locales, vue-tsc, vitest, pip-audit, npm audit | — | **no PostgreSQL, no `alembic upgrade`, no schema drift check, no Docker build, no E2E** |
| E2E | none | — | `frontend/qa/mobile-audit.cjs` is a manual screenshot tool |
| Property-based | none | — | hypothesis not used in the repo |

### Test-quality observations

- **Sequential-only evidence.** With one shared session, tests cannot observe transaction isolation, row
  locking, `IntegrityError` under concurrency or `StaleDataError`. Every concurrency finding of the audit
  (CASA-01, -05, -08, -10, -11, -13, -19, -20, -24, -26, -28, -29, -32) passes the existing suite.
- **Tests that encode a wrong assumption.** `test_prefers_current_period_over_older_backlog` checks only the
  first scan (CASA-05); `test_leave_admin_auto_promote`/`test_leave_last_member_deletes_household` encode the
  rule but not its atomicity; `test_backfill_limited_to_14_days` accepts the backfill burst that CASA-17 shows
  is harmful after reactivation; the logic review rated "todo reopen" ok without a test (CASA-06).
- **Many `*_scoping` files** (≈ 25) assert 403/404 for foreign households — valuable for isolation, but they
  do not test business outcomes.
- **Emit contracts are untested** except where a test inspects the mock (L-03 regression); CASA-19 is the same
  defect class and passed.
- **Migrations are never executed** in tests; `test_db_integrity.py` checks only for a single head.
- **Frontend race tests exist** (`syncRaces.test.ts`, pets/plants guards) but not for the 12 unguarded stores.

## 2. Gap matrix

Priority: P0 = must exist before the corresponding fix ships · P1 = next iteration · P2 = later.

| # | Critical business scenario | Existing coverage | Missing scenarios | Test type | Recommended test cases | Prio |
|---|---|---|---|---|---|---|
| 1 | Expense ledger invariant Σshares = amount | sequential unit tests | concurrent PATCH‖PATCH, PATCH‖DELETE | PG integration | `H.parallel` 2–4 PATCH with disjoint/overlapping participants + amount; DELETE‖PATCH; assert Σ = amount, status ∈ {200,404,409} | P0 |
| 2 | Ledger invariants over arbitrary operation sequences | none | random create/edit/delete/settle/leave/join/book | Property-based (hypothesis) on PG | port `audit-evidence/finance/pg_props.py`: after each step Σshares = amount, Σsaldo = −unassigned, suggestions zero balances, ≤ n−1 | P1 |
| 3 | Split and settlement maths | example tests | random amounts/participants | Property-based (pure) | port `finance/test_pure_props.py` | P1 |
| 4 | Undo of expense deletion | none | booked bill, ex-member participant | API + vitest | delete booked → restore → bill still booked → book → 409; ex-member restore → 200; undo payload keeps link | P0 |
| 5 | Settlement idempotency/plausibility | none | double recording, parallel, overpay | API + PG | same client id twice → 1 row; parallel; amount > debt → warning flag | P1 |
| 6 | Explicit null on non-nullable fields | none | every `*Update` schema | API (parametrised) | for each field: PATCH null → 422, row unchanged, list endpoints 200 | P0 |
| 7 | Chore tag idempotency and pinning | one-scan test | repeated, parallel, resolve→external complete→execute | PG integration | 2 open past assignments, execute ×2 → second `changed=false`; parallel; pinned id → 409 | P0 |
| 8 | Todo reopen keeps reminders | none | done→undo with future reminder | API + scheduler unit | run `process_todo_reminders` at `remind_at+1min` after undo → 1 push; frontend bell hidden when `notified_at` set | P0 |
| 9 | Backup/restore across a migration | none | rollback restore | Scripted ops test (docker compose or PG service) | migrate N-1 → seed → dump → upgrade → restore → row equality, `alembic upgrade head` succeeds | P0 |
| 10 | Feed-all completeness | tag test only | concurrent single feed | PG integration | `H.parallel` single + feed-all → all pets fed; response lists created rows | P0 |
| 11 | Membership invariants | sequential tests | leave‖leave, leave‖join, admin‖senior | PG integration | assert admins ≥ 1 or members = 0; 200 join ⇒ member; no 0-member household | P1 |
| 12 | Refresh token concurrency | sequential grace test | 2/3-way concurrent, 3 uses within grace | PG integration + unit | no `REFRESH_TOKEN_REUSED`, exactly one active token | P1 |
| 13 | Store isolation per household/session | reset test | late response after switch for 12 stores; logout→login; A→null→C | vitest | pattern from `audit-evidence/households/staleSwitch.test.ts` per store; App watch test | P1 |
| 14 | Chore schedule edit / pause / reactivate | rename & schedule tests | gap ≥ 1 day before new anchor; push for paused chore; reactivation backfill | API with patched today + scheduler unit | no open `due_date < today` after edit/reactivation; no push for inactive chore | P1 |
| 15 | Chore scheduler date maths | example tests | random anchors/windows | Property-based | port `chores_tasks_time/prop_scheduler.py` | P2 |
| 16 | Socket payload contract | L-03 regression only | every emit vs response model; deletions propagated | Backend contract test | collect emits per router (mock), validate against Pydantic models; schedule edit emits deletion | P1 |
| 17 | Meal plan concurrency and decide semantics | sequential tests | parallel PUT/decide; occupied date; recipe delete | PG + API | ON CONFLICT path; 409/confirm on occupied date; entry after recipe delete | P1 |
| 18 | Calendar delete races | sequential guard tests | delete‖create, delete‖decide, delete‖delete | PG integration | no 201 without persisted event; ≥ 1 calendar | P1 |
| 19 | Membership validation of assignees/participants | none | todos, events, event-poll recipes | API | foreign user → 422; random UUID → 422; ex-member already on record allowed | P1 |
| 20 | Departure consistency across surfaces | ex-member finance tests | badge/widget/push/dashboard for ex-member assignee; widget key after leave/rejoin; bill payer | API consistency | same data → same "due" set on badge, widget, dashboard, push recipients | P1 |
| 21 | Concurrency → 409 not 500 | none | budget, meal plan, widget token, register, join, document claim, item into deleted list | PG integration | parallel pair → statuses ⊆ {200,201,409,422} | P1 |
| 22 | Medication multi-dose and duplicates | none | second dose UI; parallel give; delete with history | component + API | button visible with last-dose info; client id idempotent; delete blocked/archived | P1 |
| 23 | Plant/care idempotency | sequential | parallel complete/water-all; repeated tag | PG integration | one log per task per day (after PD-T1) | P2 |
| 24 | Files under concurrency | sequential | quota, claim, cleanup interleave | PG integration | quota never exceeded; exclusive ownership; cleanup never deletes attached | P2 |
| 25 | Expense list beyond 100 | none | pagination | vitest/E2E | 150 expenses → all reachable | P1 |
| 26 | Migrations vs models | single-head test | upgrade on PG, drift, downgrade/upgrade of newest | CI PG job | `alembic upgrade head`; `compare_metadata` = no structural diff; `downgrade -1 && upgrade head` | P1 |
| 27 | DST and household time | Zurich offsets | gap/overlap event creation; device TZ ≠ household TZ | unit + vitest (TZ env) | 02:30 on 2026-03-29 → clear error or normalised; frontend dates with `TZ=America/New_York` | P2 |
| 28 | AI quota concurrency/failure | SQLite unit | first-row race, unmapped exceptions | PG integration + unit | no 429 below limit; `APIResponseValidationError` → 502, quota released | P2 |
| 29 | Push click household context, badge per household | none | multi-household push | E2E | tap pet reminder of household B while on A → B opened | P2 |
| 30 | **Critical household journeys end-to-end** | none | two devices, realtime | E2E (Playwright, two browser contexts) | (a) shopping list sync add/check/delete between two users; (b) expense create → balances on other device; (c) household switch while loading; (d) logout → other user login; (e) meal poll decide visible on other device; (f) chore complete via `/t/<token>` twice | P1 |

## 3. What remains unverified after this audit

| Area | Why | How to verify |
|---|---|---|
| Real iOS/Android PWA behaviour (install, SW update, badge, push click, Web NFC double reads) | no device | device test checklist per release |
| Real Web Push delivery (VAPID, Apple/FCM) | no keys/devices | staging with a test device |
| Production nginx / Nginx Proxy Manager, TLS, real-IP range, long AI requests | no production access | staging smoke test; check `FORWARDED_ALLOW_IPS` vs Docker pool |
| Real Anthropic API (refusals, latency, cost) | no key (documented) | one-off staging run |
| `restore-db.ps1`/`backup-db.ps1` executed as scripts | no PowerShell; commands reproduced directly | run once on the Windows host |
| Real Socket.IO ordering and the join/evict race (CASA-48) | requires a running server + clients | socket integration test |
| Accessibility in a browser (screen reader, contrast) | not re-audited | axe + manual VoiceOver pass |
| Frequency of the concurrency defects in real use | harness proves the windows exist only | production logging of 409/500 per endpoint |
