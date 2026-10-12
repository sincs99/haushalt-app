# Area `tags_ai` — NFC/QR tag action registry + AI assistant

Auditor scripts (all under `$S/work/tags_ai/`, run against PostgreSQL 16 via `pgharness`, Anthropic client always mocked):

- `pg_tags.py` — T1..T13 tag scenarios (DB `audit_tagsai_tags`)
- `pg_ai.py` — A1..A5 quota/failure scenarios (DB `audit_tagsai_ai`)
- `pg_ai_firstrow.py` — first-row reservation race (DB `audit_tagsai_ai2`)

Existing suites run: `tests/test_tags.py` + `tests/test_ai_assistant.py` → **121 passed** (SQLite, shared session).
`$S/backend_tests.txt` (full suite) → 837 passed.

---

## 1. Inventory

### Tags (registered actions — verified list in `backend/app/services/tag_actions.py:686-749`)

| Action key | target_type | target optional | Delegates to | Status |
|---|---|---|---|---|
| `pet.feed` | pet | yes (NULL = all pets) | `pets.create_feeding` / `pets.feed_all` | Implemented + verified (PG T4–T6, T13; tests) — **race defect F-03** |
| `pet.care_task.done` | pet_care_task | no | `pets.complete_care_task` | Implemented + verified (PG T10, tests) |
| `plant.water` | plant | yes (NULL = all due) | `plants.complete_care_task` per water task / `plants.water_all` | Implemented + verified (PG T7, T8; tests) |
| `plant.care_task.done` | plant_care_task | no | `plants.complete_care_task` | Implemented + verified (PG T9; tests) |
| `chore.assignment.done` | chore | no | `chores.list_assignments` (materialize) + `chores.complete_assignment` | Implemented + verified — **target-drift defects F-01/F-02** |
| `shopping_list.open` | shopping_list | yes | navigation only (`execute=None`) | Implemented + verified (tests) |
| `todo.done` | todo | no | `todos.update_todo(is_done=True)` | Implemented + verified (PG T11; tests) |

There is **no** medication action (no `pet.medication.*` in the registry) — so no duplicate-medication path via tags.

Endpoints (`backend/app/routers/tags.py`): management `GET/POST /api/households/{id}/tags/`, `GET …/tags/targets`, `PATCH/DELETE …/tags/{tag_id}`, `POST …/{tag_id}/regenerate-token` (admin); scan `POST /api/tags/resolve/{token}`, `POST /api/tags/{token}/execute` (any member, `shared_limit` 30/min per IP and scope). Log redaction: `backend/app/core/log_redaction.py:13-16,38` — Implemented + verified by existing tests.

Frontend: `frontend/src/views/TagScanView.vue`, `frontend/src/utils/tagScan.ts`, `frontend/src/stores/tags.ts`, `frontend/src/views/TagsView.vue` — Implemented, flow verified by code reading; existing unit tests `utils/__tests__/tagScan.test.ts`.

Docs inconsistencies:
- `tag_actions.py:32` points to `TagResolveView.vue` — file does not exist (it is `TagScanView.vue`).
- `docs/security/tags-review.md` says "52 Tests" (file table) and "66 Tests" (Verifikation); actual `grep -c "def test_" tests/test_tags.py` = 65.
- `docs/qa/logic-review.md` §9 row "`chore.assignment.done` … ältere offene bleiben | ok" — **contradicted** by PG T1/T2 (only true for a single scan).

### AI assistant

| Feature | Where | Status |
|---|---|---|
| `GET /api/ai/status`, `GET/PUT /api/households/{id}/ai/settings` (admin opt-in) | `routers/ai.py:78-131` | Implemented + verified (tests) |
| `POST …/ai/recipe`, `POST …/ai/plant-care` | `routers/ai.py:204-225`, `services/ai/recipe.py`, `plant_care.py` | Implemented + verified (tests, mocked) |
| Daily quota per household & UTC day, reserve/release | `services/ai/usage.py` | Implemented + verified on PG (A1–A5) — **F-05 spurious 429**, **F-06 unmapped exceptions consume quota** |
| Concurrency semaphore (non-blocking → 503 `AI_BUSY`) | `services/ai/client.py:51,82-110` | Implemented + verified (A5, tests) |
| Frontend store / recipe card / save & add-to-shopping | `stores/ai.ts`, `components/AiRecipeCard.vue` | Implemented, code-read; tests `stores/__tests__/ai.test.ts` |
| Plant advice apply | `stores/plants.ts:345-370`, `utils/plantCare.ts:66-96`, `views/PlantDetailView.vue:191-208`, `views/PlantsView.vue:183-193` | Implemented, code-read; tests `plants.test.ts` |
| Receipt scan, weekly plan (Etappe 2) | `docs/ai-assistant.md` §9 | Planned (G) — not a defect |

---

## 2. Invariants

| Invariant | Where enforced | Ops that can violate | Status | Existing tests | Missing tests |
|---|---|---|---|---|---|
| Tag execute acts on the target the user confirmed on resolve | **nowhere** — no token/assignment pinning; `TagExecuteRequest` only has `slot` (`tags.py:151-153`) | `chore.assignment.done` (re-selected at execute, `tag_actions.py:588`), `plant.water` all (`water_all` at execute) | **Violated** (PG T3) | none | PG: resolve → external complete → execute must 409 |
| One scan of a chore tag completes at most the current period | `current_chore_assignment` (`tag_actions.py:509-550`) | second/parallel scan | **Violated** (PG T1, T2) | `test_prefers_current_period_over_older_backlog` (single scan only) | double scan, parallel scan |
| One feeding per pet/date/slot | `uq_feeding_pet_date_slot` (`models.py:869`) | parallel scans | Verified (PG T5, T6: 1 row, others 409/`changed=false`) | `test_second_feed_same_slot_409` | — |
| "Feed all" feeds every unfed pet or reports error | `pets.feed_all` (`pets.py:423-430`) | feed-all concurrent with a single feed | **Violated** (PG T4: 3/6 runs, Y,Z unfed, `changed=false`) | none | PG race test |
| Daily AI quota never exceeded | `usage._try_increment` `UPDATE … WHERE calls < limit` (`usage.py:34-44`) | parallel requests | Verified (PG A1: 12 parallel/limit 5 → 5 ok, 5 provider calls; A2 ×2: 20 parallel → never > 5) | `test_daily_limit_*` (SQLite) | PG concurrency test in suite |
| Quota not consumed by calls the provider never answered | `_run_feature` release for `_NOT_BILLED` (`ai.py:191-198`) | exceptions outside `AiError` | **Partially violated** (PG A3: `APIResponseValidationError`, `RuntimeError` → 500 + `calls=1`) | `test_sdk_errors_are_mapped_and_not_counted` | unmapped SDK exceptions |
| Request is only rejected as over-limit when limit is reached | `usage.reserve_call` (`usage.py:54-58`) | first request(s) of a UTC day in parallel | **Violated** (pg_ai_firstrow: 429 with 5–9 of 50 used) | none | PG first-row race |
| Tag mutations = same side effects as REST (notified_at reset, socket payloads, version bump, logs) | delegation to router functions | — | Verified by code comparison (see §3 F-table) + PG emits (T7 4×`plant_care_logged`, T11 version 1→3) | `test_resolve_and_execute*` check emits | — |
| Token alone authorizes nothing; foreign household 403; disabled 410; rotated 404; deleted target 404 | `tags.py:236-277` | — | Verified (PG T12 + tests) | many | — |
| AI cannot mutate household data | no tools; results only returned (`ai.py:9-10`) | — | Verified (code: endpoints write only `ai_usage`) | `test_user_input_is_data…` | — |
| Plant-advice apply does not duplicate tasks | `planAdvice` with fresh read (`plants.ts:350`) + UI busy flag (`PlantDetailView.vue:197`) | two tabs/devices applying simultaneously | Partially verified (code) | `plants.test.ts` | — |

---

## 3. Findings

### F-01 — Chore tag: repeated (or parallel) scans complete additional, older/future assignments
- **Severity:** High · **Class:** A (implementation defect)
- **Modules:** `backend/app/services/tag_actions.py:509-600`, `backend/app/services/chore_scheduler.py:172-177`
- **Observed:** each scan picks "the most recent open assignment with due_date ≤ today", so after the current one is done the *next* scan completes the previous week's open assignment, then the one before. Two simultaneous scans complete two different assignments (the materializer's `SELECT … FOR UPDATE` on chores serializes them, the second then sees today's done and takes the backlog). Every response reports `changed: true` and the UI shows the success message.
- **Expected:** a scan completes only the current period; once it is done, further scans report "already done" (`changed=false`/`can_execute=false`). The docstring itself says "Ältere offene Zuweisungen bleiben unangetastet".
- **Reproduction / evidence (`pg_tags.py` T1, T2, PG):**
  ```
  === T1 chore: sequential double scan with backlog ===
  execute#1: 200 True 2026-10-10
  execute#2: 200 True 2026-10-03
  execute#3: 200 True 2026-09-26
  === T2 chore: two parallel scans ===
  parallel: 200 True 2026-10-03
  parallel: 200 True 2026-10-10
  ```
  Decisive code: `tag_actions.py:536-540`
  `current = base.filter(ChoreAssignment.due_date <= today).order_by(ChoreAssignment.due_date.desc()).first()`
  and if none, `:542-549` picks the next one up to 6 days ahead (so for a chore due in ≤6 days a second scan can also tick off next period early).
- **Root cause:** "current" is recomputed per call from whatever is still open; no notion of "this period already done".
- **Business impact:** household history is falsified (backlog of other members marked done by the scanner, `completed_by` = scanner, rotation fairness/stats wrong); a double tap, NFC re-read, or "retry" after a network error silently consumes another assignment. Phones commonly fire NFC twice.
- **Fix:** define the current period as the latest assignment with `due_date ≤ today` **regardless of completion** (or the next within 6 days if none); if it is already completed → `changed=false` / describe `ALREADY_DONE`. Additionally pin the target (F-02).
- **Regression test:** PG integration: chore with 2 open past assignments → execute twice → second returns `changed=false`, backlog untouched; parallel variant with `H.parallel`.
- **Confidence:** High.

### F-02 — No target pinning between resolve and execute (chore, plant.water "all")
- **Severity:** Medium · **Class:** A/B
- **Modules:** `routers/tags.py:151-153,484-513`, `tag_actions.py:588`, `plants.py:345-381`
- **Observed:** resolve shows assignment X (due today, assigned to Ben). Ben ticks it off in the app. The scanner then taps the button: execute silently completes assignment of 2026-10-03 instead (`same as shown? False`). Same mechanism for `plant.water` without target: execute waters whatever is due at execute time, not the `due_count` shown.
- **Evidence (`pg_tags.py` T3):**
  ```
  resolve shows 2026-10-10 91efcbec-…
  Ben completes via app: 200
  execute after: 200 True completed due_date 2026-10-03 same as shown? False
  ```
- **Expected:** execute acts on the confirmed object or fails with 409 "already done / changed meanwhile".
- **Fix:** return a `confirm` token from resolve (e.g. `assignment_id`, or a hash of the target ids/versions) and require it in `TagExecuteRequest`; execute verifies it is still open. Cheap version: echo `details.assignment_id` back as an optional param and validate.
- **Regression test:** PG: resolve → REST complete → execute with pinned id → 409/`changed=false`.
- **Confidence:** High.

### F-03 — `feed_all` race: some pets stay unfed while the response says "nothing changed"
- **Severity:** Medium · **Class:** A
- **Modules:** `backend/app/routers/pets.py:381-440` (used by tag `pet.feed` without target and by the app's "feed all" button); UI `TagScanView.vue:245-247` (`successNoChange`)
- **Observed:** if any other feeding for one of the pets commits concurrently (single-pet tag scan, app tap, second feed-all), feed-all's whole batch hits `uq_feeding_pet_date_slot`, is rolled back, and returns `[]`. Pets that nobody fed (Y, Z) remain unfed; tag result `changed=false` → UI "War schon erledigt — nichts geändert."
- **Evidence (`pg_tags.py` T4, 6 attempts, PG):**
  ```
  attempt 0: single=200 changed=True; feed-all=200 changed=False; fed pets now=['X']
  attempt 2: single=200 changed=True; feed-all=200 changed=False; fed pets now=['X']
  attempt 5: single=200 changed=True; feed-all=200 changed=False; fed pets now=['X']
  ```
  Code: `pets.py:426-430` `except IntegrityError: db.rollback(); # … einfach leere Liste zurückgeben, Client refetcht; return []`
- **Expected:** all pets unfed at commit time are fed (per-row insert with `ON CONFLICT DO NOTHING` or per-pet savepoints), response lists what was actually created.
- **Business impact:** animals miss a meal while two household members each believe someone fed them (exactly the coordination problem the feature is meant to solve). Requires near-simultaneous actions (e.g. two people at breakfast) — rare but realistic.
- **Fix:** `insert(FeedingLog).on_conflict_do_nothing(...)` per pet or `begin_nested()` per pet; re-query created rows.
- **Regression test:** PG `H.parallel`: single feed X + feed-all → afterwards X,Y,Z all fed.
- **Confidence:** High.

### F-04 — `changed=true` / success shown for no-op or duplicate completions (care tasks, plant water, todo races)
- **Severity:** Low · **Class:** F (C for plants: E-4)
- **Modules:** `tag_actions.py:318` (`pet.care_task.done` always `changed: True`), `:484` (`plant.care_task.done`), `:392-427`; `describe` for both care-task actions never sets `can_execute=False`.
- **Evidence:** T10 `resolve2 can_execute True … exec2 True` (care task already done today, re-done; `next_due` unchanged but reported as change). T9: parallel `plant.care_task.done` → 2 logs. T7: parallel `plant.water` (all) → 4 logs for 2 tasks (sequential 3rd scan correctly `changed=false`). T8: single-plant water writes logs on every scan and also completes a *non-due* second water task (label "Winter", next_due today+20 → today+30). T11: parallel `todo.done` → both `changed=true`, two `todo_updated` events, `done_at` overwritten, version 1→3.
- **Expected (proposal):** care-task/water actions idempotent per household day (`last_done_at == today` → `changed=false`, describe `ALREADY_DONE`); todo via conditional update `WHERE is_done = false`.
- **Impact:** duplicate log entries in plant history; misleading "done" feedback; low harm (due dates computed from today anyway). Plant duplicate logging is documented E-4 (`tags-review.md` "Mehrfach-Scan").
- **Confidence:** High.

### F-05 — AI quota: spurious `AI_DAILY_LIMIT_REACHED` on first concurrent requests of a UTC day
- **Severity:** Low · **Class:** A
- **Module:** `backend/app/services/ai/usage.py:54-58`
- **Observed:** when the day's row does not exist yet, a request whose UPDATE matched 0 rows but whose subsequent `exists` SELECT sees the row just inserted by a parallel request raises "limit reached" without retrying the increment.
- **Evidence (`pg_ai_firstrow.py`, limit 50, 10 parallel, PG):**
  ```
  trial 1 Counter({(200,'ok'): 9, (429,'AI_DAILY_LIMIT_REACHED'): 1}) calls counted: 9 (limit 50)
  trial 3 Counter({(200,'ok'): 5, (429,'AI_DAILY_LIMIT_REACHED'): 5}) calls counted: 5 (limit 50)
  ```
  Code: `if exists: db.rollback(); raise AiDailyLimitReached("Daily limit reached")`.
- **Fix:** when the row exists, retry `_try_increment` once before raising (or `INSERT … ON CONFLICT DO UPDATE SET calls = calls + 1 WHERE calls < limit RETURNING`).
- **Impact:** user sees "Tageslimit erreicht" although almost nothing was used; only at the first parallel calls of a UTC day. The limit itself is never exceeded (verified).
- **Regression test:** PG parallel test with fresh day row, assert no 429 below limit.
- **Confidence:** High.

### F-06 — AI: exceptions outside the mapped set → HTTP 500 and the call stays counted
- **Severity:** Low · **Class:** A
- **Modules:** `services/ai/client.py:95-110`, `routers/ai.py:191-198`
- **Observed:** `anthropic.APIResponseValidationError` (subclass of `APIError`, not of `APIStatusError`/`APIConnectionError`) or any unexpected exception propagates raw: 500 to the client and `calls` remains incremented (no `release_call`).
- **Evidence (`pg_ai.py` A3):** `respvalid -> ('EXC','APIResponseValidationError') usage: [('2026-10-10', 1, 0, 0)]`, `runtime -> ('EXC','RuntimeError') usage: [… 1 …]`. (Mapped ones correct: `conn`/`status500` → 502, calls 0; `valerr` → 502, calls 1 as documented A-02.) The semaphore is released correctly (`finally`).
- **Fix:** add `except anthropic.APIError` → `AiUnavailable`; in `_run_feature` add a generic `except Exception: release_call(...); raise`.
- **Confidence:** High.

### F-07 — AI: transient failures temporarily hold quota → concurrent successful requests get 429
- **Severity:** Low · **Class:** D/E (inherent to reservation design)
- **Evidence (`pg_ai.py` A4):** limit 5, 8 parallel requests that end in connection errors: 5×502, **3×429**, final `calls=0`. A successful request racing with slow failing ones can be refused although the day ends with unused quota.
- **Recommendation:** accept and document, or let the frontend retry once on 429 if `calls_today < limit` after refetching settings.
- **Confidence:** High.

### F-08 — AI "fehlende Zutaten": partial failure + retry duplicates shopping items (L-12 still open)
- **Severity:** Low · **Class:** C/F
- **Modules:** `frontend/src/stores/ai.ts:146-161`, `components/AiRecipeCard.vue:86-107`
- **Observed (code reading):** items are added sequentially; if item k fails, items 1..k-1 remain, `missingAdded` stays `null`, the button reappears, and a retry adds 1..k-1 again. No dedupe against existing entries (L-12). Recipe save is guarded (`saving`/`saved`, `AiRecipeCard.vue:68-83`).
- **Fix:** use a backend bulk endpoint with dedupe (as the recipe "missing ingredients" endpoint does), or client-side dedupe against the active list.
- **Confidence:** Medium (behaviour of `shopping.addItem` offline queue not exercised).

### F-09 — AI suggestion can land in another household after a household switch
- **Severity:** Low · **Class:** A (minor)
- **Module:** `frontend/src/stores/ai.ts:101-125,212-216`
- **Observed (code reading):** `reset()` runs on household switch, but an in-flight `suggestRecipe`/`fetchPlantCare` assigns `recipeSuggestion.value`/`plantAdvice.value` after the await without checking that the household is still the same; "Speichern" then calls `useFoodStore().createRecipe` for the *new* current household; the quota was charged to the old one. Content is the user's own input, so no data leak, but the recipe is saved to an unintended household.
- **Fix:** capture `householdId` and drop the result if `currentHouseholdId` changed (pattern `captureHousehold` already exists in `stores/plants.ts`).
- **Confidence:** Medium (unverified in browser).

### F-10 — Pet feed tag blocks the other slot
- **Severity:** Low · **Class:** F
- **Evidence:** T13 `default slot morning -> resolve can_execute False ALREADY_FED`; `TagScanView.vue` shows the slot picker only in `confirm` state, so when the default slot is fed the user cannot log the other slot via the tag (e.g. early evening feeding at 13:30; or morning feeding forgotten and logged after 14:00 when evening already fed).
- **Fix:** `can_execute` = any slot unfed; preselect the unfed slot.
- **Confidence:** High.

### Verified correct (no finding)
- Side effects equal to REST: tags call the router functions with the same `membership` and session, so `notified_at` reset (`pets.py:917`, `plants.py:231`), `next_due_at` from today, `PlantCareLog`, socket payloads (`plant_care_task_updated`, `plant_care_logged`, `feeding_created`, `chore_assignment_updated`, `todo_updated` with full response incl. `version`), reminder marking on todo done (`todos.py:251-254`) and the version bump are identical. Only additions: `tag_updated` event after use (`tags.py:280-286`) and chore materialization emits on resolve (same as `GET /assignments`).
- Feeding uniqueness under parallel tag scans: T5/T6 exactly one row per pet/slot; losers get 409 (`already_done` in UI) or `changed=false`.
- Household isolation: user only in household B → 403 on A's tag; user in both → resolves with the tag's household (T12). Disabled → 410, rotated old token → 404, deleted target → 404 `TAG_TARGET_NOT_FOUND`; failed scans don't increment `use_count` (T12).
- Session expiration: `/t/:token` requires auth → `/login?redirect=/t/<token>` (`router/index.ts:172`), 401 during execute → refresh + one retry (`api/client.ts:42-66`); "retry" on scan errors re-runs `resolve`, not `execute`.
- AI: opt-in + key checked before reservation (`require_ai_enabled` dependency), the limit is never exceeded on PG, network/5xx/busy failures release the reservation, prompt injection can only change suggestion content (no tools, no writes), AI endpoints never touch other household data. Recipe save goes through `RecipeCreate` validation (`food` router). Plant advice apply re-reads tasks, is guarded against double tap, appends (never overwrites) `care_notes`, fills `species` only if empty, and leaves labelled tasks untouched.

---

## 4. Prior review status

| Item | Status now | Evidence |
|---|---|---|
| L-10 / E-3 (paused chore; tag rejects `CHORE_INACTIVE`) | Still open (decision) | `tag_actions.py:573-574,583-587` unchanged |
| L-11 / E-1 / E-2 (due from today; interval change doesn't move due) | Still open — also affects AI advice apply (see §5) | `plants.py:229-230`, `update_care_task` only resets `notified_at` when `next_due_at` given |
| L-12 / E-9 (AI missing ingredients no dedupe) | Still open | `stores/ai.ts:157-160` |
| L-17 / E-8 (AI day = UTC) | Still open (documented) | `usage.py:30-31` `today_utc()` |
| E-4 (multi-scan `plant.water` logs again) | Still open; broader than documented: also parallel "all" (T7), `plant.care_task.done` (T9), non-due water tasks of the plant (T8) | PG T7–T9 |
| logic-review §9 "chore.assignment.done … ältere offene bleiben — ok" | **Regressed/incorrect**: only holds for the first scan | F-01 |
| logic-review §9 "Mehrfachausführung pet.feed → 409/ALREADY_FED — ok" | Verified for single pet; feed-all race is new F-03 | T4–T6 |
| logic-review §10 "Tageslimit-Reservierung bei Fehlschlag — ok" | Verified for mapped errors; F-06 for unmapped | A3 |
| A-01 (limit multipliable via more households) | Still open | no global/user limit in `usage.py` |
| A-02 (schema error counted without tokens) | Still as documented | A3 `valerr` calls=1 tokens 0 |
| A-03..A-06 | Unchanged (operational/info) | — |
| Tags T-01..T-10 | T-01/T-02/T-06/T-07/T-08 still correct (T12 + existing tests); T-03/T-09 operational | — |

---

## 5. Cross-module effects

| Source op | Dependent entities | What can go inconsistent |
|---|---|---|
| Chore tag scan (F-01) | `chore_assignments` backlog of other members, completed_by stats, dashboard/task list | backlog vanishes without anyone doing it; "who did what" wrong |
| Chore tag resolve | `list_assignments` materialization + `chore_assignment_created` emits | resolve is not side-effect free (acceptable, same as GET) |
| `feed_all` rollback (F-03) | `feeding_logs`, dashboard feeding status, push reminders | pets shown unfed while scanner was told "already done" |
| `plant.water` (target) | all water tasks of the plant incl. not-due ones | seasonal/secondary water task rescheduled from today (T8: +20 → +30 days) |
| AI plant advice apply → `PATCH care-tasks interval_days` | `next_due_at` (unchanged, L-11/E-2) | new shorter interval only takes effect after next completion (e.g. water every 3 days but next due still in 13 days) |
| AI plant advice apply on *unlabelled* task | user-chosen interval | silently replaced by AI value; UI only shows counts ("n aktualisiert"), not old→new |
| Household switch during AI request (F-09) | recipes of the new household | suggestion saved to wrong household |
| Tag execute success | `tags.use_count`, `tag_updated` socket (contains token) to all members | fine (members can see token anyway, T-05) |

---

## 6. Test gaps

| Scenario | Recommended type |
|---|---|
| Chore tag double scan / parallel scan must not complete backlog (F-01) | PG integration (`H.parallel`) + unit with SQLite for sequential |
| Resolve → external completion → execute (F-02) | PG integration |
| Feed-all concurrent with single feed: all pets fed (F-03) | PG integration |
| Parallel `plant.water`/`plant.care_task.done`/`todo.done` idempotency | PG integration |
| AI first-row race no spurious 429 (F-05); limit never exceeded on PG | PG integration (mock client) |
| Unmapped SDK exception releases quota and returns 502 (F-06) | unit (mock) |
| AI result discarded after household switch (F-09) | frontend store unit (vitest) |
| addMissingToShopping partial failure / retry (F-08) | frontend store unit |
| Tag scan E2E: NFC double read (two quick navigations to `/t/<token>`) | E2E (Playwright) |

---

## 7. Product decisions

1. **What does a repeated chore scan mean?** a) no-op once current period done (recommended); b) allow completing backlog but only with an explicit second confirmation showing the date; c) current behaviour (each scan takes the next open one).
2. **Idempotency window for care/water tags (E-4):** a) per household day — `changed=false` if `last_done_at == today` (recommended); b) time window (e.g. 10 min) to absorb double reads only; c) keep logging every scan.
3. **`plant.water` with target and several water tasks:** a) complete only due/overdue water tasks, fall back to the earliest if none due (recommended); b) all water tasks (today).
4. **Feed tag slot:** a) block only when both slots fed and preselect the unfed one (recommended); b) current (block when default slot fed).
5. **AI plant advice vs. manual intervals:** a) show old→new per task and let the user deselect (recommended); b) never overwrite existing tasks, only create missing; c) current (overwrite unlabelled).
6. **AI day boundary (E-8):** a) UTC (current, documented); b) household timezone. Recommendation: b only if users report confusion; low impact.

---

## 8. Unverified

- Real NFC behaviour (double NDEF reads on Android) — no device; reasoning only.
- Frontend F-08/F-09 behaviours — code reading only; vitest tests would have to live inside the repo (not allowed), so not executed.
- Real Anthropic API behaviour (refusal content shape, whether a refusal produces partially invalid JSON that would surface as `AI_INVALID_OUTPUT` instead of `AI_REFUSED`) — never called; SDK source shows `parse_text` validates text blocks before the `stop_reason` check in `client.py:118`, so a refusal with non-JSON text would become `AiInvalidOutput` without tokens (reasoned, Low).
- Behaviour with multiple uvicorn workers (semaphore and IP limit are per process) — documented A-05.
- Note: running the existing pytest files did not modify any tracked file (`git status` clean); `backend/.coverage` (git-ignored) has a recent mtime that may come from a parallel run.
