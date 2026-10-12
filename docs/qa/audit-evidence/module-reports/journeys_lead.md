# Lead auditor journeys (PG-verified)
J1 (j1_finance_leave.py, output j1.out): 3 members; rent bill booked (Anna payer), Ben groceries, Carla leaves; all suggestions recorded -> all saldi 0 (OK).
 Then Ben deletes Anna's already-settled rent expense (204, any member may delete any expense, no audit, no warning) -> saldi invert: Carla(ex-member, cannot see app: 403) +1000 CHF creditor, Anna -2000.
 Re-booking same month allowed after deletion (201) and now split among 2 current members only -> Carla credited 1000 CHF for rent she really paid; ledger says Anna & Ben owe Carla 500 each.
 Default payer (Anna) leaves -> booking bill: 422 USERS_NOT_IN_HOUSEHOLD with raw UUID; bill list still shows Anna as payer.
J3 (j3_expense_concurrent_patch.py): 40 trials two concurrent PATCHes on same expense (amount change vs participants) on PG: 37/40 -> one request HTTP 500
 (IntegrityError uq_expense_share_user, unhandled) + SAWarning "expected to delete 3 rows; 0 matched"; 3/40 both 200 = silent last-writer-wins. Shares-sum invariant held in all 40.
J4 (j4_meal_shopping.py): manual plan Pasta for Sat; meal poll decided (Zopf) silently overwrites it. meal-decide emits meal_plan_updated with ONLY {"date"}
 (polls.py meal_decide_poll ~L432) whereas PUT emits full entry; frontend food.ts handleMealPlanUpdated (L208-215) replaces entry by {date} -> other members see "no meal"
 (FoodView getDisplayName L150-155) and add-missing uses entry.id undefined until reload. Decider refetches (FoodView L357) but own socket event may arrive after refetch.
 Vote after decision -> 400 (OK). add-missing: dedupe only exact lowercase name on FIRST list ("500 g Mehl" added though "Mehl" open on list 2; duplicate "Butter" in recipe skipped OK); repeat import idempotent (OK).
 Recipe deleted -> meal plan entry remains with recipe_id NULL and free_text NULL (state the PUT endpoint forbids) -> shown as "no meal", add-missing 400.
