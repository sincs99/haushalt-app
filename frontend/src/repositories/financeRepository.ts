import api from '../api/client'
import type { Budget, BudgetUpsertPayload, RecurringBill, RecurringBillCreatePayload, RecurringBillUpdatePayload, FinanceSummary, Expense } from '../types'

export interface FinanceRepository {
  // Budget
  getBudget(householdId: string, month?: string): Promise<Budget | null>
  upsertBudget(householdId: string, payload: BudgetUpsertPayload): Promise<Budget>

  // Recurring Bills
  fetchBills(householdId: string, includeInactive?: boolean): Promise<RecurringBill[]>
  createBill(householdId: string, payload: RecurringBillCreatePayload): Promise<RecurringBill>
  updateBill(householdId: string, billId: string, payload: RecurringBillUpdatePayload): Promise<RecurringBill>
  removeBill(householdId: string, billId: string): Promise<void>
  bookBill(householdId: string, billId: string): Promise<Expense>

  // Finance Summary
  getSummary(householdId: string, month?: string): Promise<FinanceSummary>
}

export function createOnlineFinanceRepository(): FinanceRepository {
  return {
    // Budget
    async getBudget(householdId, month) {
      const params = month ? { month } : undefined
      const { data } = await api.get<Budget | null>(
        `/api/households/${householdId}/budget`,
        { params },
      )
      return data
    },

    async upsertBudget(householdId, payload) {
      const { data } = await api.put<Budget>(
        `/api/households/${householdId}/budget`,
        payload,
      )
      return data
    },

    // Recurring Bills
    async fetchBills(householdId, includeInactive = false) {
      const params = includeInactive ? { include_inactive: 'true' } : undefined
      const { data } = await api.get<RecurringBill[]>(
        `/api/households/${householdId}/recurring-bills`,
        { params },
      )
      return data
    },

    async createBill(householdId, payload) {
      const { data } = await api.post<RecurringBill>(
        `/api/households/${householdId}/recurring-bills`,
        payload,
      )
      return data
    },

    async updateBill(householdId, billId, payload) {
      const { data } = await api.patch<RecurringBill>(
        `/api/households/${householdId}/recurring-bills/${billId}`,
        payload,
      )
      return data
    },

    async removeBill(householdId, billId) {
      await api.delete(
        `/api/households/${householdId}/recurring-bills/${billId}`,
      )
    },

    async bookBill(householdId, billId) {
      const { data } = await api.post<Expense>(
        `/api/households/${householdId}/recurring-bills/${billId}/book`,
      )
      return data
    },

    // Finance Summary
    async getSummary(householdId, month) {
      const params = month ? { month } : undefined
      const { data } = await api.get<FinanceSummary>(
        `/api/households/${householdId}/finance-summary`,
        { params },
      )
      return data
    },
  }
}
