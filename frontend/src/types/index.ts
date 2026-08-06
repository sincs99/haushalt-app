export interface ShoppingItem {
  id: string
  household_id: string
  name: string
  quantity: string | null
  category: string | null
  is_checked: boolean
  added_by_user_id: string | null
  created_at: string
  checked_at: string | null
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
  paid_by_user_id: string | null
  expense_date: string
  created_at: string
  updated_at: string
  shares: ExpenseShare[]
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
}

export type ExpenseUpdatePayload = Partial<ExpenseCreatePayload>

export interface BalanceEntry {
  user_id: string
  paid_rappen: number
  owed_rappen: number
  saldo_rappen: number
}

export interface SettlementEntry {
  from_user_id: string
  to_user_id: string
  amount_rappen: number
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
}

export interface HouseholdMemberInfo {
  id: string
  display_name: string
}

export interface MeResponse {
  id: string
  email: string
  display_name: string
  households: HouseholdInfo[]
}
