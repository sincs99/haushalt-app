# Area "households" — households, users, permissions, auth/session lifecycle, Socket.IO authz, widget tokens

Auditor scripts (all under `$S/work/households/`, S = scratchpad):

| Script | What it does | Runs on |
|---|---|---|
| `races.py` | 7 concurrency scenarios × 15 runs (leave/leave, leave/join, remove/leave, double join, double register, double refresh) | PostgreSQL 16 via `pgharness` (real Alembic schema, one session per request, `H.parallel`) |
| `refresh_race.py` | 2 concurrent `/refresh` with the same token, 40 runs, with 0 ms and up to 20 ms jitter | PG |
| `grace_three.py` | the same refresh token used three times within the grace window | PG |
| `orphan_join.py` | produces an orphan household through the real race, then joins it with the invite code | PG |
| `lifecycle.py` | effects of leave/remove on widget token, stale JWT, recurring bill payer, todos, events, badge, push recipients, unvalidated assignees | PG |
| `route_audit.py` | walks every FastAPI route and classifies it as admin / member / user-only / no auth | static (imports app) |
| `staleSwitch.test.ts` + `vitest.hh.config.ts` | Pinia stores: a delayed response from household A arrives after the switch to B | vitest 4 with the repo's `node_modules`; the test file stays in the scratchpad |

The repo was not modified.

---

## 1. Inventory

| Feature / endpoint / store | Status | Evidence |
|---|---|---|
| `POST /api/auth/register` (new household → admin; invite code → member; expired code 410) | Implemented + verified (tests `test_register.py`; PG `races.py`) | Concurrent duplicate e-mail → **500** (F-10) |
| `POST /api/auth/login` (timing equalisation, rate limit 5/min) | Implemented + verified (`test_auth_refresh.py`, `test_security_hardening.py`) | — |
| `POST /api/auth/refresh` (rotation, reuse detection, 30 s grace, cookie/CSRF) | Implemented, **defective under concurrency** | `refresh_race.py`, `grace_three.py` (F-01) |
| `POST /api/auth/logout` (revoke one token, disconnect all sockets of user) | Implemented + verified (tests); semantics documented (PROJECT-STATUS §8 "Logout trennt Sockets aller Geräte") | — |
| `GET /api/auth/me` | Implemented + verified | `lifecycle.py`: ex-member gets `households: []` |
| „Überall abmelden“, Passwort ändern, Konto löschen | **Planned / not present** (G) | PROJECT-STATUS §7 „Überall abmelden“; no endpoints (`grep password routers/` → only auth.py) |
| `POST /api/households/` create (+ default calendar) | Implemented + verified (`test_households.py`) | — |
| `POST /api/households/join` (rate limit, expiry, 409 already member) | Implemented + verified; concurrent double join → **500** | `races.py` (F-10) |
| `GET /invite-code`, `POST /invite-code/rotate` (admin) | Implemented + verified (`test_member_lifecycle.py`) | Code visible to all members = documented open product question (H-12) |
| `PATCH /api/households/{id}` rename (admin) | Implemented + verified | — |
| `POST /leave` (auto-promotion, delete household when last) | Implemented; **sequentially verified, not race-safe** | `races.py` (F-02, F-03) |
| `DELETE /members/{uid}` (admin, not admins, rotates code, socket eviction) | Implemented + verified (tests + `races.py` remove‖leave consistent) | — |
| `GET /finance-summary` | Implemented + verified (other area) | shows ex-member as `paid_by_user_id` (F-14) |
| `verify_household_access` / `verify_household_admin` on all household routes | **Verified**: 139 `{household_id}` routes, 8 admin + 131 member, 0 without membership dependency | `route_audit.py` |
| Tag scan `/api/tags/resolve|execute/{token}` membership check | Implemented + verified by reading `tags.py:236-259` and `test_tags.py` | — |
| Socket.IO connect JWT, `exp` timer, `reauth`, personal room, `join_household` membership check, eviction on leave/remove, `disconnect_user` on logout/reuse | Implemented + verified by unit tests (`test_socket_session.py`, `test_member_lifecycle.py::test_emit_with_eviction_…`); in-process only (1 worker, documented) | Narrow race join‖evict (F-13, reasoned) |
| Widget token (`/widget-token` GET/POST/DELETE, `/api/widget/summary`) | Implemented + verified (`test_widget.py`, `lifecycle.py`) | Token not deleted on leave, **comes back to life on rejoin** (F-09) |
| Push subscriptions (`/api/push/*`), recipient selection by current membership | Implemented + verified (`lifecycle.py`: ex-member excluded) | Device keeps pushes after silent session end at startup (F-12, reasoned) |
| Frontend `stores/auth.ts` (single-flight refresh/logout, cross-tab marker, `_handleRemoval`, `leaveHousehold`, `fetchMe` after other member left = L-08 fix) | Implemented + verified by `auth.test.ts` | — |
| Frontend `App.vue` household switch: leave/join room, `resetHouseholdScopedStores()`, rebind listeners, `refreshAllStores()` | Implemented; **partial**: no stale-response guard in most stores (F-04), no reset when switching via "no household" (F-05) | `staleSwitch.test.ts`; code reading |
| `useSocket.ts` (reauth, recover, refreshBlocked after logout/revoked) | Implemented + verified by `useSocket` tests | Socket `error` event ("Not a member") has no client handler (F-06) |
| `api/client.ts` 401 → refresh + one retry; 403 passed through | Implemented + verified | 403 `NOT_HOUSEHOLD_MEMBER` never triggers `/me` reload (F-06) |
| Router guard (authReady, `/no-household` when `/me` loaded and 0 households) | Implemented + verified (by reading; existing tests) | — |
| `HouseholdView.vue`, `NoHouseholdView.vue` (create/join → `fetchMe` → `switchHousehold`) | Implemented, not behaviourally verified | F-05 applies after leaving the last household |
| `WidgetSettingsCard.vue` | Implemented, not behaviourally verified | no household guard after `await` (F-15) |

---

## 2. Invariants

| Invariant | Where enforced (file:line) | Operations that can violate it | Status | Existing tests | Missing tests |
|---|---|---|---|---|---|
| I-1 Every household with ≥1 member has ≥1 admin | `households.py:197-208` (promotion in `/leave`, read-then-write, no lock) | concurrent `/leave` of admin + the member to be promoted; admin `/leave` ‖ admin removes that member | **Violated** on PG (6–8 of 15 runs end with 1 member / 0 admins) | `test_leave_admin_auto_promote` (sequential, SQLite) | PG race test |
| I-2 A household has ≥1 member or does not exist | `households.py:176-195` (count → delete household) | concurrent `/leave` of the last two members | **Violated** on PG (5–8 of 15 runs: household exists, 0 members) | `test_leave_last_member_deletes_household` (sequential) | PG race test |
| I-3 A successful join (200) leaves the user as a member | `households.py:482-550` | `/join` ‖ last member `/leave` | **Violated** on PG (13 of 15: join 200, membership cascaded away with the household) | — | PG race test |
| I-4 Only a removed/left user loses access; removal takes effect immediately on REST | `deps.py:32-46` on all 139 household routes | — | **Verified** (`route_audit.py`, `lifecycle.py` §2: stale JWT → 403 on todos/expenses/members/invite-code/widget-token/dashboard/finance-summary, POST todo 403) | `test_removed_member_loses_access` | — |
| I-5 Removed member gets no further realtime events | `socket_manager.py:269-284` eviction; `join_household` membership check `:186-242` | race between the membership check (threadpool) and `enter_room`; `reauth` does not re-check membership | Partially verified (unit test of eviction); race **unverified (reasoned)** | `test_emit_with_eviction_notifies_then_removes_all_sids_of_user` | socket integration test with a real server |
| I-6 Removed member cannot rejoin with the known code | `households.py:263-266` rotation on remove | voluntary `/leave` does not rotate (by design) | Verified | `test_removed_member_cannot_rejoin_with_old_code` | — |
| I-7 Widget key is valid only while the person is a member | `widget.py:184-207` (lazy check per call) | leave → rejoin before the next widget call revives the key | Verified for removal; **revival observed** (F-09) | `test_key_dies_when_user_leaves_household` | rejoin test |
| I-8 Push only goes to current members | `push_service.py:185-187, 224-226, 354-356` | — | **Verified** (`lifecycle.py`: reminder of ex-member's todo → only member A's device) | `test_push.py` | — |
| I-9 One refresh token → at most one successor; benign concurrent refresh never logs the user out | `auth.py:349-421` | two or three tabs refreshing within ms / within grace | **Violated**: 9/40 (0 ms) and 7/40 (≤20 ms) concurrent pairs triggered `REFRESH_TOKEN_REUSED` and revoked all tokens; 3rd use within grace → global logout; 7–26/40 forked into 2 active chains | `test_grace_window_allows_second_tab_refresh` (sequential) | PG concurrency test; 3-use grace test |
| I-10 Assignees/participants are household members | `shopping.py:551-628`, `recurring_bills.py:109-110,154`, `chores.py` (rotation), `expenses.py` | todos (`todos.py:200`, PATCH `:243-246`) and events (`events.py:170,251`) accept **any** user id | **Violated** (todo assigned to a user of another household → 201; random UUID → 500; event participant outsider → 201) | — | API validation tests |
| I-11 Frontend shows only data of `currentHouseholdId` | `householdScope.ts:22-61` reset; pets/plants `captureRequest` | delayed fetch for the old household after a switch; switch through `null` | **Violated** for todos and shopping (vitest), same pattern in 13 more stores (reading) | `householdScope.test.ts`, pets/plants race tests | per-store stale-response tests |
| I-12 Admin-only operations = rename, rotate code, remove member, tag CUD/token, AI opt-in | `route_audit.py` output | — | Verified; docs (PROJECT-STATUS §Rollen line 717) omit rotate and AI settings (listed elsewhere) | `test_admin_guard.py`, `test_tags.py`, `test_ai_assistant.py` | — |

---

## 3. Findings

### F-01 Concurrent refresh of the same token falsely triggers reuse detection → user logged out on all devices
- **Severity:** Medium · **Class:** A · **Modules:** `backend/app/routers/auth.py`, frontend multi-tab/PWA
- **Refs:** `auth.py:200-216` (`_create_token_pair` commits), `:407-413`, `:356-398`
- **Observed:** Two requests with the same refresh token at nearly the same time. Request 1 sets `revoked_at` and then commits inside `_create_token_pair` (`db.commit()` at `auth.py:215`) **before** `replaced_by_id` is set (`:412-413`). Request 2 sees a revoked token without a replacement, so `grace_ok` is False (`:363-367`). It then runs full reuse detection: it revokes every token of the user (`:389-393`) and disconnects all sockets (`:395`). The new token that request 1 just returned is revoked too.
  The grace path follows only one hop. A third use of the same token within 30 s finds `replacement.revoked_at` set, so it also falls through to reuse detection.
  Without a row lock, concurrent pairs also often create **two** active successor chains (a token fork).
- **Evidence:**
  ```
  refresh_race.py  N=40 jitter<=0ms:  9 reuse_detected_all_revoked active=0 ((200),(401 REFRESH_TOKEN_REUSED)); 26 ok active=2; 5 ok active=1
                   N=40 jitter<=20ms: 7 reuse_detected_all_revoked; 7 ok active=2; 26 ok active=1
  grace_three.py   refresh #1 200, #2 200 (grace), #3 401 REFRESH_TOKEN_REUSED; active refresh tokens: 0
  ```
- **Expected:** Benign duplicates do not cause logout. This is the documented promise in logic-review §11: „zwei Tabs refreshen gleichzeitig → beide bekommen gültige Tokens“.
- **Repro:** Open the app in 2–3 tabs (or PWA plus a tab), let the access token expire (sleep/wake), then trigger requests in all tabs. Each tab has its own single-flight; all of them send the same `casa_rt` cookie.
- **Root cause:** A commit in the middle of the rotation leaves a visible „revoked without replacement“ state. There is no `SELECT … FOR UPDATE` on the old token, and the grace logic handles only one hop.
- **Impact:** Sporadic forced logout on every device, socket disconnects, and a „Sitzung abgelaufen“ message. No data loss, but it damages trust and is hard to diagnose. Token forks also weaken reuse detection.
- **Fix:** Lock the old token (`with_for_update()`). Set `revoked_at` and `replaced_by_id` and insert the new token in **one** commit (flush the new token first). In the grace path, follow the `replaced_by_id` chain to the newest unrevoked token, or return a new pair derived from the chain head without revoking it.
- **Regression test:** A PG test with `H.parallel` and 2 and 3 concurrent refreshes asserts no `REFRESH_TOKEN_REUSED` and exactly 1 active token. A unit test checks 3 sequential uses within grace.
- **Confidence:** High

### F-02 Concurrent leave → household with members but **no admin**, permanently
- **Severity:** Medium · **Class:** A · **Modules:** `households.py` leave/remove
- **Refs:** `households.py:176-211`
- **Observed:** Admin A leaves while the most senior member B leaves too (C stays). A's transaction promotes B and deletes A; B's transaction deletes B. Result on PG: C stays as the only member with role `member`. Other runs produce a 500 (`StaleDataError` when A's UPDATE hits the deleted row of B), so A's leave fails.
  ```
  races.py == admin A + senior B leave concurrently (C remains)
    status codes: {(204, 204): 9, (500, 204): 6}
    outcomes: {'members=1 admins=0': 6, 'members=1 admins=1': 3, 'members=2 admins=1': 6}
  ```
  (first run: 8/15 with admins=0)
- **Expected:** PROJECT-STATUS §Haushalt verlassen: „Einziger Admin verlässt → dienstältestes verbleibendes Mitglied wird automatisch Admin“.
- **Impact:** Nobody can rename the household, rotate the invite code, remove members, manage tags or switch the AI. There is **no recovery path**: there is no promote endpoint, and promotion only happens when an admin leaves. Only a DB fix helps. The same class applies to admin `/leave` ‖ admin `DELETE /members/{B}`, by reading.
- **Root cause:** Read-modify-write on the member list without a lock. The promotion target is chosen from a snapshot.
- **Fix:** Serialise membership changes per household, e.g. `SELECT … FROM households WHERE id=… FOR UPDATE` at the start of leave/remove/join. Then re-read members, and after the delete, ensure „≥1 admin if ≥1 member“ before commit. Map `StaleDataError` to 409. Alternatively, add an admin-repair rule: if no admin is present on any member request, promote the senior member.
- **Regression test:** PG race test asserting `admins ≥ 1 or members == 0`.
- **Confidence:** High

### F-03 Last-member races: orphan household with 0 members (data and files kept, joinable by code holders); successful join silently undone
- **Severity:** Medium · **Class:** A · **Modules:** `households.py` leave/join, storage
- **Refs:** `households.py:176-195, 482-537`
- **Observed:**
  1. When the last two members leave at the same time, both see 2 members and only delete themselves.
     ```
     races.py == last two members leave concurrently
       outcomes: {'exists=True members=0 admins=0': 5, 'exists=True members=1 admins=1': 6, 'exists=False ...': 4}  (first run 8/15 orphans)
     ```
     `orphan_join.py`: an orphan was produced on attempt 2. Anyone with the still-valid code (7 days) can join it **and sees all old data**:
     `outsider sees old data: 200 ['geheime Notiz von A']`, and the joiner is a plain `member` (rename/rotate → 403). Files on disk stay until someone joins and leaves again.
  2. `/join` ‖ last member `/leave`: `{'household_exists=False joiner_memberships=0': 13}`, while all 15 joins returned **200**. The join committed, then the leave (which had counted 1 member) deleted the household by CASCADE, including the new membership.
- **Expected:** The last leaver deletes the household and its files (documented rule). A 200 join means membership exists.
- **Impact:** Orphaned personal and financial data with no owner, and storage that is never freed. Former members or code holders can reattach to it. A newly joined user gets a success toast and then lands in a household that does not exist.
- **Root cause:** Same as F-02: the member count comes from an unlocked snapshot.
- **Fix:** The same per-household row lock in leave/join/remove. After deleting a membership, re-count inside the lock and delete the household when 0 members remain. As a safety net, a periodic job deletes households with 0 members together with their storage.
- **Regression test:** PG race tests for leave‖leave and leave‖join.
- **Confidence:** High

### F-04 Frontend: a delayed response for the previous household overwrites the new household's store
- **Severity:** Medium · **Class:** A · **Modules:** `frontend/src/stores/*`
- **Refs:** `todos.ts:23-33` (`items.value = await repo.fetchAll(householdId)`); the same unguarded `x.value = await …` in `shopping.ts:61,128,140`, `expenses.ts:50,65,81`, `settlements.ts:38`, `chores.ts:41,54,65`, `finance.ts:27,43,72`, `dashboard.ts:27`, `polls.ts:36`, `calendar.ts:72,185,196`, `notes.ts:42,53`, `food.ts:44` (recipes; week plan is guarded by `weekRequestId`), `tasks.ts:23,33`, `documents.ts:50,71,90` (store resets itself by watch, but the response after the await is unguarded), `tags.ts:42,51`, `ai.ts:86`. Guarded: `pets.ts:51-60` and `plants.ts:63-72` (`captureRequest`), `food.ts:125`, and tag socket handlers `tags.ts:123,128`.
- **Observed (vitest, `staleSwitch.test.ts`):** A fetch for hh-A is started, then the user switches to hh-B (`resetHouseholdScopedStores()`) and B's fetch resolves first. A's response then arrives:
  ```
  TODOS after switch: ["hh-A:A-Todo"]
  SHOPPING after switch: ["hh-A:Brot-A"]
  PETS after switch: ["hh-B:B-Katze"]      (guarded store is correct)
  ```
- **Expected:** After a switch only B's data is shown (L-07 intent; logic-review §7).
- **Repro:** Use two households on a slow connection. Switch right after start or after a reconnect, when `refreshAllStores()` for A is still in flight.
- **Impact:** The list under household B shows A's todos, shopping items, expenses and balances. Actions on them hit `/households/B/...` with A's ids and get 404/422. The data stays wrong until the next fetch or a reload. This is a confusing state with a wrong-person/wrong-household feel. It is not a security leak, because the user belongs to both households.
- **Root cause:** No household/generation check after `await` in most stores. The L-07 fix only clears the stores.
- **Fix:** Generalise the pets/plants `captureRequest(householdId, key)` helper (or a shared `householdGeneration` counter bumped by `resetHouseholdScopedStores`) and apply it in every fetch and mutation response.
- **Regression test:** Per store, a vitest „A responds after B“ test like `staleSwitch.test.ts`.
- **Confidence:** High (todos/shopping executed); High by code pattern for the others.

### F-05 Switching via „no household“ (leave the last one, then create or join a new one) does not reset the stores
- **Severity:** Low · **Class:** A · **Refs:** `App.vue:173-182`
- **Observed (reasoned):** `resetHouseholdScopedStores()` runs only when `oldHouseholdId && oldHouseholdId !== householdId`. Leaving the last household gives A → `null`: the `if (householdId)` block is skipped and nothing is reset. Creating or joining a new household then gives `null` → C: `oldHouseholdId` is falsy and again nothing is reset. `refreshAllStores()` overwrites the core stores. Pets, plants, notes, food, calendar and tasks keep A's data, including `members`, until their view fetches. Documents, AI and tags reset through their own watch.
- **Impact:** A brief or persistent display of the old household's pets, plants and notes in the new household. Actions on them return 404.
- **Fix:** Reset whenever `householdId !== oldHouseholdId`, including transitions to and from `null`.
- **Test:** An App-level or watch-level vitest for the A → null → C sequence.
- **Confidence:** Medium (code reading; not executed)

### F-06 Removal or leave missed while the socket was disconnected → app stays in a dead household (all 403) until reload
- **Severity:** Low · **Class:** A/F · **Refs:** `App.vue:290-297` (`handleReconnect` joins and refetches but never calls `fetchMe`); `api/client.ts:75` (403 passed through); `socket_manager.py:231-237` emits `error` „Not a member“, and the frontend has no `error` handler (`grep "on('error'"` → none)
- **Observed (reasoned):** The removal event is delivered only to connected sockets (`emit_to_household`). Typical case: an iOS PWA in the background with a dropped socket. On resume the reconnect rejoins the room (server refuses), and every store fetch gets 403 `NOT_HOUSEHOLD_MEMBER`, which is swallowed (`refreshAllStores` uses `quiet`). The household stays selected; the router guard only reacts to `/me`.
- **Expected:** Same UX as the live case (`_handleRemoval`): toast plus a switch or `/no-household`.
- **Fix:** On reconnect, and on any 403 with `NOT_HOUSEHOLD_MEMBER` for `currentHouseholdId`, call `fetchMe()` and handle the removal.
- **Confidence:** Medium

### F-07 Todo assignee and event participants are not validated against membership
- **Severity:** Low–Medium · **Class:** B · **Refs:** `todos.py:195-203` (create), `:243-246` (PATCH `setattr` of any field); `events.py:170, 250-252`
- **Observed (`lifecycle.py` §4):** A todo assigned to a user of **another household** → 201. A random UUID → **500** (FK violation not mapped). An event with an outsider in `participant_ids` → 201. Shopping, chores, expenses and recurring bills do validate (`shopping.py:551-628`, `household_checks.py`).
- **Impact:** Inconsistent rules and a 500 on bad input. Such todos are counted for nobody (see F-08). Foreign user ids are stored in a household's data. There is no name leak: responses carry ids only.
- **Fix:** `assert_users_allowed(db, household_id, [assignee], already_on_record={current})` for todos, and validation of `participant_ids` in events (allow already-recorded ex-members). This overlaps with the todos and calendar areas.
- **Confidence:** High

### F-08 Items assigned to an ex-member disappear from everyone's badge, widget and dashboard „due“ list, while push still goes to everyone
- **Severity:** Low · **Class:** C (extends L-15 / E-6) · **Refs:** `attention.py:79,98-99` („mine or unassigned“); `push_service.py:226,355-357` („assignee if member, else all members“); `chore_scheduler.py:161` (assignments are materialized 7 days ahead, so up to a week of the ex-member's turns stays assigned)
- **Observed (`lifecycle.py`):** The todo „Dora-Todo“ is due today and assigned to ex-member D. `badge for A: {"count":0}`, `badge for C: {"count":0}`. The reminder push goes to A (`push recipients …: ['A']`). D is correctly excluded.
- **Impact:** The ex-member's due chores and todos stay „nobody's“ in the UI counters, but a push says „Ämtli heute fällig“ to all. They are easily forgotten.
- **Recommendation:** Treat an ex-member assignee like „unassigned“ in `attention.py`, which matches push. Or decide E-6 b) and clear the assignee on leave.
- **Confidence:** High

### F-09 Widget key survives leaving and becomes valid again after rejoin
- **Severity:** Low · **Class:** C/D (docs partly inconsistent) · **Refs:** `widget.py:184-207`; `docs/widget.md:35` („Schlüssel wird beim nächsten Abruf ungültig und gelöscht“)
- **Observed (`lifecycle.py` §1):** B leaves: `widget_tokens rows for B after leave: 1`. B rejoins (voluntary leave does not rotate the code), and the old key returns **200** again. After an admin removal the key is rejected (401) and deleted.
- **Impact:** Someone who believed leaving revoked their (iCloud-synced) widget key finds it working again after rejoining. The data exposure is only to the same person.
- **Fix:** Delete `WidgetToken` rows for (user, household) in `/leave` and `remove_member`. Keep the lazy check as a safety net.
- **Confidence:** High

### F-10 Double-tap join / concurrent registration with the same e-mail → HTTP 500
- **Severity:** Low · **Class:** A · **Refs:** `households.py:512-537`, `auth.py:258-304`
- **Evidence (`races.py`):** double join `{(200, 500): 7, (500, 200): 4, (409, 200): 2, …}`, memberships=1. Double register `{(200, 500): 10, (500, 200): 5}`, users=1.
- **Impact:** The data stays consistent thanks to the unique constraints, but the user sees a generic error instead of 409/400.
- **Fix:** Catch `IntegrityError` and map it to `ALREADY_MEMBER` (409) or `EMAIL_ALREADY_REGISTERED` (400).
- **Confidence:** High

### F-11 Joining through registration emits no `household_member_joined`
- **Severity:** Low · **Class:** A/F · **Refs:** `auth.py:270-305` (no emit) vs. `households.py:539-548`
- **Impact:** Other members' open member lists, assignee pickers and payer pickers do not show the newcomer until they refetch.
- **Confidence:** High (reading)

### F-12 A device whose session silently expired keeps receiving that user's pushes
- **Severity:** Low · **Class:** A (privacy) · **Refs:** `stores/auth.ts:83-87` (`initialize`: 401 → `_clearState()` only) vs. `_doLogout` `:250-258` (`disablePush`)
- **Observed (reasoned):** If the refresh cookie is dead at app start (expired after 30 days, or revoked by reuse detection), the store clears its state without unsubscribing push. The backend `PushSubscription` stays mapped to the old user, so reminders with todo, chore and document titles keep arriving on the lock screen of a logged-out device. This continues until someone else logs in on it (`syncPushSubscription` reassigns) or the user disables push.
- **Fix:** Call `disablePush({notifyBackend:false})` in the 401 branch of `initialize()`, and in the cross-tab logout listener. Optionally revoke push subscriptions server-side in reuse detection.
- **Confidence:** Medium

### F-13 Socket room join can race with eviction; `reauth` never re-checks membership
- **Severity:** Low · **Class:** E · **Refs:** `socket_manager.py:217-239` (check in threadpool, then `enter_room`), `:159-183` (`reauth`)
- **Reasoned:** If removal and eviction run between `_is_household_member` and `enter_room`, the socket enters the room after eviction. Because `reauth` only extends `exp`, that connection keeps receiving the household's events for as long as the client keeps refreshing. Removal does not revoke refresh tokens. The window is milliseconds and requires a reconnect at the moment of removal.
- **Fix:** Re-check membership in `reauth` (drop rooms that are no longer allowed), or re-check after `enter_room`.
- **Confidence:** Low–Medium (not reproduced; requires a real Socket.IO server)

### F-14 Recurring bill keeps an ex-member as default payer
- **Severity:** Low · **Class:** C/F · **Refs:** `recurring_bills.py:225-231`, `households.py:417`
- **Observed (`lifecycle.py`):** After D leaves, the bill list and finance summary still show `paid_by_user_id = D`. `POST /book` without a body → **422 USERS_NOT_IN_HOUSEHOLD**. Renaming the bill works. Bills are **not** booked to the ex-member. The UI suggests a current member instead (`ExpensesView.vue:161-162`).
- **Recommendation:** Clear `paid_by_user_id` on leave/remove (and show „Zahler wählen“), or show a hint. Booking to an ex-member is correctly prevented.
- **Confidence:** High

### F-15 WidgetSettingsCard has no household guard after `await`
- **Severity:** Low · **Class:** F · **Refs:** `WidgetSettingsCard.vue:33-41, 48-61`
- **Reasoned:** `create()` for household A finishes after a switch to B. The watch already cleared `script`, but `script.value` is then set to A's key and shown under B. `load()` can show A's status. The generated script shows the household name, so this is unlikely to go unnoticed.
- **Fix:** Capture `householdId` before the await and drop the result if it changed.
- **Confidence:** Medium

### Verified correct (no finding)
- All 139 household-scoped routes check membership on every request, so a stale access JWT of a removed member gets 403 (`route_audit.py`, `lifecycle.py` §2). File downloads (`files.py:410-414`) and tag scans (`tags.py:243-252`) included.
- Push recipients are always filtered by current membership (`lifecycle.py`: ex-member excluded).
- Remove ‖ leave of the same member: consistent outcome on PG (`{(204, 204): 14, (404, 204): 1}`, members=2, admins=1).
- An admin removal rotates the code; a removed member cannot rejoin with the old code (existing test).
- Booking a recurring bill never books to an ex-member (422).
- The frontend refreshes `/me` when another member leaves or is removed (L-08 fix still present, `auth.ts:394-400`).
- Logout semantics (all sockets of the user disconnected, other devices reconnect without refresh) match PROJECT-STATUS §5 and §8.

---

## 4. Prior review status

| Item | Status now | Evidence |
|---|---|---|
| L-05 (chore with ex-member in rotation not editable) | Fixed (chores area; not re-tested here) | — |
| L-07 (household switch did not reset stores) | **Fixed but incomplete**: the reset exists (`householdScope.ts`), but delayed responses re-fill stores with old data (F-04), and there is no reset across `null` (F-05) | `staleSwitch.test.ts` |
| L-08 (promoted member sees role only after reload) | Fixed, still present | `auth.ts:394-400`; `auth.test.ts` |
| L-14 (reconnect reloads only core stores) | Open as documented; additionally reconnect does not reload `/me` (F-06) | reading |
| L-15 / E-6 (assignments of ex-member stay) | Open as documented; new consequence: they vanish from badge/widget for everyone (F-08) | `lifecycle.py` |
| E-7 (rotation cleanup on leave) | Open as documented (scheduler skips) | `chore_scheduler.py:117-138` |
| Logic-review §7 „Letzter Admin verlässt → ok“, „Einziges Mitglied verlässt → ok“ | **True only sequentially**; violated under concurrency on PG (F-02, F-03) | `races.py` |
| Logic-review §11 „Refresh-Rotation mit Grace-Window: zwei Tabs gleichzeitig → beide gültig“ | **Not reliably true**: about 20% of truly concurrent pairs, and every third use, cause a global logout (F-01) | `refresh_race.py`, `grace_three.py` |
| H-12 (invite code expiry/rotation) | Fixed; visibility for all members still an open product question (documented) | — |
| H-13 (rate limit per IP, in-memory) | Accepted (documented) | — |
| H-15 (sockets after logout/expiry) | Fixed (timer + reauth + disconnect); residual F-13 | — |
| PROJECT-STATUS §8 „Logout trennt Sockets aller Geräte“, „Access-Token bis 15 Min gültig“ | D, accepted limitations; not re-reported | — |
| „Überall abmelden“ / password change | G (planned) | PROJECT-STATUS §7 |

---

## 5. Cross-module effects

| Source operation | Dependent entities | What can go inconsistent |
|---|---|---|
| `/leave`, `DELETE /members` | todos (`assigned_to_user_id`), shopping items, chore assignments (up to 7 days materialized), events `participant_ids`, poll votes, recurring bill `paid_by_user_id`, widget token, push subscriptions | Assignees keep pointing to the ex-member (L-15). Badge, widget and dashboard ignore those items while push goes to all (F-08). The bill default payer is stale and default booking returns 422 (F-14). The widget key is not deleted and revives on rejoin (F-09). Poll votes of ex-members keep counting (no cleanup; product decision). Push is correctly filtered. Expenses and settlements follow the documented ex-member pattern. |
| Concurrent `/leave` (+`/join`) | Household, all CASCADE children, storage directory | Household with no admin (F-02). Orphan household with all data and files, joinable by code (F-03). A joiner's membership is deleted by CASCADE after a 200 (F-03). |
| `/refresh` reuse detection (incl. false positives) | all refresh tokens of the user, all sockets | Global logout on every device (F-01). Push subscriptions stay registered (F-12 variant). |
| Household switch in the frontend | 17 stores, socket rooms, WidgetSettingsCard | Old-household data re-inserted by late responses (F-04). No reset across `null` (F-05). Widget script shown under the wrong household (F-15). |
| Removal while offline | auth store, router, every store | The app stays in a household it no longer belongs to; every request returns 403 (F-06). |
| Todo / event create with a foreign user id | attention, push, UI name resolution | Item counted for nobody; unknown name in the UI; 500 for a nonexistent id (F-07). |

---

## 6. Test gaps

| Scenario | Recommended test type |
|---|---|
| Concurrent leave of admin + senior member; leave‖remove; „≥1 admin if ≥1 member“ | PG integration (race) |
| Last two members leave concurrently → household deleted with files | PG integration (race) |
| Join ‖ last-member leave | PG integration (race) |
| 2 and 3 concurrent `/refresh` with one token; 3 sequential uses within grace | PG integration + unit |
| Double join / double register returns 409/400, not 500 | PG integration |
| Widget key after leave + rejoin | API test (SQLite suffices) |
| Todo/event assignee validation (foreign user, random UUID) | API test |
| Attention/badge with an item assigned to an ex-member | unit/API |
| Every store ignores responses for a previous household | vitest per store (pattern `staleSwitch.test.ts`) |
| A → null → C household transition resets the stores | vitest (App watch extracted) or E2E |
| Reconnect / 403 `NOT_HOUSEHOLD_MEMBER` triggers `/me` reload | vitest + E2E |
| Socket join_household ‖ eviction; reauth after removal | integration with a real python-socketio server |
| Push unsubscribed when startup refresh returns 401 | vitest (auth store) |

---

## 7. Product decisions

1. **Permission matrix (C).** Admin is required only for: rename, rotate code, remove member, tag create/update/delete/token, and AI opt-in (`route_audit.py`). All 131 other household routes are open to any member, including deleting **other people's** expenses, settlements, documents with their files, pets, plants, events, polls, budgets and recurring bills. There are no ownership checks anywhere. This matches „Keine feingranularen Berechtigungen (bewusst)“ (PROJECT-STATUS §Rollen), so it is not a defect. Docs inconsistency: the admin list at PROJECT-STATUS l.717 omits invite-code rotate and AI settings, which are documented elsewhere.
   Options: a) keep as is. b) Creator-or-admin for destructive financial operations (delete or edit expense/settlement, delete recurring bill or document). c) Add an audit trail („gelöscht von …“).
   **Recommendation:** b) for money and documents. At minimum c), because deleting a settlement silently changes others' balances.
2. **Admin recovery.** There is no promote, demote or transfer endpoint, so a household that ends up without an admin (F-02) cannot recover. Options: a) a lock-only fix. b) Also auto-promote the senior member when no admin exists. c) A manual „zum Admin machen“ action for admins.
   **Recommendation:** a) + b).
3. **Ex-member assignments (E-6).** a) Keep (today). b) Clear them on leave/remove, including future chore assignments, open todos and shopping items, and the bill default payer. c) Keep them, but count them as „unassigned“ in attention and widget.
   **Recommendation:** c) now (small change, consistent with push); b) later.
4. **Widget key on leave.** a) Lazy (today; revives on rejoin). b) Delete on leave/remove.
   **Recommendation:** b).
5. **Invite code after voluntary leave.** Today it is not rotated, so the leaver can rejoin within 7 days. a) Keep. b) Rotate on every membership loss.
   **Recommendation:** a) is acceptable; document it.
6. **Poll votes of ex-members.** a) Keep counting (today). b) Exclude from open polls.
   **Recommendation:** b) for polls that are still open.

---

## 8. Unverified

- **Socket race F-13**, and eviction across multiple workers: needs a real Socket.IO server and clients. Only unit tests exist. A single worker is documented.
- **F-05, F-06, F-12, F-15** (frontend): established by code reading. They were not executed because a mounted `App.vue` test would need many mocks and new test files cannot go into the repo.
- **Real-world frequency of F-01** depends on browser timing (tabs waking together). The PG harness proves the window exists; how often production users hit it is unknown.
- **F-04 for the 13 stores other than todos and shopping**: the same pattern was found by reading; not executed one by one.
- **Push to a real device / iOS** behaviour after an unsubscribe: not tested (no VAPID keys, no device).
