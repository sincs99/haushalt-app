# Audit area: pets_plants_documents

Scope: Pets (profiles, feeding, feed-all, medications and administration logs, care tasks, photos), Plants (records, care tasks, care logs, next-due computation, water-all, photos, applying AI advice), Documents and files (upload, protected download, multi-page documents, quota, file references, deletion, orphan cleanup, expiry reminders).

Code state: working tree at audit time (read-only). Scripts are in `$S/work/pets_plants_documents/` (`s1_pets.py`, `s2_files.py`, `s3_plants_push.py`) and run against PostgreSQL 16 through `$S/pg/pgharness.py`, with real Alembic migrations and one session per request. Output excerpts below are copied verbatim.

---

## 1. Inventory

| Feature / endpoint / store | Status |
|---|---|
| Pet CRUD `routers/pets.py:285-531` | Implemented and verified (scoping tests `test_pet_scoping.py`, PG `s1`) |
| Feeding create/undo `pets.py:535-620`, unique `(pet_id,date,slot)` `models.py:869` | Implemented and verified. PG `s1` S1: concurrent duplicates return 201 + 409 |
| Feed-all `pets.py:381-439` | Implemented, but the race behaviour is **defective** (PPD-01). No backend test for the endpoint itself; only `test_tags.py::test_feed_all_pets` via the tag action |
| Feeding status `pets.py:336-377` | Implemented and verified (`test_feeding_status_returns_today`) |
| Medications CRUD + give + log `pets.py:629-802` | Implemented and verified (`test_medication_scoping.py`, PG `s1` S3). No duplicate guard and no history protection (PPD-02/03/04) |
| Pet care tasks `pets.py:811-952` | Implemented and verified (`test_pet_care_scoping.py`, PG `s1` S4) |
| Pet/plant photos (`photo_file_id`, `file_in_use`) `pets.py:465-485`, `plants.py:406-425` | Implemented and verified sequentially (`test_file_references.py`). Concurrent claim not protected (PPD-05) |
| Plant CRUD, care tasks, care log `routers/plants.py` | Implemented and verified (`test_plants.py`, PG `s3`) |
| Water-all `plants.py:345-380` | Implemented and verified for "only due water tasks" (`test_water_all_only_due_water_tasks`, PG `s3` P3). Concurrent duplicates (PPD-08) |
| AI advice application `frontend/src/stores/plants.ts:345-370`, `utils/plantCare.ts:37-87` | Implemented, but behaviour is not verified by me (store tests exist in the frontend suite). Months×30 is documented (`docs/ai-assistant.md:208`) |
| File upload/download/delete `routers/files.py:387-476` | Implemented and verified (`test_files_scoping.py`, PG `s2` F5/F7) |
| Storage quota `files.py:228-250` | Implemented and verified sequentially (`test_files_upload_respects_quota`). **Not enforced under concurrency** (PPD-06) |
| Orphan cleanup `files.py:332-356`, `services/file_cleanup.py` | Implemented and verified for the basic case (`test_delete_orphan_files`). Race with attach (PPD-07) |
| Documents (create from file_ids, multipart upload, pages add/reorder/remove, delete) `routers/documents.py` | Implemented and verified (`test_documents.py`, PG `s2` F6) |
| Document expiry push `push_service.py:368-406` | Implemented and verified (`test_push_chores_documents.py`, PG `s2` F8, `s3` PU2) |
| Pet/plant care push `push_service.py:238-297` | Implemented and verified (`test_push.py`, PG `s3` PU1) |
| Household deletion removes upload dir `households.py:183-194` | Implemented and verified (PG `s2` F9) |
| Frontend stores `pets.ts`, `plants.ts`, `documents.ts` | Implemented. I verified the relevant flows by reading the code only |
| "Assumed vs recorded" feeding | Not a concept in the app. Feed-all writes real `FeedingLog` rows attributed to the tapping user |
| Docs: `PROJECT-STATUS.md:697` says files are removed "beim Auflösen des Haushalts" | Consistent with the code |

---

## 2. Invariants

| Invariant | Enforced at | Operations that can violate it | Status | Existing tests | Missing tests |
|---|---|---|---|---|---|
| At most one feeding per pet/day/slot | DB unique `models.py:869`; 409 at `pets.py:561-571` | none | **Verified** (PG S1: `{(201, 409): 8}`) | `test_feeding_duplicate_returns_409` | PG concurrency test |
| Feed-all feeds every not-yet-fed pet, or reports exactly what it did | `pets.py:396-429` | Feed-all concurrent with a single feeding | **Violated** (PPD-01) | none for the endpoint | PG race test |
| Medication administration recorded once per real dose | none | double tap from two devices; two people | **Violated / requires product decision** (PPD-03) | — | — |
| Medication history is kept and auditable | logs have no delete endpoint (PG: `404`) | `DELETE medication`, `DELETE pet` cascade (`models.py:917-919, 858-860`, FK CASCADE `:931-933`) | **Partially verified**: immutable per entry, but history is lost with the parent (PPD-04) | `test_user_can_delete_medication` | test that logs survive / are archived |
| Care task `next_due_at = today + interval` after completion (E-1a) | `pets.py:914-917`, `plants.py:230-232` | — | Verified (PG S4: completing a task due 2026-10-01 on 2026-10-10 gives 2026-11-09) | `test_complete_care_task_updates_dates` | — |
| `notified_at` reset when due date moves (L-06) | `pets.py:885-886`, `plants.py:556-557` | — | **Verified** (PG S4 `move due -> notified_at reset: True`) | `test_update_care_task_due_date_resets_notified_at` | — |
| One push per due cycle; a completed task is not pushed | `_claim` `push_service.py:190-199` plus the expire-on-commit reload | completion between check and UPDATE (µs window) | **Verified** for the realistic window (PG PU1/PU2) | `test_push.py` | — |
| A file belongs to at most one of {document, pet photo, plant photo} | `DocumentFile.file_id` unique (`models.py:1273-1278`); `file_in_use` check (`files.py:286-320`) | concurrent pet/plant PATCH + document create | **Violated** under concurrency (PPD-05) | `test_document_cannot_claim_pet_photo`, `test_photo_cannot_use_pet_photo` | PG race |
| A document has ≥ 1 file | `documents.py:487-494` | orphan cleanup vs late attach (PPD-07) | **Violated** in an interleaving | `DOCUMENT_LAST_FILE` test | PG interleaving test |
| Household storage ≤ quota | `check_storage_quota` `files.py:241-250` | concurrent uploads | **Violated** (PPD-06) | `test_files_upload_respects_quota` | PG parallel test |
| Removed member cannot read files | `verify_household_access` `deps.py:32-46` | — | **Verified** (PG F5: 200 → 403 after removal; foreign household path 404; no token 401) | `test_files_scoping.py` | — |
| Multi-page upload is all-or-nothing | `documents.py:372-384` | — | **Verified** (PG F6: 422, DB rows 26→26, disk files 33→33) | — | — |
| Expiry reminders re-armed when expiry changes, and only then | `documents.py:404-410` | — | **Verified** (PG F8) | `test_changing_expiry_resets_notifications` | — |
| Water-all touches only due water tasks | `plants.py:353-361` | — | **Verified** (PG P3: 1 log for 3 tasks) | `test_water_all_only_due_water_tasks` | — |
| One care log per real completion | none | concurrent complete / water-all | **Violated** (PPD-08) | — | PG race |

---

## 3. Findings

### PPD-01 — A feed-all that loses a race reports "all already fed" while most pets stay unfed
- **Severity:** Medium · **Class:** A · **Modules:** `backend/app/routers/pets.py`, `frontend/src/views/PetsView.vue`, `frontend/src/stores/pets.ts`, `backend/app/services/tag_actions.py`
- **Refs:** `pets.py:396-429`; `PetsView.vue:145-157`; `de.json:755` (`"allAlreadyFed": "Alle sind schon gefüttert"`); `tag_actions.py:257-267`
- **Observed:** Feed-all inserts one row per unfed pet in a single transaction. If any of those rows hits the unique constraint because someone fed a single pet at the same moment, the whole transaction is rolled back and the endpoint returns `[]`:
  ```python
  except IntegrityError:
      db.rollback()
      # Bei Race-Condition: einfach leere Liste zurückgeben, Client refetcht
      return []
  ```
  The UI then shows the info toast "Alle sind schon gefüttert" (`if (created.length === 0) notifyInfo(t('pets.allAlreadyFed'))`). The tag action `pet.feed` without a target reports `changed: false` in the same case.
- **Expected:** Pets that were not fed get their feeding, or the client is told that the operation did not complete.
- **Repro / evidence:** `s1_pets.py` S2 has 4 pets. Thread A feeds pet 1 (evening) while thread B calls feed-all (evening), 30 trials:
  ```
  (feed-all status, feed-all returned n, pets fed in DB [4 pets]): {(200, 0, 1): 12, (200, 4, 4): 12, (200, 3, 4): 6}
  ```
  In 12 of 30 trials feed-all returned 0 rows and only 1 of 4 pets was fed. Feed-all against feed-all is harmless (`{((200,0),(200,4)), 4}: 15`) because the winner fed everyone.
- **Root cause:** An all-or-nothing transaction with optimistic duplicate handling, and the response gives no way to tell "lost race" from "nothing to do".
- **Impact:** Someone taps "Alle gefüttert", sees "all already fed" and leaves. Three cats go unfed. The status list does refresh, but the toast says the opposite.
- **Fix:** Insert per pet with `INSERT … ON CONFLICT (pet_id,date,slot) DO NOTHING RETURNING *` (PostgreSQL) or a savepoint per pet. Return the rows that were really created. Alternatively, return 409 on conflict and have the client retry once. The frontend should compare against the refreshed status before saying "all already fed".
- **Regression test:** PG integration test of the race above; assert that every pet is fed afterwards and the response lists the newly created rows.
- **Confidence:** High.

### PPD-02 — A second daily dose cannot be recorded in the UI
- **Severity:** Medium · **Class:** C/F · **Modules:** `frontend/src/views/PetDetailView.vue`
- **Refs:** `PetDetailView.vue:266-271` (`isGivenToday`), `:776-783` (`<BaseButton v-if="!isGivenToday(med.id)" … @click="handleGiveMedication(med.id)">`)
- **Observed:** The "Jetzt gegeben" button disappears once any log for today exists. `schedule` is free text (for example "2x täglich"), and nothing models doses per day. The API accepts a second dose (PG S3: `sequential double give: 201 201`), but the UI offers no way to record it. Inactive medications have no give button in the UI, yet the API still accepts a dose for them (PG: `give on inactive medication: 201`).
- **Expected:** A medication taken twice daily can be logged twice, ideally with a hint such as "zuletzt vor 2 h durch Ben".
- **Impact:** The second dose goes unrecorded. The next person cannot tell whether the evening dose was given, which risks a double dose or a missed one.
- **Fix:** Product decision (see section 7). The minimum is to keep the button visible after a dose and show "heute schon gegeben um HH:MM von X — nochmals erfassen?".
- **Confidence:** High (code reading). The UI path was not executed in a browser.

### PPD-03 — No duplicate guard for medication administration across people or devices
- **Severity:** Medium · **Class:** C (with B-flavour: the UI intends "once per day", the server does not enforce it) · **Refs:** `pets.py:750-775`
- **Observed:** `give` always inserts a row. There is no idempotency key and no interval check. The frontend double-tap guard (`run(..., {key: 'give-…'})`, `PetDetailView.vue:284-291`) only covers one device.
- **Evidence:** `s1_pets.py` S3: `parallel give by Anna+Ben: [201, 201]`.
- **Impact:** Two people give the pill and both log it. The log shows two doses, and nobody is warned before the second physical dose. The warning only appears after the socket update arrives.
- **Fix:** Optional `client_id` idempotency (the offline concept already has `client_ids`), plus a server response or a 409 with "zuletzt gegeben vor X min" inside a configurable minimum interval. The client then asks for confirmation.
- **Regression test:** PG parallel give with the same `client_id` produces 1 row.
- **Confidence:** High.

### PPD-04 — Deleting a medication or a pet permanently erases its administration and feeding history; any member can do it
- **Severity:** Medium · **Class:** C (product decision) / F · **Refs:** `models.py:858-863, 917-919, 931-933`; `pets.py:503-531, 720-741`; `de.json:704` ("Katze wirklich löschen?"), `:730` ("Medikament wirklich löschen?")
- **Observed:** PG S3: `Ben (non-admin member) deletes medication: 204` → `medication_logs before=5 after=0`. Deleting a pet cascades feedings, medications, logs and care tasks. Neither confirmation dialog mentions that history is lost. The non-destructive alternative (`active=false`) exists, but the UI never suggests it. Single feedings can also be deleted by any member without a record (PG S2c: `Ben deletes Anna's feeding: 204`; see PPD-09).
- **Impact:** A vet asks when the last antibiotic was given, and the answer is gone after one mis-tap on the trash icon. There is no undo and no trace of who deleted it.
- **Fix options:** (a) Soft delete (archived medications keep their logs). (b) Block deletion when logs exist and offer "deactivate" instead. (c) At least warn in the confirmation ("Verlauf mit N Gaben geht verloren").
- **Confidence:** High.

### PPD-05 — Concurrent attach can make one file shared by a pet photo and a document; a document-vs-document race returns 500
- **Severity:** Low · **Class:** A · **Refs:** `files.py:286-320` (check without lock), `documents.py:207-226, 303-325`, `pets.py:466-488`
- **Evidence (`s2_files.py`):**
  ```
  == F2 two documents claim the same file concurrently ==
  Counter({(201, 500): 5, (201, 422): 5})
  == F3 pet photo PATCH and document create on the same image concurrently ==
  (pet PATCH, doc POST): {(422, 201): 7, (200, 201): 8} trials ending with file shared by pet AND document: 8
  delete document -> 204
  pet photo after doc delete: None
  ```
- **Observed:** `DocumentFile.file_id` is unique, so document against document is safe for data, but the loser's `IntegrityError` is unhandled and returns 500 instead of `FILE_IN_USE`. Between a pet/plant photo and a document there is no DB constraint, so 8 of 15 races ended with both referencing the file. Deleting that document then deleted the pet's photo file (`photo_file_id` → NULL via SET NULL).
- **Practical reach:** The frontend always uploads fresh files right before attaching (`documents.ts:130-160`, `usePhotoUpload.ts`), so this only happens with crafted or API clients, or a double submit reusing ids. That is why it is rated Low.
- **Fix:** `SELECT … FOR UPDATE` on the `StoredFile` rows in `_claim_files` and in the photo PATCH. Map `IntegrityError` to 422 `FILE_IN_USE`. Or model ownership in one column (`stored_files.owner_kind/owner_id` with a unique constraint).
- **Confidence:** High.

### PPD-06 — The storage quota can be exceeded by concurrent uploads
- **Severity:** Low · **Class:** A/E · **Refs:** `files.py:241-250, 253-283`
- **Evidence:** `s2_files.py` F1 with a 1 MB quota and 8 parallel uploads of 200 KB:
  ```
  statuses: Counter({201: 7, 422: 1}) used_bytes: 1400063 quota: 1048576 exceeded: True
  ```
- **Root cause:** A SUM-then-insert check with no lock (READ COMMITTED).
- **Impact:** The overshoot is bounded by about (parallel uploads × 10 MB). It is an abuse or limit-integrity issue, not a data loss. The rate limit of 30/min caps it further.
- **Fix:** `SELECT … FROM households WHERE id=… FOR UPDATE` (or `pg_advisory_xact_lock(household)`) around the check and insert, or a `storage_used_bytes` counter with a conditional `UPDATE … WHERE used + :n <= quota`.
- **Confidence:** High.

### PPD-07 — Orphan cleanup can delete a file that was attached a moment earlier, leaving a document with 0 pages
- **Severity:** Low · **Class:** E · **Refs:** `files.py:335-356`
- **Evidence:** `s2_files.py` F4 uses the cleanup's exact query, interleaved by hand (select orphans → API attaches the file to a new document → cleanup deletes and commits):
  ```
  orphans selected: [True]
  attach: 201
  cleanup commit OK
  document after cleanup: 200 files: 0
  ```
  The ORM delete of `StoredFile` cascades `document_files` in the DB. The document survives with no files, which breaks the "≥ 1 file" rule, and the bytes are removed from disk.
- **Practical reach:** It needs a file uploaded more than 24 h earlier and attached during the cleanup's run window. The frontend uploads immediately before attaching, so in practice only API clients are affected. Probability is very low.
- **Fix:** Delete with a guarded statement (`DELETE … WHERE id=:id AND NOT EXISTS(...)` re-evaluated per row), or lock the rows `FOR UPDATE SKIP LOCKED` and have attach lock the `StoredFile` (same lock as PPD-05).
- **Confidence:** High for the interleaving, Low for real-world frequency.

### PPD-08 — Concurrent "complete" or "water-all" writes duplicate plant care logs
- **Severity:** Low · **Class:** A · **Refs:** `plants.py:222-244, 345-380, 575-602`
- **Evidence:** `s3_plants_push.py`:
  ```
  == P1 parallel complete same plant task ==  [200, 200] logs: 2
  (responses, logs in DB for 5 plants): {(((200, 5), (200, 5)), 10): 4, (((200, 0), (200, 5)), 5): 2}
  ```
  In 4 of 6 trials, two people pressing "alle giessen" produced 10 logs for 5 plants. Each user also gets a success toast for the same 5 plants.
- **Impact:** The schedule is unaffected because both writes compute the same `next_due_at`. Only the care history is duplicated (the 50-entry log fills with duplicates). The pet care complete is idempotent per day (PG S4 `['2026-11-09','2026-11-09']`).
- **Fix:** `water_all` should select `FOR UPDATE SKIP LOCKED` and re-check `next_due_at <= today`. Single complete can use a conditional update or E-4 option b (idempotent per day).
- **Confidence:** High.

### PPD-09 — A single tap deletes another member's feeding record, without confirmation or trace
- **Severity:** Low · **Class:** F/C · **Refs:** `stores/pets.ts:186-198` (toggle on an existing feeding = DELETE), `pets.py:588-620`
- **Observed:** A slot shown as "fed by Ben 07:12" turns back to "not fed" with one tap by Anna. An undo toast exists, but the deletion is not logged. PG S2c: `Ben deletes Anna's feeding: 204`.
- **Impact:** Someone taps by mistake or to check, the record is gone, and the next person feeds again (a double feeding).
- **Fix:** Ask for confirmation when the feeding was recorded by someone else, or more than N minutes ago.
- **Confidence:** High (code). The UI was not executed.

### PPD-10 — AI advice changes intervals but not due dates (E-2 follow-on); a shortened watering interval takes effect only after the next completion
- **Severity:** Low · **Class:** C · **Refs:** `utils/plantCare.ts:74-87`, `stores/plants.ts:345-359`, `plants.py:553-557`
- **Observed:** `planAdvice` updates only `interval_days` of the first unlabeled task of the same care type. The backend PATCH never recomputes `next_due_at` (PG P4: `interval 365->30, next_due stays: 2027-08-06`). For example, an existing water task due in 25 days stays due in 25 days even if the advice says every 7 days. Manual intervals on unlabeled tasks are overwritten (documented in `docs/ai-assistant.md:204`). Labelled tasks are left alone, and a `null` interval does not delete anything.
- **Partial failure:** The steps run sequentially with no rollback. A retry re-reads tasks from the server (`repo.fetchCareTasks`), so it does not create duplicates. Months×30 is documented (`docs/ai-assistant.md:208`, `plantCare.ts:37`).
- **Fix:** Decide E-2. If option b is chosen, recompute `next_due_at = last_done_at + new interval` (or `min(old, today + new)`) when the interval changes, and reset `notified_at`.
- **Confidence:** High.

### PPD-11 — Feed-all has no scope filter (all species, no inactive or deceased concept)
- **Severity:** Low · **Class:** C/G · **Refs:** `pets.py:390-394`; PG S2c: `feed-all fed 4 pets of 4 incl. fish+dog`
- **Observed:** Pets have no `active`/`deceased` field. The only option is to delete a pet, which also deletes its history (PPD-04). Feed-all also logs a feeding for a fish or a pet on a different feeding regime.
- **Fix:** Product decision: add an `archived` flag, or opt-out per pet from "alle füttern".
- **Confidence:** High.

---

## 4. Prior review status

| Item | Status now | Evidence |
|---|---|---|
| L-06 (pet `notified_at` reset on due move) | **Fixed, still holds** | `pets.py:884-886`; PG S4 `move due -> notified_at reset: True`; test `test_update_care_task_due_date_resets_notified_at` |
| L-07 (stores reset on household switch) | Fixed per `current-audit-fixes.md`; I did not re-check it behaviourally | — |
| L-11 / E-1 (next due counted from today) | **Open (decision)**, unchanged; same in both modules | `pets.py:914-916`, `plants.py:230-231`; PG S4 (2026-10-01 → completed on 10-10 → 11-09) |
| E-2 (interval change does not recompute due) | **Open (decision)**, unchanged; now also affects AI advice application (PPD-10) | PG P4 and S4 (`interval 30->7: next_due 2026-11-09 notified_at True`) |
| E-4 (repeated `plant.water` scan logs again) | **Open**; same root cause as PPD-08 | — |
| L-14 (reconnect reloads pets/plants only when the view is open) | Open (accepted Unschärfe); not re-verified | — |
| Section 4 rows "feed-all idempotency ok", "race → `[]` ok" | **Re-assessed: not ok** — the race leaves other pets unfed (PPD-01) | PG S2 |
| Section 4 "a file belongs to at most one pet/plant/document" | Holds sequentially; **violated under concurrency** (PPD-05) | PG F3 |
| current-audit-fixes "duplicate medication entry in the display" | Fixed for display; server-side duplicates remain possible (PPD-03) | PG S3 |

---

## 5. Cross-module effects

| Source operation | Dependent entities | What can become inconsistent |
|---|---|---|
| `DELETE /pets/{id}` | feedings, medications → medication_logs, care tasks, own photo `StoredFile` | All history is lost. The photo is deleted only if `file_in_use` says it is unused (correct sequentially). |
| `DELETE /documents/{id}` | `StoredFile`s of the pages | After the PPD-05 race, a pet or plant photo silently disappears (`photo_file_id` SET NULL). |
| Orphan cleanup | `StoredFile` → `document_files` (CASCADE), `pets/plants.photo_file_id` (SET NULL) | PPD-07: a document with 0 pages, or a photo that vanishes. |
| Tag `pet.feed` (no target) → `feed_all` | feedings | PPD-01: `changed:false` reported while pets are unfed. `feed_all` calls `db.rollback()` on the tag's session; anything else pending in the tag transaction is rolled back too (unverified, reasoned). |
| Tag `plant.water` → `_apply_completion` | care logs | Duplicate logs (E-4 / PPD-08). |
| Household leave by last member | rows CASCADE, `UPLOAD_DIR/{hid}` removed after commit | Verified (F9). An upload running at the same moment can write a file after `rmtree`. The DB insert then fails with an FK error and the file stays on disk with no row, so the DB-driven cleanup never finds it (reasoned, not run). |
| Member removal | file download | Verified: 403 immediately (F5). |
| Push scheduler vs completion/expiry change | `notified_at`, `expiry_*_notified_at` | Verified safe in practice: `_claim` commits after each row, which expires the ORM objects, so `next_due_at`/`expiry_date` are reloaded before the next row's check (PU1: completed task not pushed and not claimed; PU2: moved expiry not claimed). The remaining window is between that reload and the UPDATE (microseconds). |

---

## 6. Test gaps

| Scenario | Recommended type |
|---|---|
| Feed-all racing a single feeding; every pet fed and response accurate (PPD-01) | PG integration |
| Feed-all endpoint basic behaviour (only unfed pets, 2nd call `[]`) — no direct backend test exists | unit/API |
| Concurrent medication give with idempotency key (once designed) | PG integration |
| Medication delete keeps or archives logs (once decided) | API |
| `isGivenToday` / give button for multi-dose schedules | frontend component / E2E |
| Concurrent document claims → 422, never 500; photo vs document claim exclusive (PPD-05) | PG integration |
| Quota under 8 parallel uploads (PPD-06) | PG integration |
| Orphan cleanup vs attach interleaving (PPD-07) | PG integration (two sessions) |
| Parallel water-all / complete → one log per task (PPD-08) | PG integration |
| Push: completion between query and claim (this keeps the expire-on-commit protection from regressing) | PG integration |
| Household deletion while an upload is in flight | integration (filesystem) |
| `applyAdviceTasks` partial failure + retry produces no duplicates | frontend unit (store) |

---

## 7. Product decisions

1. **Multiple doses per day (PPD-02/03).**
   - (a) Keep "once per day" and hide the button (today).
   - (b) Always allow giving, and show the last dose with time and person, plus a confirmation inside N hours.
   - (c) Model `doses_per_day` / `min_interval_hours` on `Medication`, and have the server warn or return 409.

   **Recommendation: (b) now, (c) later.**
2. **Deleting medication or pet history (PPD-04).**
   - (a) Hard delete (today).
   - (b) Archive or soft delete, with history visible.
   - (c) Block deletion when logs exist and offer "deactivate".

   **Recommendation: (c) for medications, (b) for pets (status "verstorben/abgegeben").**
3. **Feed-all race semantics (PPD-01).**
   - (a) Skip conflicting pets per row (ON CONFLICT DO NOTHING).
   - (b) 409 + client retry.

   **Recommendation: (a).**
4. **E-1 / E-2** (unchanged). Recommended: E-1 a (from today) for pets/plants (documented); E-2 b when the interval changes from the AI advice, so the new rhythm takes effect.
5. **Feed-all scope (PPD-11).**
   - (a) All pets (today).
   - (b) Per-pet opt-out / archived pets excluded.

   **Recommendation: (b).**
6. **Deleting someone else's feeding (PPD-09).**
   - (a) As today.
   - (b) Confirm when it was recorded by another person.

   **Recommendation: (b).**

---

## 8. Unverified

- Frontend views (PetDetailView give button, PetsView feed-all toast, DocumentsView) were verified by code reading only. No browser or vitest run was done for them, because new test files would have to be placed inside the repo.
- The tag-action rollback side effect of `feed_all` (`db.rollback()` inside a tag transaction) is reasoned, not run.
- An upload racing household deletion (a file left on disk) is reasoned, not run.
- Real-world frequency of PPD-07 depends on API usage. The UI path makes it practically unreachable.
- `upload_file`: if `db.commit()` fails after `_storage.save`, the file stays on disk with no DB row, and the DB-driven orphan cleanup cannot find it (reasoned, `files.py:396-397`; not reproduced).
- Store-level double-tap guards (`pendingCompletions` in plants.ts, `pendingToggles` in pets.ts) were checked by reading, not executed.
