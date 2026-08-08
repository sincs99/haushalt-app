// ── Shopping Lists ──

export interface ShoppingList {
  id: string
  household_id: string
  name: string
  icon: string | null
  position: number
  created_at: string
  open_count: number
}

export interface ShoppingListCreatePayload {
  name: string
  icon?: string
}

export interface ShoppingListUpdatePayload {
  name?: string
  icon?: string
  position?: number
}

export interface ShoppingItem {
  id: string
  household_id: string
  list_id: string
  name: string
  quantity: string | null
  category: string | null
  is_checked: boolean
  added_by_user_id: string | null
  created_at: string
  checked_at: string | null
  store: string | null
  assigned_to_user_id: string | null
}

export interface TodoItem {
  id: string
  household_id: string
  title: string
  description: string | null
  assigned_to_user_id: string | null
  due_date: string | null
  is_done: boolean
  created_by_user_id: string | null
  created_at: string
  done_at: string | null
  tags: string[]
}

// ── Notes ──

export interface NoteItem {
  id: string
  household_id: string
  title: string
  body: string
  tag: string | null
  pinned: boolean
  created_by_user_id: string | null
  created_at: string
  updated_at: string
}

// ── Unified Tasks ──

export interface UnifiedTask {
  type: 'todo' | 'chore'
  id: string
  title: string
  due_date: string | null
  assigned_to_user_id: string | null
  tags: string[]
  recurring: boolean
}

export interface UserInfo {
  id: string
  email: string
  display_name: string
}

// ── Expenses ──

export interface ExpenseShare {
  user_id: string
  amount_rappen: number
}

export interface Expense {
  id: string
  household_id: string
  description: string
  amount_rappen: number
  currency: string
  split_type: SplitType
  paid_by_user_id: string | null
  expense_date: string
  created_at: string
  updated_at: string
  shares: ExpenseShare[]
  category: string | null
  recurring_bill_id: string | null
}

export type SplitType = 'even' | 'custom'

export interface ExpenseCreatePayload {
  description: string
  amount_rappen: number
  currency?: string
  paid_by_user_id: string
  expense_date?: string
  split_type: SplitType
  shares?: ExpenseShare[]
  participant_ids?: string[]
  category?: string
}

export type ExpenseUpdatePayload = Partial<ExpenseCreatePayload>

// ── Budget ──

export interface Budget {
  id: string
  household_id: string
  month: string  // "YYYY-MM-DD" (immer 1. des Monats)
  amount_rappen: number
  created_at: string
  updated_at: string
}

export interface BudgetUpsertPayload {
  month: string
  amount_rappen: number
}

// ── Recurring Bills ──

export interface RecurringBill {
  id: string
  household_id: string
  name: string
  amount_rappen: number
  day_of_month: number
  category: string | null
  split_type: SplitType
  active: boolean
  created_at: string
}

export interface RecurringBillCreatePayload {
  name: string
  amount_rappen: number
  day_of_month: number
  category?: string
  split_type?: SplitType
  active?: boolean
}

export interface RecurringBillUpdatePayload {
  name?: string
  amount_rappen?: number
  day_of_month?: number
  category?: string | null
  split_type?: SplitType
  active?: boolean
}

// ── Finance Summary ──

export interface CategorySummary {
  category: string | null
  total_rappen: number
}

export interface PendingBillInfo {
  id: string
  name: string
  amount_rappen: number
  day_of_month: number
  category: string | null
  is_booked_this_month: boolean
}

export interface FinanceSummary {
  month: string
  budget_rappen: number | null
  total_spent_rappen: number
  remaining_rappen: number | null
  days_elapsed: number
  days_in_month: number
  by_category: CategorySummary[]
  pending_bills: PendingBillInfo[]
}

export interface BalanceEntry {
  user_id: string
  paid_rappen: number
  owed_rappen: number
  settled_out_rappen: number
  settled_in_rappen: number
  saldo_rappen: number
}

export interface SettlementEntry {
  from_user_id: string
  to_user_id: string
  amount_rappen: number
}

// ── Settlements ──

export interface SettlementInfo {
  id: string
  household_id: string
  from_user_id: string
  to_user_id: string
  amount_rappen: number
  currency: string
  settled_date: string
  note: string | null
  created_by_user_id: string | null
  created_at: string
}

export interface SettlementCreatePayload {
  from_user_id: string
  to_user_id: string
  amount_rappen: number
  currency?: string
  settled_date?: string
  note?: string
}

export interface BalancesResponse {
  balances: BalanceEntry[]
  settlements: SettlementEntry[]
  unassigned_rappen: number
}

export interface HouseholdInfo {
  id: string
  name: string
  role: string
  currency: string  // z.B. "CHF" — vom Backend via GET /api/auth/me
}

export interface HouseholdMemberInfo {
  id: string
  display_name: string
  role: string
}

export interface MeResponse {
  id: string
  email: string
  display_name: string
  households: HouseholdInfo[]
}

// ── Chores ──

export type ChoreRecurrence = 'weekly' | 'biweekly' | 'monthly'

export interface ChoreInfo {
  id: string
  household_id: string
  title: string
  description: string | null
  recurrence: ChoreRecurrence
  weekday: number | null        // 0=Mo..6=So
  day_of_month: number | null   // 1-31
  rotation_order: string[]      // User-UUID-Strings
  next_rotation_index: number
  anchor_date: string           // "YYYY-MM-DD"
  active: boolean
  created_at: string
  created_by_user_id: string | null
}

export interface ChoreCreatePayload {
  title: string
  description?: string
  recurrence: ChoreRecurrence
  weekday?: number
  day_of_month?: number
  rotation_order: string[]
  active?: boolean
}

export interface ChoreUpdatePayload {
  title?: string
  description?: string
  recurrence?: ChoreRecurrence
  weekday?: number
  day_of_month?: number
  rotation_order?: string[]
  active?: boolean
}

export interface ChoreAssignmentInfo {
  id: string
  household_id: string
  chore_id: string
  assigned_user_id: string | null
  due_date: string              // "YYYY-MM-DD"
  completed_at: string | null
  completed_by_user_id: string | null
  created_at: string
}

// ── Dashboard ──

export interface DashboardTodoItem {
  id: string
  title: string
  due_date: string | null
  is_overdue: boolean
  type: 'todo' | 'chore'
}

export interface DashboardTodoSection {
  open_count: number
  overdue_count: number
  items: DashboardTodoItem[]
}

export interface DashboardChoreItem {
  id: string
  title: string
  assigned_user_id: string | null
}

export interface DashboardChoreSection {
  items: DashboardChoreItem[]
}

export interface DashboardShoppingSection {
  open_count: number
  top_items: string[]
}

export interface DashboardFinanceSection {
  saldo_rappen: number
  currency: string
}

export interface DashboardEventItem {
  id: string
  title: string
  starts_at: string
  all_day: boolean
  category: string
}

export interface DashboardEventSection {
  items: DashboardEventItem[]
}

export interface DashboardResponse {
  todos: DashboardTodoSection
  chores: DashboardChoreSection
  shopping: DashboardShoppingSection
  finance: DashboardFinanceSection
  events: DashboardEventSection
}

// ── Calendar Events ──

export type EventCategory = 'arbeit' | 'katzen' | 'haushalt' | 'freunde' | 'geburtstage' | 'essen' | 'sonstiges'

export interface CalendarEvent {
  id: string
  household_id: string
  title: string
  starts_at: string          // ISO 8601
  ends_at: string | null
  all_day: boolean
  category: EventCategory
  participant_ids: string[]  // leer = ganzer Haushalt
  note: string | null
  created_by_user_id: string
  created_at: string
}

export interface CalendarEventCreatePayload {
  title: string
  starts_at: string
  ends_at?: string | null
  all_day?: boolean
  category?: EventCategory
  participant_ids?: string[]
  note?: string | null
}

export type CalendarEventUpdatePayload = Partial<CalendarEventCreatePayload>

// ── Event Polls ──

export interface PollVote {
  id: string
  user_id: string
  created_at: string
}

export interface PollOption {
  id: string
  label: string
  starts_at: string | null
  recipe_id: string | null
  votes: PollVote[]
}

export interface EventPoll {
  id: string
  household_id: string
  question: string
  status: 'offen' | 'entschieden'
  poll_type: string
  created_by_user_id: string
  decided_event_id: string | null
  decided_meal_date: string | null
  created_at: string
  options: PollOption[]
}

export interface PollOptionCreatePayload {
  label: string
  starts_at?: string | null
  recipe_id?: string | null
}

export interface PollCreatePayload {
  question: string
  options: PollOptionCreatePayload[]
  poll_type?: string
  meal_date?: string
}

export interface PollVotePayload {
  option_id: string
}

export interface PollDecidePayload {
  option_id: string
  event_title: string
  event_category?: string
}

export interface MealDecidePayload {
  option_id: string
}

// ── Pets ──

export type FeedingSlot = 'morning' | 'evening'

export interface HealthEntry {
  title: string
  subtitle: string
  severity: 'green' | 'yellow' | 'red'
}

export interface Pet {
  id: string
  household_id: string
  name: string
  species: string
  breed: string | null
  birthdate: string | null  // ISO date string
  weight_grams: number | null
  photo_url: string | null
  notes: string | null
  // Slice 3 Profil-Felder
  chip_number: string | null
  insurance: string | null
  vet_name: string | null
  food_notes: string | null
  health_entries: HealthEntry[] | null
  created_at: string
}

export interface PetCreatePayload {
  name: string
  species?: string
  breed?: string
  birthdate?: string
  weight_grams?: number
  notes?: string
  // Slice 3
  chip_number?: string
  insurance?: string
  vet_name?: string
  food_notes?: string
  health_entries?: HealthEntry[]
}

export interface PetUpdatePayload {
  name?: string
  species?: string
  breed?: string
  birthdate?: string
  weight_grams?: number
  notes?: string
  // Slice 3
  chip_number?: string
  insurance?: string
  vet_name?: string
  food_notes?: string
  health_entries?: HealthEntry[]
}

export interface FeedingLog {
  id: string
  household_id: string
  pet_id: string
  slot: FeedingSlot
  fed_at: string     // ISO datetime
  fed_by_user_id: string
  date: string       // ISO date
}

export interface PetFeedingStatus {
  pet_id: string
  pet_name: string
  morning: FeedingLog | null
  evening: FeedingLog | null
}

// ── Medications ──

export interface Medication {
  id: string
  household_id: string
  pet_id: string
  name: string
  dosage: string | null
  schedule: string | null
  active: boolean
  created_at: string
}

export interface MedicationCreatePayload {
  name: string
  dosage?: string
  schedule?: string
  active?: boolean
}

export interface MedicationUpdatePayload {
  name?: string
  dosage?: string
  schedule?: string
  active?: boolean
}

export interface MedicationLog {
  id: string
  household_id: string
  medication_id: string
  given_at: string
  given_by_user_id: string
  created_at: string
}

// ── Recipes & Meal Plan ──

export interface Recipe {
  id: string
  household_id: string
  name: string
  servings: number
  cost_rappen: number | null
  duration_min: number | null
  ingredients: string[]
  is_favorite: boolean
  created_at: string
}

export interface RecipeCreatePayload {
  name: string
  servings?: number
  cost_rappen?: number
  duration_min?: number
  ingredients?: string[]
  is_favorite?: boolean
}

export interface RecipeUpdatePayload {
  name?: string
  servings?: number
  cost_rappen?: number | null
  duration_min?: number | null
  ingredients?: string[]
  is_favorite?: boolean
}

export interface MealPlanEntry {
  id: string
  household_id: string
  date: string          // "YYYY-MM-DD"
  recipe_id: string | null
  free_text: string | null
  recipe: Recipe | null
}

export interface MealPlanAssignPayload {
  recipe_id?: string | null
  free_text?: string | null
}

export interface AddToShoppingResponse {
  added: string[]
  skipped: string[]
  list_id: string
}
