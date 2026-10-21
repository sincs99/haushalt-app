# Product Decisions

**Date:** 2026-10-10 · Companion to [FULL_LOGIC_AUDIT.md](FULL_LOGIC_AUDIT.md).

This document lists behaviours where the code does something defensible but **no business rule has been
decided**, or where two reasonable rules conflict. They are deliberately kept apart from confirmed defects.
Nothing here has been implemented. Open decisions from `docs/qa/logic-review.md` (E-1…E-10) are referenced
and, where this audit adds evidence, extended.

Each entry: current behaviour · why it matters · options with trade-offs · recommendation · affected modules.

---

## Finance

### PD-F1 · Who may edit or delete financial records, and is there a history?
- **Current:** any member may edit/delete any expense or settlement; hard delete; expenses have no creator/editor (settlements have `created_by_user_id`, not shown). Evidence: CASA-02, finance scenario 1 (debtor deletes creditor's expense → both 0), scenario 14 (third party deletes a settlement).
- **Why it matters:** the ledger is the household's shared truth; untraceable changes cause disputes and allow erasing one's own debt.
- **Options:** (a) keep as is · (b) only creator, payer or admin may edit/delete · (c) everyone may, but soft delete + visible history ("gelöscht von Ben am …") + notification to the payer.
- **Trade-offs:** (b) adds a permission model the app deliberately avoids ("keine feingranularen Berechtigungen"); (c) keeps the flat model and makes changes visible at modest cost (columns + list filter).
- **Recommendation:** **(c)**, plus `created_by`/`updated_by` on expenses. Required anyway for the Undo fix (CASA-03).
- **Affected:** expenses, settlements, ExpensesView, balances, socket events, migrations.

### PD-F2 · Changing history before the last settlement
- **Current:** edit/delete of an expense dated before a settlement silently reopens/reverses debts (finance F-17; journey J1 steps 6–7), including toward ex-members who cannot see it.
- **Options:** (a) allow silently · (b) allow with a warning "Salden ändern sich nachträglich" and show the effect · (c) lock expenses older than the last settlement between the involved people.
- **Trade-offs:** (c) is strict and makes honest corrections hard; (b) preserves flexibility and informs.
- **Recommendation:** **(b)**; additionally show ex-member balances prominently to remaining members.
- **Affected:** expenses, BalanceSummary, ExpenseFormDialog.

### PD-F3 · Settlement idempotency and plausibility
- **Current:** every POST creates a settlement; duplicates, overpayment and payments against the debt direction are accepted (CASA-08).
- **Options:** (a) as is · (b) client idempotency key + warning when amount > current debt between the two or an identical settlement exists within N minutes · (c) hard reject implausible settlements.
- **Recommendation:** **(b)**. (c) would block legitimate advance payments.
- **Affected:** settlements API, BalanceSummary.

### PD-F4 · Booking a missed recurring-bill month
- **Current:** only the current household month can be booked; a forgotten month can only be entered as an unlinked manual expense.
- **Options:** (a) current month only · (b) allow `month` (past months, not future) with the same uniqueness.
- **Recommendation:** **(b)**, limited to the past 12 months.
- **Affected:** recurring bills, finance summary.

### PD-F5 · `RecurringBill.split_type` (existing E-5)
- **Current:** `custom` is accepted and stored, but every booking is even over current members.
- **Options:** (a) remove the field · (b) model shares per bill · (c) reject `custom`.
- **Recommendation:** **(c)** now, **(a)** together with the bill management UI (which does not exist yet — CASA-58).

### PD-F6 · Refunds and credits
- **Current:** amounts must be > 0; a refund must be modelled as a settlement or a custom expense paid by the refunding person.
- **Options:** (a) document the workaround in the UI · (b) `kind = refund` expenses with negative effect.
- **Recommendation:** **(a)** unless users ask for it.

### PD-F7 · Concurrent edit strategy for financial records
- **Current:** last writer wins with full payloads (CASA-09); no version on expenses.
- **Options:** (a) send only changed fields · (b) `version` + `If-Match` → 409 "inzwischen von X geändert" · (c) both.
- **Recommendation:** **(c)** for expenses; (a) for notes, shopping sheet, todos. (Note: locking against CASA-01 is a defect fix, not a decision.)

## Households and membership

### PD-H1 · What happens to a departing member's open responsibilities? (existing E-6, E-7; extended)
- **Current:** todos, shopping items, materialised chore assignments (up to 7 days ahead + overdue), recurring-bill default payer, event participants and open-poll votes keep pointing to the ex-member. Push falls back to all members, badge/widget count nobody, dashboard shows no name (CASA-22).
- **Options:** (a) keep (today) · (b) on leave/remove: clear assignees (→ "open for all"), remove from `rotation_order`, clear default payer, remove votes from **open** polls, delete widget token · (c) keep the data but treat ex-member assignees as unassigned in attention/widget/dashboard.
- **Trade-offs:** (b) changes stored data (history of "who was assigned" is lost for open items only); (c) is cheap and consistent with push but leaves stale ids.
- **Recommendation:** **(c) immediately**, **(b)** in the same transaction as the membership lock (CASA-10). Decided polls and completed items keep the ex-member for history.
- **Affected:** households, todos, shopping, chores, recurring bills, polls, events, attention, widget, push.

### PD-H2 · Permission model for destructive actions
- **Current:** admin only for rename, invite code rotation, member removal, tags, AI opt-in; any member may delete anything else (documented "keine feingranularen Berechtigungen").
- **Options:** (a) keep · (b) creator-or-admin for destructive actions on money, documents and care history · (c) keep permissions flat but add audit trail and soft delete (see PD-F1, PD-P2).
- **Recommendation:** **(c)**; revisit (b) only for money if households report abuse.

### PD-H3 · Admin recovery
- **Current:** no promote/demote/transfer endpoint; a household that loses its admin (CASA-10) cannot recover.
- **Options:** (a) lock-only fix · (b) also auto-promote the senior member whenever no admin exists · (c) manual "zum Admin machen" for admins.
- **Recommendation:** **(a) + (b)**; (c) optional.

### PD-H4 · Invite code after voluntary leave / visibility (existing H-12 question)
- **Current:** code not rotated on voluntary leave (leaver can rejoin within 7 days); visible to all members.
- **Recommendation:** keep; document. Rotate on removal (already done).

## Chores

### PD-C1 · Pausing and reactivating a chore (existing E-3, extended)
- **Current:** paused chores keep materialised open assignments, which still push and count (CASA-17); reactivation backfills 14 days.
- **Options:** (a) keep visible · (b) hide while paused · (c) delete open assignments with `due_date ≥ today` on pause (give back rotation index), and re-anchor to the next date ≥ today on reactivation.
- **Recommendation:** **(c)**.
- **Affected:** chores API, scheduler, push, attention, dashboard, tags (`CHORE_INACTIVE`).

### PD-C2 · Dashboard chores section and `/tasks`
- **Current:** dashboard shows today's chores only; badge counts overdue ones; `/tasks` is unused and classifies differently (CASA-43).
- **Options:** dashboard (a) today only · (b) today + overdue; `/tasks` (a) keep · (b) remove · (c) use it with the attention rules.
- **Recommendation:** dashboard **(b)**; `/tasks` **(b)** unless a combined list view is planned.

### PD-C3 · Rotation editing in the UI (existing L-16)
- **Current:** members can only be reordered; new members never join existing rotations through the UI.
- **Recommendation:** allow add/remove in the edit dialog (UX branch).

## Tags

### PD-T1 · Idempotency window for repeated scans (existing E-4, extended)
- **Current:** chore tag completes backlog (defect CASA-05, not a decision); care/water tags log every scan and report `changed:true`; single-plant water completes all water tasks of the plant (CASA-29).
- **Options:** (a) idempotent per household day (`last_done_at == today` → `changed=false`) · (b) short time window (e.g. 10 min) to absorb double reads only · (c) log every scan.
- **Recommendation:** **(a)**; for `plant.water` with target: complete only due/overdue water tasks, fall back to the earliest if none is due.

### PD-T2 · Feed tag slot selection
- **Current:** blocked when the default slot is fed (CASA-31). **Recommendation:** allow any unfed slot, preselect it.

## Pets and plants

### PD-P1 · Multiple doses per day and duplicate warnings
- **Current:** UI allows one dose per day; API accepts any; no duplicate detection across devices (CASA-14).
- **Options:** (a) keep · (b) always allow, show "zuletzt gegeben um HH:MM von X", confirm within N hours · (c) model `doses_per_day`/`min_interval_hours` with server-side warning (never silent rejection or merge).
- **Recommendation:** **(b) now, (c) later**. Never silently merge or discard administration records.

### PD-P2 · Deleting medication / pet history
- **Current:** hard delete cascades all logs (CASA-15).
- **Options:** (a) keep · (b) soft delete / archive (pet status "verstorben/abgegeben") · (c) block deletion when logs exist and offer "deactivate".
- **Recommendation:** **(c)** for medications, **(b)** for pets; warn with counts in the dialog.

### PD-P3 · Feed-all scope
- **Current:** feeds every pet including fish/dogs; no archived state (PPD-11). **Recommendation:** per-pet opt-out + archived pets excluded.

### PD-P4 · Next due date semantics (existing E-1, E-2)
- **Current:** next due = completion day + interval; interval change does not move the due date (also affects AI advice).
- **Recommendation:** keep E-1 (a) (documented); E-2 (b): recompute `next_due_at = last_done_at + new interval` (or `min(old, today + new)`) when the interval changes, reset `notified_at`.

### PD-P5 · AI plant advice vs. manual intervals
- **Current:** unlabelled tasks get the AI interval silently; UI shows only counts.
- **Recommendation:** show old → new per task and let the user deselect.

## Shopping and food

### PD-S1 · Same item added twice
- **Current:** separate items. **Options:** (a) keep · (b) merge by normalised name (append quantity) · (c) warn "Milch steht schon auf der Liste".
- **Recommendation:** **(c)**; (b) is unreliable while quantity is free text.

### PD-S2 · Quantities as free text
- **Current:** free text (`"500 g Mehl"` as an ingredient name). **Recommendation:** keep until merge/sum features are wanted; then structured amount + unit.

### PD-M1 · Meal-poll decision on an occupied date
- **Current:** silent overwrite (CASA-19). **Options:** (a) keep · (b) confirm in the dialog showing the existing meal · (c) API 409 unless `replace=true`.
- **Recommendation:** **(b) + (c)**.

### PD-M2 · Target list and dedupe of "missing ingredients" (existing E-9)
- **Current:** recipe path → first list, exact-name dedupe; AI path → active list, no dedupe.
- **Recommendation:** one backend bulk endpoint used by both, targeting the active list, deduping against open items on all lists (case-insensitive, ignoring leading quantities).

### PD-M3 · Recipe deleted while planned
- **Options:** (a) keep entry with the recipe name as free text · (b) delete entries · (c) block deletion while planned in the future.
- **Recommendation:** **(a)**.

## Calendar and polls

### PD-K1 · Event reminders
- **Current:** none; not documented as planned. Everything else in the app reminds (todos, chores, pets, plants, documents).
- **Options:** (a) none · (b) push X minutes before for participants (or all if none) · (c) daily digest.
- **Recommendation:** decide explicitly; **(b)** is consistent with the rest of the app.

### PD-K2 · Event-poll option without a time
- **Current:** decided event starts "now". **Recommendation:** require a time, or create an all-day event on a chosen date.

### PD-K3 · Multi-day events on dashboard/widget "today"
- **Current:** only events starting today. **Recommendation:** every day the event spans (as the calendar does).

### PD-K4 · DST gap times
- **Current:** shifted +1 h silently / rejected as "end before start" (CASA-35). **Recommendation:** reject with a specific message, or normalise and tell the user.

### PD-K5 · Poll option times in the API (existing E-10)
- **Recommendation:** household time (b), as for events.

## Data, operations, AI

### PD-D1 · Account deletion semantics
- **Current:** no deletion path; FK rules would rewrite balances (CASCADE on shares/settlements) or block (NO ACTION) (CASA-55).
- **Options:** (a) anonymise the user, keep all rows · (b) hard delete with SET NULL everywhere · (c) keep current mix (not viable).
- **Recommendation:** **(a)**; change ledger FKs to RESTRICT before any GDPR feature.

### PD-D2 · Rollback strategy
- **Options:** (a) restore an old dump with old code (today; requires the CASA-07 fix) · (b) forward-only migrations, restore only for disaster recovery.
- **Recommendation:** **(b)** plus a fixed and rehearsed restore procedure.

### PD-D3 · Missed reminders after downtime
- **Current:** at-most-once; chores only on the same day, todos within 12 h; pets/plants/documents sent late.
- **Recommendation:** keep, but document per reminder type in `PROJECT-STATUS.md` §8.

### PD-A1 · AI day boundary (existing E-8)
- **Recommendation:** keep UTC (documented, low impact) unless users report confusion.

### PD-A2 · AI quota scope (existing A-01)
- **Current:** per household, multipliable via several households. **Recommendation:** add a per-user daily limit.

---

## Decision summary

| ID | Recommended option | Blocks |
|---|---|---|
| PD-F1 | soft delete + history + creator/editor | CASA-02, CASA-03 |
| PD-F2 | warn on retroactive changes | CASA-02 |
| PD-F3 | idempotency key + plausibility warning | CASA-08 |
| PD-F7 | diffs + version/409 for expenses | CASA-09 |
| PD-H1 | treat ex-member as unassigned now; clean up on leave later | CASA-22 |
| PD-H3 | lock + auto-promote when no admin | CASA-10 |
| PD-C1 | delete open future assignments on pause; re-anchor on reactivation | CASA-17 |
| PD-T1 | idempotent per household day | CASA-29 |
| PD-P1 | always allow dose, show last dose, confirm | CASA-14 |
| PD-P2 | block delete with history / archive pets | CASA-15 |
| PD-M1 | confirm + 409 on occupied date | CASA-19 |
| PD-K1 | event reminders yes/no | — |
| PD-D1 | anonymise users | CASA-55 |
| PD-D2 | forward-only migrations | CASA-07 |
