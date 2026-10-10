import api from '../api/client'
import { deleteIdempotent } from './http'
import type { Expense, ExpenseCreatePayload, ExpenseUpdatePayload, BalancesResponse } from '../types'

export interface ExpenseListParams {
  limit?: number
  offset?: number
  /** Nur Ausgaben dieses Monats (YYYY-MM-01) */
  month?: string
  /** true: nur gelöschte Ausgaben (Verlauf) */
  deleted?: boolean
}

export interface ExpensesRepository {
  fetchAll(householdId: string, params?: ExpenseListParams): Promise<Expense[]>
  get(householdId: string, expenseId: string): Promise<Expense>
  create(householdId: string, payload: ExpenseCreatePayload): Promise<Expense>
  /** `version` → If-Match: veralteter Stand wird mit 409 EXPENSE_VERSION_CONFLICT abgelehnt */
  update(householdId: string, expenseId: string, payload: ExpenseUpdatePayload, version?: number): Promise<Expense>
  remove(householdId: string, expenseId: string): Promise<void>
  restore(householdId: string, expenseId: string): Promise<Expense>
  getBalances(householdId: string): Promise<BalancesResponse>
}

function ifMatch(version?: number) {
  return version !== undefined ? { headers: { 'If-Match': `"${version}"` } } : undefined
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

    async get(householdId, expenseId) {
      const { data } = await api.get<Expense>(
        `/api/households/${householdId}/expenses/${expenseId}`,
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

    async update(householdId, expenseId, payload, version) {
      const { data } = await api.patch<Expense>(
        `/api/households/${householdId}/expenses/${expenseId}`,
        payload,
        ifMatch(version),
      )
      return data
    },

    async remove(householdId, expenseId) {
      await deleteIdempotent(
        `/api/households/${householdId}/expenses/${expenseId}`,
      )
    },

    async restore(householdId, expenseId) {
      const { data } = await api.post<Expense>(
        `/api/households/${householdId}/expenses/${expenseId}/restore`,
      )
      return data
    },

    async getBalances(householdId) {
      const { data } = await api.get<BalancesResponse>(
        `/api/households/${householdId}/expenses/balances`,
      )
      return data
    },
  }
}
