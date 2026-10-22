import { scopeRepository, isScopeChanged, currentDataGeneration, assertDataGeneration } from '../services/sessionScope'
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { useFinanceStore } from './finance'
import { createOnlineExpensesRepository } from '../repositories/expensesRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { translateApiError } from '../utils/apiErrors'
import { createRequestGuard } from '../utils/householdGuard'
import { createDeletedHistory } from '../utils/deletedHistory'
import { isStale } from '../utils/syncVersion'
import type { Expense, ExpenseCreatePayload, ExpenseUpdatePayload, BalancesResponse, HouseholdMemberInfo } from '../types'

/** Seitengrösse der Ausgabenliste („Mehr laden“, CASA-23) */
export const EXPENSES_PAGE_SIZE = 50

/** Fehlercode einer API-Antwort (detail.code) */
export function apiErrorCode(e: any): string | undefined {
  const detail = e?.response?.data?.detail
  return detail && typeof detail === 'object' ? detail.code : undefined
}

/** Neueste zuerst — gleiche Reihenfolge wie GET /expenses (Datum, dann Erfassung) */
function compareExpenses(a: Expense, b: Expense): number {
  if (a.expense_date !== b.expense_date) return a.expense_date < b.expense_date ? 1 : -1
  if (a.created_at !== b.created_at) return a.created_at < b.created_at ? 1 : -1
  return 0
}

export const useExpensesStore = defineStore('expenses', () => {
  const repo = scopeRepository(createOnlineExpensesRepository())
  const householdRepo = scopeRepository(createOnlineHouseholdsRepository())

  // State
  const expenses = ref<Expense[]>([])
  const balances = ref<BalancesResponse | null>(null)
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  /** Salden konnten nicht geladen werden (Karte zeigt dann einen Fehlerzustand) */
  const balancesError = ref(false)
  /** Weitere (ältere) Ausgaben auf dem Server vorhanden */
  const hasMore = ref(false)
  const loadingMore = ref(false)
  /** Verlauf: gelöschte Ausgaben (nur geladen, wenn der Verlauf geöffnet ist) */
  const deletedHistory = createDeletedHistory<Expense>((hid, params) => repo.fetchAll(hid, params), EXPENSES_PAGE_SIZE)
  const { items: deletedExpenses, loaded: deletedLoaded, hasMore: deletedHasMore,
    loading: deletedLoading, error: deletedError, fetch: fetchDeleted,
    loadMore: loadMoreDeleted, reset: resetDeleted } = deletedHistory

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
      fetchBalances(householdId).catch(() => {})
      useFinanceStore().fetchSummary(householdId).catch(() => {})
    }, 300)
  }

  /** Einfügen oder ersetzen (veraltete Versionen werden verworfen) und sortiert halten */
  function upsertSorted(incoming: Expense) {
    const idx = expenses.value.findIndex(e => e.id === incoming.id)
    if (idx !== -1) {
      if (isStale(expenses.value[idx], incoming)) return
      // Sortierschlüssel unverändert → an Ort und Stelle ersetzen
      if (compareExpenses(expenses.value[idx], incoming) === 0) {
        expenses.value[idx] = incoming
        return
      }
      expenses.value.splice(idx, 1)
    }
    const pos = expenses.value.findIndex(e => compareExpenses(incoming, e) <= 0)
    if (pos === -1) {
      // Älter als alles Geladene: nur anhängen, wenn die Liste vollständig ist —
      // sonst erscheint die Ausgabe beim „Mehr laden“ an der richtigen Stelle
      if (!hasMore.value) expenses.value.push(incoming)
    } else {
      expenses.value.splice(pos, 0, incoming)
    }
  }

  function dropDeleted(id: string) {
    deletedHistory.drop(id)
  }

  // Actions
  async function fetchExpenses(householdId?: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return
    const active = captureRequest(hid, 'expenses')

    loading.value = true
    error.value = null
    try {
      const page = await repo.fetchAll(hid, { limit: EXPENSES_PAGE_SIZE, offset: 0 })
      if (!active()) return
      expenses.value = page
      hasMore.value = page.length === EXPENSES_PAGE_SIZE
    } catch (e: any) {
      if (active()) error.value = translateApiError(e)
      throw e
    } finally {
      if (active.latest()) loading.value = false
    }
  }

  /** Nächste Seite älterer Ausgaben anhängen (Duplikate durch neue Einträge werden übersprungen) */
  async function loadMore() {
    const actionGeneration = currentDataGeneration()
    const hid = useAuthStore().currentHouseholdId
    if (!hid || loadingMore.value || !hasMore.value) return
    loadingMore.value = true
    try {
      const page = await repo.fetchAll(hid, { limit: EXPENSES_PAGE_SIZE, offset: expenses.value.length })
      assertDataGeneration(actionGeneration)
      const known = new Set(expenses.value.map(e => e.id))
      expenses.value.push(...page.filter(e => !known.has(e.id)))
      hasMore.value = page.length === EXPENSES_PAGE_SIZE
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      error.value = translateApiError(e)
      throw e
    } finally {
      if (actionGeneration === currentDataGeneration()) loadingMore.value = false
    }
  }



  async function fetchBalances(householdId?: string) {
    const actionGeneration = currentDataGeneration()
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
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      // Balances-Fehler nicht als Store-Error propagieren (nicht-kritisch),
      // aber merken, damit die Karte nicht still verschwindet
      if (active()) balancesError.value = true
      console.error('Failed to fetch balances:', e)
    }
  }

  async function fetchMembers(householdId?: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return
    const active = captureRequest(hid, 'members')

    try {
      const result = await householdRepo.fetchMembers(hid)
      if (active()) members.value = result
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      console.error('Failed to fetch members:', e)
    }
  }

  async function addExpense(payload: ExpenseCreatePayload) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    error.value = null
    try {
      // Kein Optimistic Update — Split wird serverseitig berechnet
      const created = await repo.create(householdId, payload)
      // Socket-Event wird die Liste aktualisieren, aber wir fügen
      assertDataGeneration(actionGeneration)
      // das Ergebnis trotzdem sofort ein (Dedupe im Handler)
      if (!expenses.value.some(e => e.id === created.id)) upsertSorted(created)
      debouncedFetchBalances()
      return created
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      error.value = translateApiError(e)
      throw e
    }
  }

  /**
   * Teil-Update mit Versionsprüfung (If-Match = bekannte Version, PD-F7).
   * 409 EXPENSE_VERSION_CONFLICT: der aktuelle Server-Stand ersetzt den lokalen,
   * der Fehler wird weitergeworfen (Dialog zeigt „inzwischen geändert“ und lädt neu).
   */
  async function editExpense(expenseId: string, payload: ExpenseUpdatePayload, version?: number) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const expectedVersion = version ?? expenses.value.find(e => e.id === expenseId)?.version
    error.value = null
    try {
      const updated = await repo.update(householdId, expenseId, payload, expectedVersion)
      assertDataGeneration(actionGeneration)
      upsertSorted(updated)
      debouncedFetchBalances()
      return updated
    } catch (e: any) {
      const code = apiErrorCode(e)
      assertDataGeneration(actionGeneration)
      if (code === 'EXPENSE_VERSION_CONFLICT') {
        const current = e.response.data.detail.current as Expense | undefined
        if (current) upsertSorted(current)
      } else if (code === 'EXPENSE_DELETED') {
        expenses.value = expenses.value.filter(x => x.id !== expenseId)
      }
      error.value = translateApiError(e)
      throw e
    }
  }

  /** Aktuellen Stand einer Ausgabe vom Server holen (z. B. nach einem Konflikt) */
  async function refreshExpense(expenseId: string): Promise<Expense | undefined> {
    const actionGeneration = currentDataGeneration()
    const hid = useAuthStore().currentHouseholdId
    if (!hid) return
    const fresh = await repo.get(hid, expenseId)
    assertDataGeneration(actionGeneration)
    if (fresh.deleted_at) {
      expenses.value = expenses.value.filter(e => e.id !== expenseId)
    } else {
      upsertSorted(fresh)
    }
    return fresh
  }

  async function removeExpense(expenseId: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic Delete (wie Shopping)
    const idx = expenses.value.findIndex(e => e.id === expenseId)
    const removed = idx !== -1 ? expenses.value[idx] : null
    if (idx !== -1) expenses.value.splice(idx, 1)

    try {
      await repo.remove(householdId, expenseId)
      assertDataGeneration(actionGeneration)
      debouncedFetchBalances()
      if (deletedLoaded.value || deletedLoading.value) fetchDeleted(householdId).catch(() => {})
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      // Rollback
      if (removed && idx !== -1) expenses.value.splice(idx, 0, removed)
      error.value = translateApiError(e)
      throw e
    }
  }

  /**
   * Gelöschte Ausgabe exakt wiederherstellen (Rückgängig, Verlauf) — inkl. Rechnungsbezug,
   * gebuchtem Monat und Ex-Mitgliedern (CASA-03). Wurde der Monat inzwischen neu gebucht,
   * lehnt der Server mit 409 BILL_ALREADY_BOOKED ab.
   */
  async function restoreExpense(expenseId: string) {
    const actionGeneration = currentDataGeneration()
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return
    error.value = null
    try {
      const restored = await repo.restore(householdId, expenseId)
      assertDataGeneration(actionGeneration)
      upsertSorted(restored)
      dropDeleted(expenseId)
      debouncedFetchBalances()
      return restored
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      error.value = translateApiError(e)
      throw e
    }
  }

  // Socket-Handler — Idempotente Merges (Server gewinnt, veraltete Versionen verworfen)
  function handleExpenseCreated(serverExpense: Expense) {
    // Auch bei Wiederherstellung (Server sendet dann expense_created)
    upsertSorted(serverExpense)
    dropDeleted(serverExpense.id)
    debouncedFetchBalances()
  }

  function handleExpenseUpdated(serverExpense: Expense) {
    upsertSorted(serverExpense)
    debouncedFetchBalances()
  }

  function handleExpenseDeleted(data: { id: string }) {
    expenses.value = expenses.value.filter(e => e.id !== data.id)
    debouncedFetchBalances()
    if (deletedLoaded.value || deletedLoading.value) fetchDeleted().catch(() => {})
  }

  return {
    // State
    expenses,
    balances,
    members,
    loading,
    error,
    balancesError,
    hasMore,
    loadingMore,
    deletedExpenses,
    deletedLoaded,
    deletedHasMore,
    deletedLoading,
    deletedError,
    loadMoreDeleted,
    resetDeleted,
    // Actions
    fetchExpenses,
    loadMore,
    fetchDeleted,
    fetchBalances,
    fetchMembers,
    addExpense,
    editExpense,
    refreshExpense,
    removeExpense,
    restoreExpense,
    // Socket-Handlers
    handleExpenseCreated,
    handleExpenseUpdated,
    handleExpenseDeleted,
  }
})
