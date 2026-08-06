import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineExpensesRepository } from '../repositories/expensesRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type { Expense, ExpenseCreatePayload, ExpenseUpdatePayload, BalancesResponse, HouseholdMemberInfo } from '../types'

export const useExpensesStore = defineStore('expenses', () => {
  const repo = createOnlineExpensesRepository()
  const householdRepo = createOnlineHouseholdsRepository()

  // State
  const expenses = ref<Expense[]>([])
  const balances = ref<BalancesResponse | null>(null)
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Debounce-Timer für Balances-Refetch
  let balancesTimer: ReturnType<typeof setTimeout> | null = null

  function debouncedFetchBalances() {
    if (balancesTimer) clearTimeout(balancesTimer)
    balancesTimer = setTimeout(() => {
      const authStore = useAuthStore()
      const householdId = authStore.currentHouseholdId
      if (householdId) fetchBalances(householdId)
    }, 300)
  }

  // Actions
  async function fetchExpenses(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return

    loading.value = true
    error.value = null
    try {
      expenses.value = await repo.fetchAll(hid)
    } catch (e: any) {
      error.value = e.message || 'Fehler beim Laden der Ausgaben'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchBalances(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return

    try {
      balances.value = await repo.getBalances(hid)
    } catch (e: any) {
      // Balances-Fehler nicht als Store-Error propagieren (nicht-kritisch)
      console.error('Failed to fetch balances:', e)
    }
  }

  async function fetchMembers(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return

    try {
      members.value = await householdRepo.fetchMembers(hid)
    } catch (e: any) {
      console.error('Failed to fetch members:', e)
    }
  }

  async function addExpense(payload: ExpenseCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    error.value = null
    try {
      // Kein Optimistic Update — Split wird serverseitig berechnet
      const created = await repo.create(householdId, payload)
      // Socket-Event wird die Liste aktualisieren, aber wir fügen
      // das Ergebnis trotzdem sofort ein (Dedupe im Handler)
      const idx = expenses.value.findIndex(e => e.id === created.id)
      if (idx === -1) {
        // An den Anfang einsortieren (neueste zuerst)
        expenses.value.unshift(created)
      }
      debouncedFetchBalances()
      return created
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || 'Fehler beim Erstellen'
      throw e
    }
  }

  async function editExpense(expenseId: string, payload: ExpenseUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    error.value = null
    try {
      const updated = await repo.update(householdId, expenseId, payload)
      const idx = expenses.value.findIndex(e => e.id === updated.id)
      if (idx !== -1) {
        expenses.value[idx] = updated
      }
      debouncedFetchBalances()
      return updated
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || 'Fehler beim Bearbeiten'
      throw e
    }
  }

  async function removeExpense(expenseId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic Delete (wie Shopping)
    const idx = expenses.value.findIndex(e => e.id === expenseId)
    const removed = idx !== -1 ? expenses.value[idx] : null
    if (idx !== -1) expenses.value.splice(idx, 1)

    try {
      await repo.remove(householdId, expenseId)
      debouncedFetchBalances()
    } catch (e: any) {
      // Rollback
      if (removed && idx !== -1) expenses.value.splice(idx, 0, removed)
      error.value = e.response?.data?.detail || e.message || 'Fehler beim Löschen'
      throw e
    }
  }

  // Socket-Handler — Idempotente Merges (Server gewinnt immer)
  function handleExpenseCreated(serverExpense: Expense) {
    const idx = expenses.value.findIndex(e => e.id === serverExpense.id)
    if (idx !== -1) {
      expenses.value[idx] = serverExpense  // Dedupe: Server gewinnt
    } else {
      expenses.value.unshift(serverExpense)
    }
    debouncedFetchBalances()
  }

  function handleExpenseUpdated(serverExpense: Expense) {
    const idx = expenses.value.findIndex(e => e.id === serverExpense.id)
    if (idx !== -1) {
      expenses.value[idx] = serverExpense
    } else {
      expenses.value.unshift(serverExpense)
    }
    debouncedFetchBalances()
  }

  function handleExpenseDeleted(data: { id: string }) {
    expenses.value = expenses.value.filter(e => e.id !== data.id)
    debouncedFetchBalances()
  }

  return {
    // State
    expenses,
    balances,
    members,
    loading,
    error,
    // Actions
    fetchExpenses,
    fetchBalances,
    fetchMembers,
    addExpense,
    editExpense,
    removeExpense,
    // Socket-Handlers
    handleExpenseCreated,
    handleExpenseUpdated,
    handleExpenseDeleted,
  }
})
