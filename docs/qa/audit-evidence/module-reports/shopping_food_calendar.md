# Audit: Shopping / Food (recipes, meal plan) / Calendar / Polls

Area: `shopping_food_calendar`. Repo state as checked out on 2026-10-10 (read-only).
Evidence scripts and outputs live in `$S/work/shopping_food_calendar/` (S = scratchpad):

| Script | What it checks | Output |
|---|---|---|
| `t_shopping.py` | duplicates, client-id resurrection, concurrent toggles/patches, store merge, list delete, list-delete vs create race | `t_shopping.out` |
| `t_food.py`, `t_food3.py` | recipe delete vs meal plan, add-missing dedupe and concurrency, concurrent meal PUT, `null` PATCH corruption | `t_food.out`, `t_food3.out` |
| `t_cal.py` | DST gap/overlap, all-day edit, `null` PATCH corruption, participants, ranges, calendar delete races | `t_cal.out` |
| `t_polls.py`, `t_vote.py` | concurrent decide, vote rules, decide vs calendar delete, meal-decide overwrite, recipe deletion, ex-member votes | `t_polls.out`, `t_vote.out` |
| `vt/mealdecide.test.ts` (+ `vt/vitest.audit.config.ts`) | frontend food store vs the `{date}` socket payload of meal-decide | passed (run with `npx vitest run --config …` from `frontend/`) |

All backend scripts use the PG harness (real Alembic migrations, PostgreSQL 16, one session per request). A TestClient with `raise_server_exceptions=False` was used so that 500s are observable as status codes (`sfc_common.py`). Race results vary from run to run. Below, "x of n" counts come from the runs I recorded.

---

## 1. Inventory

| Feature / endpoint / store | Status |
|---|---|
| Shopping lists CRUD (`shopping.py:281-421`), list position, delete with `?force` | Implemented and verified (PG: S9; tests `test_shopping_scoping.py`) |
| Shopping items CRUD with client IDs (`shopping.py:529-683`, `client_ids.py`) | Implemented and verified (PG: S2, S11; `test_offline_sync.py`) |
| Store normalisation, `GET /stores`, `POST /reassign-store` | Implemented and verified (PG: S7, S8; `test_shopping_stores.py`, 23 tests) |
| `version`/`updated_at` on lists/items (`models.py:26-54`) | Implemented and verified. Monotonic, one bump per update (PG F0). Used **only** to drop stale socket events on the client. There is no server-side precondition (stale `version` in the PATCH body is ignored, S3) |
| Item assignment (`assigned_to_user_id`), member validation | Implemented and verified (PG S5). Ex-member stays assigned (L-15) |
| Frontend `stores/shopping.ts` (optimistic add/toggle/delete/assign, undo via `restoreItems`, `upsertVersioned`) | Implemented. Unit tests exist (`shopping.test.ts`). Edit-sheet lost update is not covered (F-9) |
| Recipes CRUD API (`food.py:239-336`) | Implemented but only partly behaviourally verified. The PATCH `null` path corrupts data (F-2) |
| Recipe create/edit/delete **in the UI** | Planned (`PROJECT-STATUS.md:883`). **Docs inconsistent:** Epic 15 (`PROJECT-STATUS.md:1106`) says "FoodView.vue (… Rezept-CRUD …)". In the UI, recipes come only from the AI card, and only `is_favorite` is ever PATCHed |
| Meal plan GET week / PUT upsert / DELETE (`food.py:345-462`) | Implemented. Concurrent PUT to the same day gives a 500 (F-6) |
| "Fehlende Zutaten" → shopping (`food.py:466-566`) | Implemented and verified (PG F2; `test_food_shopping.py`). Not concurrency-safe (F-7) |
| AI "missing ingredients" → shopping (`stores/ai.ts:145-161`) | Implemented. No dedupe (L-12 still open) |
| AI recipe save (`services/ai/recipe.py:36-61` → `RecipeCreate`) | Implemented and verified by code reading: output is clipped to the `RecipeCreate` limits and re-validated by `POST /recipes`. A double-submit guard exists (`AiRecipeCard.vue:68-84`) |
| Calendars CRUD, last-calendar and non-empty guards (`calendars.py`) | Implemented. The guards are not race-safe (F-3, F-10) |
| Events CRUD, household wall-clock time (`events.py`, `event_times.py`) | Implemented and verified (PG C1-C7; `test_event_times.py`). DST gap handling is surprising (F-11). `participant_ids` is not validated (F-12). PATCH `null` corrupts (F-1) |
| Event reminders / notifications | **Not implemented and not listed as planned** (no event code in `push_service.py`; only socket `event_*`) → product decision C |
| Dashboard / widget "today's events" | Implemented. Only events that *start* today are shown (`dashboard.py:263-272`, `widget.py:236-244`). Multi-day events are missing (already documented as "Unschärfe" in logic-review §3) |
| Polls: create / vote / change vote / decide / meal-decide / delete (`polls.py`) | Implemented and verified (PG P1-P13, `t_vote`; tests `test_poll_scoping.py`, `test_meal_poll.py`, `test_db_integrity.py`) |
| Frontend `stores/polls.ts` | Implemented. **No unit tests** (as stated in `PROJECT-STATUS.md`). No versioning, so a REST response can overwrite a newer socket state |
| Frontend `stores/food.ts` | Implemented. Unit tests exist. The `{date}`-only payload breaks the store (F-4, verified with vitest) |
| Frontend `stores/calendar.ts`, `CalendarView.vue`, `CalendarMonthGrid.vue` | Implemented. Unit tests for the store (`calendar.test.ts`) |
| Socket docs `PROJECT-STATUS.md` §6 | **Docs inconsistent:** `event_created` "nach `decide` einer Umfrage `{ id, title }`" is outdated (L-03 fixed, full `EventResponse` is sent). `meal_plan_updated` "nach meal-decide `{ date }`" is documented, but the frontend cannot handle it (F-4) |

---

## 2. Invariants

| Invariant | Where enforced | Operations that can violate it | Status | Existing tests | Missing tests |
|---|---|---|---|---|---|
| A poll is decided at most once and produces ≤1 event | `polls.py:133-149` conditional UPDATE `status='offen'→'entschieden'` | none found | **Verified** (PG P1: 10 rounds × 3 parallel decides → always `(200,400,400)`, exactly 10 events) | `test_decided_poll_cannot_be_decided_again` (SQLite, sequential) | PG concurrency test |
| A decided event poll has its event (or the event was deliberately deleted) | none | `DELETE /calendars/{id}` racing with `decide` | **Violated** (P5: in 3 of 6 rounds the poll is `entschieden`, `decided_event_id` NULL, and the decider got a 500) | — | PG race test |
| One vote per user per poll | `uq_poll_vote_poll_user` (`models.py` EventPollVote) + IntegrityError swallow (`polls.py:338-341`) | — | **Verified** (`t_vote`: 10 × 2 parallel vote changes → always 1 vote) | `test_one_vote_per_user_and_poll` | — |
| No voting / deciding on a decided poll | `polls.py:297-298, 375-376, 467-468` | — | **Verified** (P3) | `test_vote_on_decided_poll_rejected` | — |
| Vote option belongs to the poll | `polls.py:301-306` | — | **Verified** (P3) | — | — |
| Poll recipe options belong to the household | `polls.py:206-221` (**meal polls only**) | event-type poll with a foreign `recipe_id` | **Partially verified / violated** (P10: event poll accepts a foreign household's recipe id, 201) | `test_poll_scoping.py` | yes |
| Household has ≥1 calendar | `calendars.py:178-188` count check | two concurrent deletes | **Violated** (C10: `[204,204]`, 0 calendars left, in 1 of 2 runs) | — | PG race |
| A calendar with events cannot be deleted | `calendars.py:190-200` count check | concurrent event create / poll decide | **Violated** (C9: create returned 201 but the event was cascaded away. 2 of 3 successful creates were lost in the second run) | — | PG race |
| Event `starts_at`/`calendar_id`/`title`/`participant_ids` well-formed | DB NOT NULL. Pydantic for create | PATCH with explicit `null` | **Violated** for `participant_ids` (C5: JSON `null` persisted → reads 500). Others → 500 without persisting | — | yes |
| `ends_at >= starts_at` | `events.py:358-362, 440-448` | — | **Verified** (C4). DST gap makes valid wall-clock input fail (F-11) | `test_event_times.py` | DST gap test |
| Event times = household wall clock | `event_times.py:76-89` | DST gap (nonexistent time shifted +1h), DST overlap (resolved to first occurrence) | **Partially verified** (C1/C2) | `test_naive_time_is_household_wall_clock`, `test_winter_time_offset` | gap/overlap tests |
| Recipe `ingredients` is a list | DB NOT NULL (JSON), `RecipeUpdate.validate_ingredients` (`food.py:92-102`) | PATCH `{"ingredients": null}` | **Violated** (F3: JSON `null` persisted → `GET /recipes` and `GET /meal-plan` 500 for the whole household) | — | yes |
| Meal plan entry has recipe or free text | `food.py:381-389` (PUT only) | recipe DELETE (ORM nullifies FK, `models.py:1103`), poll option recipe deleted then decided (handled) | **Violated** by recipe delete (F1: entry with `recipe_id=None, free_text=None`) | — | yes |
| One meal plan entry per household+date | `uq_meal_plan_household_date` | concurrent PUT / meal-decide | **Verified as a constraint**, but surfaces as 500 (F3: 4/4 rounds one 500. P9: 4/5 rounds one 500, poll stays open) | — | PG race |
| Meal-decide does not silently destroy a planned meal | none | `meal-decide` on an occupied date | **Requires product decision** (P7: "Grosis Geburtstag – Fondue" silently replaced by "Risotto") | `test_meal_poll_decide_*` (no occupied-day case) | yes |
| Shopping item belongs to an existing list of the same household | `shopping.py:543-549` + FK | list force-deleted concurrently | **Partially verified** (S10: 2-3 of 5 rounds → 500 FK violation instead of 4xx). No orphan rows | `test_shopping_scoping.py` | PG race |
| Created shopping item stays deleted | none (no tombstones) | delete followed by delayed retry with the same client ID | **Violated, documented limitation** (S2/S11, `PROJECT-STATUS.md:891`) | `test_item_delete_twice_is_204_then_404` | — |
| Same-name open items are not duplicated | only in add-missing (`food.py:505-513`) | parallel manual adds (S1), parallel add-missing (F2b), AI path (L-12) | **Requires product decision** for manual adds. **Violated** for add-missing under concurrency | `test_add_missing_to_shopping_skips_duplicates` | PG race |
| ≤1 default "Einkaufsliste" created by add-missing | `food.py:211-230` (check-then-insert) | parallel add-missing in a household without lists | **Violated** (F2c: two "Einkaufsliste" at position 0) | `test_add_missing_to_shopping_creates_list_if_none` | PG race |
| Concurrent edits to different item fields both survive | backend PATCH applies only sent fields | UI edit sheet always sends name+quantity+store+category | **Violated in the UI** (F-9, code reading). Backend alone OK | — | component test |
| Store groups case-insensitive, canonical spelling | `shopping.py:46-98, 473-523` | rename racing with a create that uses the old name (S8: old name survives, acceptable) | **Verified** | 23 tests | — |

---

## 3. Findings

### F-1. PATCH `participant_ids: null` persists JSON `null` → the event and every calendar range containing it return 500
- **Severity:** High · **Class:** A
- **Modules:** `backend/app/routers/events.py:254-261, 459-467`; `models.py:713`.
- **Observed:** `PATCH /events/{id}` with `{"participant_ids": null}` returns 500, **but the value is committed**. After that, `GET /events/{id}` returns 500, and `GET /events?from_date=2026-11-16&to_date=2026-11-22` returns 500. Every calendar view (week, month, list) that covers this event fails, for every member, until someone repairs the row through the API. For the other NOT NULL fields (`title`, `starts_at`, `calendar_id`, `all_day`), PATCH `null` gives a 500 without persisting.
- **Evidence:** `t_cal.out` C5:
  ```
  participant_ids=null 500 Internal Server Error
     GET single: 500  db participant_ids: null
   GET range containing corrupted event: 500
   GET range Oct (unaffected): 200
  ```
- **Root cause:** `if "participant_ids" in update_data and update_data["participant_ids"] is not None:` skips conversion. `setattr(item, "participant_ids", None)` then stores the JSON literal `null`, because a SQLAlchemy `JSON` column stores Python `None` as JSON `null` unless `none_as_null=True`, so NOT NULL does not catch it. The commit happens before response validation (`EventResponse.participant_ids: list[uuid.UUID]`) fails.
- **Expected:** 422, or treat `null` as `[]`.
- **Impact:** One malformed request (an API client, a future offline replay, or a buggy UI build) takes down the shared calendar for the whole household. The current UI always sends an array, so this is not reachable by normal UI use.
- **Repro:** create an event, then `PATCH {"participant_ids": null}`, then `GET /events?from_date=…`.
- **Fix:** In `EventUpdate`, reject `null` for non-nullable fields with a model validator (generic pattern: `for f in NON_NULLABLE: if f in fields_set and getattr(self, f) is None: raise`), or map `participant_ids=None → []`. Also consider `JSON(none_as_null=True)` for the NOT NULL JSON columns, so the DB rejects it.
- **Regression test:** PATCH with `null` for each non-nullable field → 422. The row is unchanged and the GET range is 200.
- **Confidence:** High.

### F-2. PATCH recipe `ingredients: null` persists JSON `null` → `GET /recipes` and `GET /meal-plan` return 500 for the whole household
- **Severity:** High · **Class:** A
- **Modules:** `food.py:92-102` (`validate_ingredients` returns `None` for `None`), `food.py:305-310`, `models.py:1094`.
- **Observed** (`t_food3.out`):
  ```
  PATCH ingredients=null 500
  P|null|null                      <- DB: ingredients is JSON null
  GET recipes 500
  GET meal-plan week 500
  repair PATCH 200
  ```
  `name`/`servings`/`is_favorite` = null → 500 without persisting (NOT NULL violation). `steps`/`tags` are safe because their validators coerce `None → []`.
- **Root cause:** Same JSON-`null` mechanism as F-1. The validator was written to pass `None` through.
- **Impact:** The Food page (week plan and recipe list) is unusable for everyone until the recipe is repaired via the API. There is no UI path today (the UI only PATCHes `is_favorite`). The planned recipe-edit UI, or any API client, would hit this.
- **Fix:** coerce `None → []` like `steps`/`tags`, or reject it. Add a generic "explicit null on a non-nullable field → 422" rule to all `*Update` schemas.
- **Test:** `PATCH {"ingredients": null}` → 422 or `[]`; `GET /recipes` stays 200.
- **Confidence:** High.

### F-3. Calendar delete races: a just-created event (or a poll's decided event) is silently cascaded away, and the decided poll stays closed without an event
- **Severity:** Medium (silent loss of a confirmed event; rare, it needs concurrent actions) · **Class:** A
- **Modules:** `calendars.py:190-203`; `models.py:685-687` (`Calendar.events` relationship `cascade="all, delete-orphan"`); `polls.py:400-425`.
- **Observed:**
  - C9 (create event vs delete empty calendar, 6 rounds): `(204,201)` twice, `(204,500)` twice, `(422,201)` once. Afterwards only **1** of the 3 events answered with 201 exists in the DB. There are 0 orphan rows, so the events were deleted, not orphaned.
  - P5 (decide vs delete calendar, 6 rounds): `((204,500),'entschieden',False)` three times. The decide transaction committed (poll closed, event created). Then the calendar delete loaded `cal.events`, saw the committed event, and deleted it. `decided_event_id` was set to NULL. The decider's post-commit `_event_response` then failed → 500.
- **Root cause:** The event-count check and the delete are not atomic (READ COMMITTED). The ORM cascade on `Calendar.events` deletes whatever events exist at flush time, instead of the delete failing.
- **Expected:** Either the delete fails with `CALENDAR_NOT_EMPTY`, or the create/decide fails cleanly (and the poll stays open).
- **Impact:** A user gets "Termin gespeichert" or "Abstimmung entschieden", but the event is gone. The poll can't be decided again (it's `entschieden`), and the user gets an error toast even though the poll did close. Low likelihood in a household, high confusion when it happens.
- **Fix:** Lock the calendar row (`SELECT … FOR UPDATE`) in delete_calendar, create_event, update_event (when calendar_id changes) and decide. Or remove the ORM cascade, set `passive_deletes=True` and change the FK to `ondelete="RESTRICT"`, so that a concurrent insert makes the delete fail (IntegrityError → 422). In decide, validate the calendar *after* `_claim_poll`, inside the same locked transaction.
- **Test:** A PG concurrency test: delete calendar ‖ create event / decide. Invariant: no response 201/200 without a persisted event. No poll with `entschieden` and `decided_event_id IS NULL` unless the event was deleted explicitly.
- **Confidence:** High (reproduced several times. The mechanism is explained by the code).

### F-4. Meal-poll decision blanks the day on other devices (socket payload `{date}` replaces the entry)
- **Severity:** Medium · **Class:** A
- **Modules:** `polls.py:525-529` (emits `{"date": …}`); `frontend/src/stores/food.ts:208-215` (`handleMealPlanUpdated` replaces the entry with the payload); `views/FoodView.vue:151-155` (display); `FoodView.vue:345-359` (only the decider refetches).
- **Observed:** PG P7 emits `('meal_plan_updated', {'date': '2026-10-20'})`. The vitest `vt/mealdecide.test.ts` passed: after the socket event the entry becomes `{"date":"2026-10-20"}` (no id, recipe or free_text). `getDisplayName` then shows "Kein Essen geplant" (`food.noMeal`). Other members see the day as **empty** until they reload or reconnect. On the deciding device, the refetch races with the socket event: if the socket arrives after the refetch, the decider sees an empty day as well.
- **Expected:** Emit the full `MealPlanEntryResponse` (as PUT does, `food.py:422-426`), or have the client refetch on a partial payload.
- **Impact:** The household "decided" dinner and it shows as nothing planned. People may plan something else or assign the day again.
- **Fix:** In `meal_decide_poll`, `db.refresh(entry)` and emit `MealPlanEntryResponse.model_validate(entry)`. Update the docs table.
- **Test:** backend: the emit payload has `id`, `recipe_id`, `free_text`. Frontend: `handleMealPlanUpdated` ignores or refetches payloads without `id`.
- **Confidence:** High.

### F-5. Meal-poll decision silently overwrites an existing meal plan entry
- **Severity:** Medium · **Class:** C (product decision; behaviour is intentional in code: "Upsert: wenn Datum schon belegt, updaten", `polls.py:488`)
- **Observed:** P7: the day had `free_text "Grosis Geburtstag – Fondue"`. After meal-decide it is `recipe Risotto`, with no warning in the API or the UI (`FoodView.confirmDecide` only confirms the option). There is no undo.
- **Impact:** A deliberately planned meal is lost without trace. Two members (manual plan vs poll) contradict each other silently.
- **Recommendation:** see Product decisions PD-3. Minimum: the decide dialog shows "Am … ist bereits X geplant – ersetzen?".
- **Confidence:** High.

### F-6. Concurrent writes to the same meal plan day → 500 (meal plan PUT and meal-decide)
- **Severity:** Medium · **Class:** A
- **Modules:** `food.py:395-419` (query then insert); `polls.py:491-514`.
- **Observed:** F3: 4/4 rounds of two parallel PUTs on an empty day → `[200,500]`. P9: two meal polls for the same date decided in parallel → in 4 of 5 rounds one 500, and that poll stays `offen` (correctly rolled back, but the user sees a generic error).
- **Root cause:** check-then-insert without `ON CONFLICT`. The unique constraint `uq_meal_plan_household_date` protects integrity but surfaces as an unhandled IntegrityError.
- **Fix:** `INSERT … ON CONFLICT (household_id, date) DO UPDATE` (PG) or catch IntegrityError → re-read and update (and retry the meal-decide once).
- **Test:** PG parallel PUT → both 200, one row, last writer wins.
- **Confidence:** High.

### F-7. "Fehlende Zutaten" is not concurrency-safe: duplicate items and a duplicate default list
- **Severity:** Low-Medium · **Class:** A
- **Modules:** `food.py:211-230, 494-530`.
- **Observed:** F2b: two members press the button at the same time → both `added: ['Reis','Kokosmilch','Curry']`, "Reis count: 2". F2c: household without lists → two lists "Einkaufsliste" (both position 0).
- **Root cause:** read-check-insert without a lock or unique key.
- **Fix:** Serialize per household/list (e.g. `SELECT … FOR UPDATE` on the target list, or a `pg_advisory_xact_lock(hash(household_id))`), and create the default list under the same lock.
- **Confidence:** High.

### F-8. Recipe delete leaves "empty" meal plan entries; the frontend keeps showing the deleted recipe
- **Severity:** Low (no recipe-delete UI today) · **Class:** A/B
- **Modules:** `food.py:321-336`; `models.py:1103-1105` (relationship without `passive_deletes`: the ORM sets `recipe_id = NULL`); `stores/food.ts:204-206` (`handleRecipeDeleted` does not touch `weekPlan`).
- **Observed:** F1: `entry after delete: [('2026-10-12', None, None, None)]`. "add-missing" on it → 400 `MEAL_PLAN_NO_RECIPE`. Other clients still show the old recipe name until reload. After reload the UI shows "Kein Essen geplant", while the entry still exists in the DB.
- **Fix:** On recipe delete, either copy `recipe.name` into `free_text` for the referencing entries (keeps the plan meaningful), or delete them and emit `meal_plan_deleted`. In the frontend, update `weekPlan` in `handleRecipeDeleted`.
- **Confidence:** High.

### F-9. Shopping edit sheet overwrites concurrent changes to other fields (lost update)
- **Severity:** Low-Medium · **Class:** A (contradicts logic-review §5 "Gleichzeitige Bearbeitung zweier Felder → beide bleiben (LWW pro Feld)", which holds only for the raw API)
- **Modules:** `components/ShoppingList.vue:233-250` (`editItem = { ...item }` snapshot), `components/ShoppingItemEditSheet.vue:66-75` (always emits name, quantity, store, category); backend has no version precondition (`shopping.py:612-648`; S3: a stale `version` in the body is ignored).
- **Scenario:** Anna opens "Milch" to fix the name. Ben sets the quantity "2 l". Anna saves → `quantity` is reset to the old value without notice.
- **Fix:** Send only changed fields (diff the form against the opened snapshot). Optionally add `If-Match: version` → 409 on mismatch.
- **Evidence:** code reading. Backend field-merge behaviour verified (S3/F0).
- **Confidence:** Medium-High.

### F-10. Two concurrent calendar deletes can leave the household with zero calendars
- **Severity:** Low · **Class:** B (rule "letzter Kalender darf nicht gelöscht werden" is not race-safe)
- **Modules:** `calendars.py:178-188`.
- **Observed:** C10 run 1: `statuses [204, 204] remaining calendars: 0`. Run 2: `[204, 422]`.
- **Impact:** Events can't be created until someone adds a calendar. Recoverable.
- **Fix:** Lock the household's calendar rows (`SELECT … FOR UPDATE` on all calendars of the household) before counting.
- **Confidence:** High.

### F-11. DST gap: a nonexistent local time is shifted +1 h, and a valid-looking range is rejected as "end before start"
- **Severity:** Low (once a year, 02:00-03:00 local) · **Class:** A/C
- **Modules:** `event_times.py:76-80` (`dt.replace(tzinfo=tz)` with fold=0).
- **Observed** (`t_cal.out` C1/C2):
  - `02:30–03:15` on 2026-03-29 → **422 EVENT_END_BEFORE_START** (02:30 is treated as 02:30+01:00 = 01:30Z, and 03:15+02:00 = 01:15Z).
  - `02:30–03:45` → stored `01:30Z–01:45Z` and shown as `03:30+02:00 – 03:45+02:00` (start silently moved +1h, duration 15 min instead of 75).
  - Ambiguous 2026-10-25 02:30 → first occurrence (CEST, `00:30Z`). Deterministic, acceptable.
- **Fix:** Normalize gap times: if `to_utc(local).astimezone(tz).replace(tzinfo=None) != local`, either reject with a specific error or map consistently and validate *after* normalization. Document overlap → first occurrence.
- **Test:** `test_event_times.py` for the gap and the overlap.
- **Confidence:** High.

### F-12. Event participants are not validated (non-members, foreign-household users, duplicates accepted)
- **Severity:** Low · **Class:** B (already noted as "Unschärfe" in logic-review §3, still open)
- **Modules:** `events.py:372-382, 459-461`.
- **Observed:** C6: random UUID, the same user twice, and a user of another household → all 201 and stored.
- **Impact:** The UI shows "?" avatars and wrong counts. The foreign user ID is stored in the household's data. Nothing leaks back to that user.
- **Fix:** Validate against `HouseholdMember` and dedupe. Allow already-stored ex-members on PATCH (same pattern as L-05).
- **Confidence:** High.

### F-13. Shopping item create into a concurrently force-deleted list → 500
- **Severity:** Low · **Class:** A
- **Modules:** `shopping.py:543-583` (`commit_or_get_existing` re-raises an IntegrityError that is not a PK collision).
- **Observed:** S10: `[204, 500]` in 2-3 of 5 rounds (FK violation on `list_id`).
- **Fix:** In `commit_or_get_existing`, when `existing is None` and the list is gone → 400/404 `list not found`. The frontend rollback already removes the optimistic item.
- **Confidence:** High.

### F-14. Explicit `null` on non-nullable fields → 500 across shopping, recipes, events (no data change except F-1/F-2)
- **Severity:** Low · **Class:** A
- **Observed:** S6 (`name`, `is_checked` null → 500), F5, C5.
- **Fix:** Same generic schema rule as F-1. Return 422.
- **Confidence:** High.

### F-15. Event poll accepts recipe IDs of another household
- **Severity:** Low · **Class:** B
- **Modules:** `polls.py:205-221` (validation only for `poll_type == "meal"`).
- **Observed:** P10: event poll with a foreign `recipe_id` → 201. The meal poll is correctly rejected with 400.
- **Impact:** A cross-household reference. If the foreign recipe is deleted, the option's FK is set to NULL (cross-tenant side effect). No content leaks.
- **Fix:** Validate for all poll types, or reject `recipe_id` on event polls.
- **Confidence:** High.

### F-16. AI "missing ingredients" path: no dedupe, a different target list, and retries after a partial failure duplicate items (L-12)
- **Severity:** Low-Medium · **Class:** C (E-9 open)
- **Modules:** `stores/ai.ts:145-161` (`for … await shopping.addItem`); compare `food.py:494-513` (first list by position, dedupe against open items).
- **Observed (code):** No duplicate check. Targets the *active* list, while the recipe endpoint targets the *first* list, so the same household gets ingredients on different lists depending on which button was used. If one `addItem` fails mid-loop, the function throws: earlier items stay, `missingAdded` stays `null`, the button stays enabled (`AiRecipeCard.vue:211-216`), and pressing it again re-adds the earlier items.
- **Recommendation:** E-9 option b: send the suggestions to a backend bulk endpoint with the same dedupe (and with quantity merged into the name, or kept separate consistently).
- **Confidence:** High (code reading).

### F-17. Poll option times in UTC (L-13) → the decide toast can show the wrong day
- **Severity:** Low · **Class:** A (UI consequence of the C-classified L-13)
- **Modules:** `polls.py:48-53` (no conversion); `CalendarView.vue:609` (`eventDate(option.starts_at)` = first 10 chars of a UTC string).
- **Observed:** P2: `['2026-10-17T17:00:00Z', …]` for 19:00 local. An option at 00:30-01:59 local is reported as the previous day in the "decided on …" toast. The event itself is correct (`decide` converts properly, P3: `2026-10-18T12:00:00+02:00`).
- **Fix:** E-10 option b: return the option times in household time (reuse `to_household_time`).
- **Confidence:** High.

### F-18. Poll decided without `starts_at` creates a timed event "now" (with microseconds)
- **Severity:** Low · **Class:** C/F
- **Observed:** P6: `2026-10-10T09:01:36.946699+02:00`. The frontend warns about this ("Ohne Startzeit legt das Backend den Termin auf jetzt", `CalendarView.vue:607`). This is intentional, but it rarely matches what the household meant.
- **Recommendation:** Require `starts_at` for event-poll options, or ask for a date in the decide dialog, or create an all-day event for today.
- **Confidence:** High.

### Verified correct (no finding)
- Concurrent `decide` → exactly one event (P1). Deciding twice / voting after the decision / voting for an option of another poll → 400 (P3). Changing a vote moves it (P3). Concurrent vote changes → still exactly 1 vote (`t_vote`).
- Deleting the decided event: `decided_event_id → NULL`, the poll stays `entschieden` (P4, matches `models.py` comment).
- Recipe deleted between vote and meal-decide: the option's `recipe_id` becomes NULL and the decision falls back to the label as `free_text` (P8). Correct.
- Editing the title of an all-day event does not shift times, either as a partial PATCH or with the full UI payload (C3).
- Range queries: date-only `to_date` includes the whole last day. Multi-day events starting before the range are included (C7). Consistent across week/month/list (all use `GET /events` + `expandEventToDays`).
- Calendar delete with events → 422 `CALENDAR_NOT_EMPTY` (C8) (outside the race).
- Store merge: `coop` → `MIGROS` merges into the existing canonical `Migros` (S7).
- Client-ID idempotency for items and lists, and the cross-household ID → 409 (existing tests). Concurrent same-ID create (existing test `test_concurrent_item_create_with_same_id_returns_existing`).
- `version` is bumped atomically, once per update, under concurrency (F0: 8 parallel PATCHes → versions 2..9, all distinct).

---

## 4. Prior review status

| Item | Status now | Evidence |
|---|---|---|
| L-03 decide emits only `{id,title}` | **Fixed** (full EventResponse, `polls.py:432-439`). PROJECT-STATUS socket table still documents the old payload (**docs stale**) | code, `test_decide_emits_full_event_payload` |
| L-12 AI missing ingredients no dedupe | **Still open** (F-16) | `stores/ai.ts:145-161` |
| L-13 poll option times in UTC | **Still open**, and now has a visible consequence in the decide toast (F-17) | P2 |
| L-14 reconnect reload only for open views | **Unchanged** (`App.vue:290-297` `refreshAllStores`; FoodView/CalendarView reload on reconnect while open) | code reading |
| L-15 ex-member stays `assigned_to_user_id` on shopping items | **Still open** (`households.py:161-224` does not clear assignments). E-6 open | code reading |
| logic-review §3 "Teilnehmer nicht validiert" | **Still open** (F-12) | C6 |
| logic-review §3 "Dashboard: mehrtägige Termine fehlen" | **Still open** (`dashboard.py:263-272`, `widget.py:236-244`) | code reading |
| logic-review §3 "Zwei gleichzeitige decide → genau ein Termin" | **Verified on PG** | P1 |
| logic-review §3 "Kalender mit Terminen löschen → 422" | Correct sequentially, **not race-safe** (F-3) | C8/C9 |
| logic-review §5 "Gleichzeitige Bearbeitung zweier Felder: beide bleiben" | True for the API. **False for the UI** (F-9) | code |
| logic-review §5 "Zutaten mit Menge im Text" | Still as described ("200 g Mehl" is not deduped against "Mehl") | F2 |
| logic-review §5 "Löschen vs. Bearbeiten → Löschen gewinnt" | Correct, except for create retries (documented tombstone limitation) | S2 |
| E-6, E-9, E-10 | open (unchanged) | — |
| Known limitation "Wiederholtes Anlegen nach Löschen" (`PROJECT-STATUS.md:891`) | Confirmed: re-POST with the same client ID after a delete → 201 and `shopping_item_created` emitted (S2). Same for lists (S11). **D, documented** | S2/S11 |

---

## 5. Cross-module effects

| Source operation | Dependent entities | What can become inconsistent |
|---|---|---|
| `DELETE /calendars/{id}` (concurrent) | events, `event_polls.decided_event_id` | Event silently cascaded; poll `entschieden` without event; client shows the event until reload (F-3) |
| `DELETE /recipes/{id}` | `meal_plan_entries.recipe_id` (ORM nullify), `event_poll_options.recipe_id` (SET NULL) | Empty meal plan entries (F-8); frontend weekPlan still shows the recipe; poll options lose the link (handled by the label fallback) |
| `POST /polls/{id}/meal-decide` | meal plan entry for `decided_meal_date` | Existing entry overwritten (F-5); other clients show the day as empty (F-4); concurrent decide → 500 (F-6) |
| `POST /polls/{id}/decide` | events, dashboard (`dashboardStore.invalidate`), calendar | OK normally; with the calendar race see F-3 |
| `POST /meal-plan/{id}/add-missing-to-shopping` | shopping lists (may create one), shopping items | Duplicate default list / items under concurrency (F-7); targets the first list while the AI path targets the active list (F-16) |
| `POST /households/{id}/leave` | `shopping_items.assigned_to_user_id`, `event_poll_votes`, `events.participant_ids`, `event_polls.created_by_user_id` | Ex-member stays assigned (L-15); **ex-member's poll vote still counts** (P13: votes `[1,0]` after Carla left); ex-member stays listed as a participant |
| `PATCH events participant_ids=null` / `PATCH recipe ingredients=null` | all range reads / week plan reads | Household-wide 500 (F-1, F-2) |
| `DELETE /shopping-lists/{id}?force` | items (DB cascade) | Frontend `handleListDeleted`/`deleteList` (`shopping.ts:103-117, 438-446`) do not remove the list's items from `items` (invisible but kept in memory until the next fetch; harmless today) |

---

## 6. Test gaps

| Scenario | Recommended test type |
|---|---|
| Explicit `null` on every non-nullable PATCH field (events, recipes, shopping) → 422, row unchanged | unit/API (runs on SQLite too, but the JSON-null persistence needs PG to be faithful) |
| Calendar delete ‖ event create / poll decide; two calendar deletes in parallel | PG integration (concurrency) |
| Concurrent decide on PG (currently only sequential SQLite tests) | PG integration |
| Concurrent meal plan PUT and meal-decide on the same date | PG integration |
| Concurrent add-missing-to-shopping (items and default list) | PG integration |
| Meal-decide on an occupied date (expected behaviour per decision) and the socket payload shape | API unit + frontend store unit |
| `handleMealPlanUpdated` with a partial payload; `handleRecipeDeleted` updates weekPlan | frontend unit (vitest) |
| Polls store (no tests at all): vote rollback, REST-vs-socket ordering | frontend unit |
| Edit sheet sends only changed fields (lost update) | component test / E2E with two clients |
| DST gap/overlap creation and edit round-trip | unit (`test_event_times.py`) |
| Participant validation | API unit |
| Recipe delete → meal plan entries | API unit |
| Item create into a deleted list → 4xx | PG integration |
| Property-based: `range_bounds` + `expandEventToDays` agree for random events incl. DST days | property-based (hypothesis) + vitest |

---

## 7. Product decisions

| # | Question | Options | Recommendation |
|---|---|---|---|
| PD-1 | Two members add the same item ("Milch") | a) keep separate (today, S1) · b) merge into one open item with the same normalized name (append quantity text) · c) warn in the UI ("Milch steht schon auf der Liste") | c: cheap and keeps free-text quantities intact. b is hard while quantity is free text |
| PD-2 | Quantity as free text (`"-5 kg; DROP"` accepted, S12) | a) keep free text · b) structured amount + unit | a for now; b only if merge/sum features are wanted |
| PD-3 | Meal-decide on a day that already has a meal | a) overwrite silently (today) · b) confirm in the dialog with the existing meal shown · c) reject with 409 unless `replace=true` | b in the UI plus c in the API (protects other clients/races) |
| PD-4 | Ex-member's poll votes | a) keep counting (today) · b) remove on leave · c) keep but mark | b for open polls, keep for decided ones |
| PD-5 | Event poll option without time | a) "now" (today) · b) require a time · c) all-day event on decision date | b |
| PD-6 | Event reminders / notifications | a) none (today; only live socket updates) · b) push X minutes before for participants · c) daily digest | Decide explicitly and document. Today nothing reminds anyone of an event, and nothing in the docs lists it as planned |
| PD-7 | Delete-then-retry resurrection (tombstones) | a) accept (documented) · b) short-lived tombstones for client IDs | a until offline M1. Then b is required |
| PD-8 | Recipe deleted that is still scheduled | a) entry keeps the name as free text · b) entry removed · c) deletion blocked while scheduled in the future | a |
| PD-9 | DST gap times | a) shift +1h silently (today) · b) reject with a clear error · c) shift and tell the user | b or c |
| PD-10 | Dashboard/widget "today" and multi-day events | a) start day only (today) · b) every day the event spans, like the calendar | b (consistency with the calendar views) |

---

## 8. Unverified

- **iOS/Safari behaviour** and real socket ordering (meal-decide socket vs refetch on the deciding device): reasoned from code. The partial-payload effect itself was verified in vitest.
- **Edit-sheet lost update (F-9):** verified by code reading only. No two-client E2E was run.
- **Polls store REST-vs-socket overwrite:** `votePoll` writes the REST response without a version check (`stores/polls.ts:84-89`), so a slower response can hide another member's vote until the next event. Reasoned, not reproduced.
- **AI path (L-12/F-16):** code reading only. The Anthropic API is not called. The partial-failure retry duplication is reasoned.
- **Frontend handling of zero calendars (F-10 aftermath):** not exercised in a browser.
- **Range consistency for device timezone ≠ household timezone:** the frontend computes "today" and week starts from the device clock (`calendar.ts:20-26`, `food.ts:13-20`). Not tested with a different device TZ.
- Race outcomes are probabilistic. The counts quoted are from my runs (PG 16 local, READ COMMITTED).
