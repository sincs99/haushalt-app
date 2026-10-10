import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { useFinanceStore } from './finance'
import { createOnlineExpensesRepository } from '../repositories/expensesRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { translateApiError } from '../utils/apiErrors'
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
  /** Weitere (ältere) Ausgaben auf dem Server vorhanden */
  const hasMore = ref(false)
  const loadingMore = ref(false)
  /** Verlauf: gelöschte Ausgaben (nur geladen, wenn der Verlauf geöffnet ist) */
  const deletedExpenses = ref<Expense[]>([])
  const deletedLoaded = ref(false)

  // Debounce-Timer für Balances-Refetch
  let balancesTimer: ReturnType<typeof setTimeout> | null = null

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
    deletedExpenses.value = deletedExpenses.value.filter(e => e.id !== id)
  }

  // Actions
  async function fetchExpenses(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return

    loading.value = true
    error.value = null
    try {
      const page = await repo.fetchAll(hid, { limit: EXPENSES_PAGE_SIZE, offset: 0 })
      expenses.value = page
      hasMore.value = page.length === EXPENSES_PAGE_SIZE
    } catch (e: any) {
      error.value = translateApiError(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  /** Nächste Seite älterer Ausgaben anhängen (Duplikate durch neue Einträge werden übersprungen) */
  async function loadMore() {
    const hid = useAuthStore().currentHouseholdId
    if (!hid || loadingMore.value || !hasMore.value) return
    loadingMore.value = true
    try {
      const page = await repo.fetchAll(hid, { limit: EXPENSES_PAGE_SIZE, offset: expenses.value.length })
      const known = new Set(expenses.value.map(e => e.id))
      expenses.value.push(...page.filter(e => !known.has(e.id)))
      hasMore.value = page.length === EXPENSES_PAGE_SIZE
    } catch (e: any) {
      error.value = translateApiError(e)
      throw e
    } finally {
      loadingMore.value = false
    }
  }

  async function fetchDeleted(householdId?: string) {
    const hid = householdId ?? useAuthStore().currentHouseholdId
    if (!hid) return
    deletedExpenses.value = await repo.fetchAll(hid, { deleted: true, limit: EXPENSES_PAGE_SIZE })
    deletedLoaded.value = true
  }

  async function fetchBalances(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return

    try {
      balances.value = await repo.getBalances(hid)
      balancesError.value = false
    } catch (e: any) {
      // Balances-Fehler nicht als Store-Error propagieren (nicht-kritisch),
      // aber merken, damit die Karte nicht still verschwindet
      balancesError.value = true
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
      if (!expenses.value.some(e => e.id === created.id)) upsertSorted(created)
      debouncedFetchBalances()
      return created
    } catch (e: any) {
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
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const expectedVersion = version ?? expenses.value.find(e => e.id === expenseId)?.version
    error.value = null
    try {
      const updated = await repo.update(householdId, expenseId, payload, expectedVersion)
      upsertSorted(updated)
      debouncedFetchBalances()
      return updated
    } catch (e: any) {
      const code = apiErrorCode(e)
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
    const hid = useAuthStore().currentHouseholdId
    if (!hid) return
    const fresh = await repo.get(hid, expenseId)
    if (fresh.deleted_at) {
      expenses.value = expenses.value.filter(e => e.id !== expenseId)
    } else {
      upsertSorted(fresh)
    }
    return fresh
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
      if (deletedLoaded.value) fetchDeleted(householdId).catch(() => {})
    } catch (e: any) {
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
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return
    error.value = null
    try {
      const restored = await repo.restore(householdId, expenseId)
      upsertSorted(restored)
      dropDeleted(expenseId)
      debouncedFetchBalances()
      return restored
    } catch (e: any) {
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
    if (deletedLoaded.value) fetchDeleted().catch(() => {})
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
