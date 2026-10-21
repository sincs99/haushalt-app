# User Journey Audit

**Date:** 2026-10-10 · Companion to [FULL_LOGIC_AUDIT.md](FULL_LOGIC_AUDIT.md).

Journeys were executed end-to-end against the real API on PostgreSQL 16 (migrated with Alembic, one
session per request, socket emits recorded) unless marked *code reading* or *store test*. Scripts:
`audit-evidence/journeys/` and the module folders. No browser or physical device was used; UI statements
are derived from the components' code and from store-level tests.

Legend for "Verified outcome": ✅ as expected · ⚠️ confusing/inconsistent · ❌ broken.

---

## J1 — Three-person flat: shared bill, groceries, one member leaves, settle, rebook

| | |
|---|---|
| **Household** | Anna (admin), Ben, Carla. CHF, Europe/Zurich |
| **Script** | `journeys/j1_finance_leave.py` → `j1.out` |

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | Anna creates recurring bill "Miete" 3000.00, default payer Anna, books it | Even split over 3, Anna +2000 | ✅ Anna +2000.00, Ben −1000.00, Carla −1000.00 |
| 2 | Ben records "Migros" 100.00 even | Rounding exact | ✅ Carla −1033.34, Ben −933.33, Anna +1966.67 (sum 0; the extra Rappen goes deterministically by UUID order) |
| 3 | Carla leaves | Allowed with debt; debt stays visible | ✅ balances unchanged; Carla gets 403 everywhere |
| 4 | Anna records both suggested settlements (incl. Carla → Anna for the ex-member) | All balances 0 | ✅ all 0, no suggestions |
| 5 | Anna books the bill again in the same month | 409 | ✅ 409 `BILL_ALREADY_BOOKED` |
| 6 | Ben deletes Anna's settled rent expense | ? (no rule) | ⚠️ 204, no warning. Balances: **Carla +1000.00, Ben +1000.00, Anna −2000.00** — the ex-member becomes a creditor and cannot see it |
| 7 | Anna books the bill again | ? | ⚠️ 201, split over Anna/Ben only → Ben −500.00, Anna −500.00, **Carla +1000.00** |
| 8 | Dashboard / finance summary | Consistent with balances | ✅ dashboard saldo −500.00 for Anna = balances; summary total 3100.00, bill booked |
| 9 | Anna (bill's default payer) leaves; Ben books next month without choosing a payer | Clear prompt for a new payer | ⚠️ 422 `USERS_NOT_IN_HOUSEHOLD` with a raw UUID; bill list still shows Anna as payer (UI pre-selects the current user, so the UI path works) |

**Broken/confusing:** steps 6–7 (CASA-02). **Missing handling:** warning when changing settled history,
attribution of the deletion, visibility of ex-member claims, clearing the stale default payer (CASA-22).

## J2 — Couple editing the same expense from two phones

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | 4-member household, expense 10.00 even | Shares 2.50 × 4 | ✅ |
| 2 | Anna limits participants to Anna+Ben, Ben limits to Carla+Dora, at the same moment | One wins, the other gets a conflict | ❌ both 200; **4 shares of 5.00 on a 10.00 expense**; household balances sum to −90.00 after 10 rounds (`journeys/v2_shares.py`) |
| 3 | Same, one changes amount, the other participants | Conflict | ❌ 37/40 → HTTP 500 (`j3_expense_concurrent_patch.py`) |
| 4 | Ben corrects amount 100→250; Anna saves description from a dialog opened earlier | Amount stays 250 or conflict | ❌ amount silently 100.00 (`finance/pg_scenarios.py` scenario 5) |

**Findings:** CASA-01, CASA-09.

## J3 — "I paid you back" recorded by both

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | Ben owes Anna 25.00 | Suggestion Ben → Anna 25.00 | ✅ |
| 2 | Ben taps "Ausgleichen" on his phone, Anna taps it on hers | One settlement | ❌ two settlements; Anna now owes Ben 25.00 (15/15 parallel rounds) |
| 3 | Anna deletes one | Back to 0 | ✅ (but anyone could delete either, unattributed) |

**Findings:** CASA-08, CASA-02.

## J4 — Accidental delete and Undo in finances

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | Booked "Internet" expense deleted, Undo tapped | Original restored | ❌ re-created without bill link; card shows "zu buchen"; booking again → 2 Internet expenses in the month (`frontend_realtime_ux/pg_undo_bill.py`) |
| 2 | Expense paid by an ex-member deleted, Undo tapped | Restored | ❌ 422; ex-member's claim lost permanently |

**Finding:** CASA-03.

## J5 — Meal poll for Saturday, missing ingredients, recipe cleanup

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | Anna plans Pasta for Saturday | Entry | ✅ |
| 2 | Ben starts a meal poll for Saturday (Zopf vs Pizza), decides Zopf | Warn that Pasta is planned | ⚠️ Pasta silently replaced |
| 3 | Anna has the food view open | Shows Zopf | ❌ socket payload `{date}` only → day shows "Kein Essen geplant" until reload |
| 4 | Vote after decision | Rejected | ✅ 400 |
| 5 | "Fehlende Zutaten" (500 g Mehl, Eier, Butter, Butter) with "Mehl" open on list 2 and "Eier" on list 1 | Skip existing | ⚠️ "500 g Mehl" added (free-text quantity, other list not checked); "Eier" and duplicate "Butter" skipped ✅; repeating the import adds nothing ✅ |
| 6 | Recipe deleted | Plan remains meaningful | ⚠️ entry with neither recipe nor text; shown as "no meal"; add-missing 400 |

**Script:** `journeys/j4_meal_shopping.py`. **Findings:** CASA-19, CASA-52, CASA-53.

## J6 — Weekly Ämtli with schedule change, holiday pause, departure, NFC

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | "Bad putzen" weekly Monday, rotation Anna→Ben→Carla | Deterministic rotation | ✅ |
| 2 | On Saturday the weekday is changed to Wednesday | Next due is next Wednesday | ❌ an overdue assignment for last Wednesday appears for Carla; her real turn is consumed (CASA-16) |
| 3 | Other members have the chores view open | Old assignments disappear | ❌ old and new shown; ticking the old one → 404 (CASA-16) |
| 4 | Household pauses the chore for holidays | No notifications | ❌ "Du bist dran" still sent for the already-materialised assignment; badge counts it (CASA-17) |
| 5 | Reactivated 6 weeks later | Starts with the next date | ❌ two overdue duties for two people immediately (CASA-17) |
| 6 | Carla leaves while assigned for today | Someone is clearly responsible | ⚠️ push "Ämtli heute fällig" to everyone; everyone's badge 0; dashboard shows no name (CASA-22) |
| 7 | Anna scans the bathroom NFC tag twice (double read) | One completion | ❌ today's and last week's assignment completed, both "erledigt" (CASA-05) |
| 8 | Ben completes it in the app between Anna's scan and confirm | "Already done" | ❌ an older assignment is completed instead (CASA-18) |

**Scripts:** `chores_tasks_time/pg_schedule.py`, `tags_ai/pg_tags.py`, `frontend_realtime_ux/pg_realtime.py`.

## J7 — Todo with reminder, accidental tick, undo

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | "Steuererklärung abgeben" due Friday, reminder Thursday 18:00 | Reminder scheduled | ✅ |
| 2 | Accidentally ticked, then "Rückgängig" | Reminder still pending | ❌ reminder cancelled silently; bell with 18:00 still shown; no push at 18:00 (CASA-06) |
| 3 | Todo assigned via API to a user of another household | 422 | ❌ 201; invisible in everyone's "Meine" and badge (CASA-21) |
| 4 | Two people claim the same todo | One wins | ✅ 1×200, 7×409 |

## J8 — Breakfast with two cats and a medication

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | Ben feeds Mia via the bowl NFC tag; Anna taps "Alle gefüttert" at the same time | All cats fed | ❌ in 12/30 trials only Mia fed; Anna sees "Alle sind schon gefüttert" (CASA-13) |
| 2 | Both feed Mia individually at the same time | One record | ✅ 201 + 409 |
| 3 | Antibiotic "2x täglich": morning dose logged | — | ✅ |
| 4 | Evening dose | Can be logged, with "last given 07:12 by Ben" | ❌ button hidden after the first dose of the day (CASA-14) |
| 5 | Anna and Ben both give the morning pill (two phones) | Second person warned before giving | ❌ both logged, warning only after the socket update (CASA-14) |
| 6 | Medication deleted by mistake | History kept or warned | ❌ all 5 logs gone; dialog says only "Medikament wirklich löschen?" (CASA-15) |
| 7 | Anna taps Ben's morning feeding by mistake | Confirmation | ⚠️ deleted with undo toast only (CASA-30) |

**Scripts:** `pets_plants_documents/s1_pets.py`, `tags_ai/pg_tags.py`.

## J9 — Plants: AI advice and watering

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | AI advice "water every 7 days" applied to a task due in 25 days | New rhythm effective | ⚠️ interval changed, due date stays in 25 days (E-2) |
| 2 | Labelled task "Winter" | Untouched | ✅ |
| 3 | Partial failure during apply, retry | No duplicates | ✅ re-reads tasks |
| 4 | Two people tap "Alle giessen" | One log per plant | ⚠️ 10 logs for 5 plants in 4/6 trials (CASA-29) |
| 5 | Single-plant water tag on a plant with a due and a non-due water task | Only the due one | ⚠️ both completed (+20 → +30 days) (CASA-29) |

## J10 — Documents: warranty with expiry, multi-page upload, storage

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | Upload 3-page warranty, page 2 invalid | Nothing saved | ✅ all-or-nothing |
| 2 | Expiry in 30 days | Pre-warning and day-of push once | ✅; re-armed only on date change ✅ |
| 3 | Removed member opens a saved download link | 403 | ✅ |
| 4 | 8 parallel uploads near the quota | Quota respected | ⚠️ exceeded (1.40 MB on 1 MB) (CASA-26) |
| 5 | Last member leaves | Files deleted | ✅ (sequential); orphan household possible under a race (CASA-10) |

## J11 — Family tablet, two users, two households

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | Parent in households "Familie" and "Ferienhaus" switches while the app is still loading | Only Ferienhaus data | ❌ Familie's shopping items and balances can appear under Ferienhaus (store test R1/R2) (CASA-12) |
| 2 | Parent logs out, teenager logs in on the same tablet | Empty until own data loads | ❌ parent's dashboard saldo, shopping list and notes visible until the teenager's requests return (store test R3) |
| 3 | Parent's session had silently expired at app start | No more parent notifications | ❌ push subscription stays with the parent → reminders on the tablet lock screen (CASA-47, code reading) |
| 4 | Push for Ferienhaus pet tapped while app shows Familie | Opens Ferienhaus pet | ❌ "not found" in Familie (CASA-40, code reading) |
| 5 | Two tabs wake after sleep and refresh at once | Stay logged in | ⚠️ ~20 % logged out on all devices (CASA-11) |

## J12 — Household lifecycle with changing members

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | Admin leaves; senior member promoted | Promoted member sees admin functions without reload | ✅ (L-08 fixed) |
| 2 | Admin and senior member leave at the same moment | Remaining member becomes admin | ❌ 6–8/15 no admin, permanently (CASA-10) |
| 3 | Last two members leave at once | Household deleted | ❌ 5–11 of 15–40 orphaned with all data |
| 4 | Somebody joins the orphan with the old code | Code invalid | ❌ 200, sees "geheime Notiz von A" |
| 5 | Removed member tries the old code | 404 | ✅ code rotated on removal |
| 6 | Leaver rejoins with code within 7 days | (allowed) | ✅ allowed (voluntary leave does not rotate); old widget key works again ⚠️ (CASA-22) |

## J13 — Single-user household

| Step | Action | Expected | Verified outcome |
|---|---|---|---|
| 1 | Register with household name; create expense paid by self | Saldo 0 | ✅ |
| 2 | Recurring bill, chores, todos, plants | Work without other members | ✅ rotation of one; pushes to self |
| 3 | Leave | Household and files deleted | ✅ |

No defects specific to single-user households were found; the concurrency findings do not apply except for
multi-device use by the same person (J2 step 2 and CASA-11 are reachable by one person with two devices).

---

## Summary of user-facing problems by type

| Type | Journeys | IDs |
|---|---|---|
| Wrong success/"nothing to do" feedback | J6, J8 | CASA-05, CASA-13, CASA-29 |
| Recovery action makes it worse | J4, J7 | CASA-03, CASA-06 |
| Silent overwrite / silent loss | J1, J2, J5, J8 | CASA-01, CASA-02, CASA-09, CASA-15, CASA-19 |
| Responsibility unclear after change | J1, J6 | CASA-16, CASA-17, CASA-22 |
| Wrong household/user context | J11 | CASA-12, CASA-40, CASA-47 |
| Unrecoverable household state | J12 | CASA-10 |
