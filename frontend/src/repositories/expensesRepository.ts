import api from '../api/client'
import type { Expense, ExpenseCreatePayload, ExpenseUpdatePayload, BalancesResponse } from '../types'

export interface ExpensesRepository {
  fetchAll(householdId: string, params?: { limit?: number; offset?: number }): Promise<Expense[]>
  create(householdId: string, payload: ExpenseCreatePayload): Promise<Expense>
  update(householdId: string, expenseId: string, payload: ExpenseUpdatePayload): Promise<Expense>
  remove(householdId: string, expenseId: string): Promise<void>
  getBalances(householdId: string): Promise<BalancesResponse>
}

export function createOnlineExpensesRepository(): ExpensesRepository {
  return {
    async fetchAll(householdId, params) {
      const { data } = await api.get<Expense[]>(
        `/api/households/${householdId}/expenses/`,
        { params },
      )
      return data
    },

    async create(householdId, payload) {
      const { data } = await api.post<Expense>(
        `/api/households/${householdId}/expenses/`,
        payload,
      )
      return data
    },

    async update(householdId, expenseId, payload) {
      const { data } = await api.patch<Expense>(
        `/api/households/${householdId}/expenses/${expenseId}`,
        payload,
      )
      return data
    },

    async remove(householdId, expenseId) {
      await api.delete(
        `/api/households/${householdId}/expenses/${expenseId}`,
      )
    },

    async getBalances(householdId) {
      const { data } = await api.get<BalancesResponse>(
        `/api/households/${householdId}/expenses/balances`,
      )
      return data
    },
  }
}
