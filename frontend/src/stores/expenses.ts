import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { useFinanceStore } from './finance'
import { createOnlineExpensesRepository } from '../repositories/expensesRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { translateApiError } from '../utils/apiErrors'
import { createRequestGuard } from '../utils/householdGuard'
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
  /** Salden konnten nicht geladen werden (Karte zeigt dann einen Fehlerzustand) */
  const balancesError = ref(false)

  // Debounce-Timer für Balances-Refetch
  let balancesTimer: ReturnType<typeof setTimeout> | null = null

  // Verspätete Antworten eines anderen Haushalts/einer alten Sitzung verwerfen (CASA-12)
  const captureRequest = createRequestGuard()

  /**
   * Nach Änderungen an Ausgaben: Salden und Budget-Übersicht („Noch verfügbar“,
   * Kategorien, gebuchte Rechnungen) gebündelt neu laden.
   */
  function debouncedFetchBalances() {
    if (balancesTimer) clearTimeout(balancesTimer)
    balancesTimer = setTimeout(() => {
      const authStore = useAuthStore()
      const householdId = authStore.currentHouseholdId
      if (!householdId) return
      fetchBalances(householdId)
      useFinanceStore().fetchSummary(householdId).catch(() => {})
    }, 300)
  }

  // Actions
  async function fetchExpenses(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return
    const active = captureRequest(hid, 'expenses')

    loading.value = true
    error.value = null
    try {
      const result = await repo.fetchAll(hid)
      if (active()) expenses.value = result
    } catch (e: any) {
      if (active()) error.value = translateApiError(e)
      throw e
    } finally {
      if (active.latest()) loading.value = false
    }
  }

  async function fetchBalances(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return
    const active = captureRequest(hid, 'balances')

    try {
      const result = await repo.getBalances(hid)
      if (!active()) return
      balances.value = result
      balancesError.value = false
    } catch (e: any) {
      // Balances-Fehler nicht als Store-Error propagieren (nicht-kritisch),
      // aber merken, damit die Karte nicht still verschwindet
      if (active()) balancesError.value = true
      console.error('Failed to fetch balances:', e)
    }
  }

  async function fetchMembers(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return
    const active = captureRequest(hid, 'members')

    try {
      const result = await householdRepo.fetchMembers(hid)
      if (active()) members.value = result
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
      error.value = translateApiError(e)
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
      error.value = translateApiError(e)
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
      error.value = translateApiError(e)
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
    balancesError,
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
