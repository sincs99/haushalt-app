import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { useExpensesStore } from './expenses'
import { createOnlineSettlementsRepository } from '../repositories/settlementsRepository'
import { translateApiError } from '../utils/apiErrors'
import { createRequestGuard } from '../utils/householdGuard'
import type { SettlementInfo, SettlementCreatePayload, SettlementCheckResponse } from '../types'

/** Seitengrösse der Ausgleichsliste („Mehr laden“, CASA-23) */
export const SETTLEMENTS_PAGE_SIZE = 50

export const useSettlementsStore = defineStore('settlements', () => {
  const repo = createOnlineSettlementsRepository()

  // State
  const settlements = ref<SettlementInfo[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const hasMore = ref(false)
  const loadingMore = ref(false)
  /** Verlauf: gelöschte Ausgleiche (nur geladen, wenn der Verlauf geöffnet ist) */
  const deletedSettlements = ref<SettlementInfo[]>([])
  const deletedLoaded = ref(false)

  // Verspätete Antworten eines anderen Haushalts/einer alten Sitzung verwerfen (CASA-12)
  const captureRequest = createRequestGuard()

  // Debounce-Helper: Balances im Expenses-Store refetchen
  let balancesTimer: ReturnType<typeof setTimeout> | null = null
  function debouncedFetchBalances() {
    if (balancesTimer) clearTimeout(balancesTimer)
    balancesTimer = setTimeout(() => {
      const expensesStore = useExpensesStore()
      const authStore = useAuthStore()
      const householdId = authStore.currentHouseholdId
      if (householdId) expensesStore.fetchBalances(householdId)
    }, 300)
  }

  function upsertTop(incoming: SettlementInfo) {
    const idx = settlements.value.findIndex(s => s.id === incoming.id)
    if (idx !== -1) settlements.value[idx] = incoming
    else settlements.value.unshift(incoming)
  }

  // Actions
  async function fetchAll(householdId?: string) {
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return
    const active = captureRequest(hid, 'settlements')

    loading.value = true
    error.value = null
    try {
      const page = await repo.fetchAll(hid, { limit: SETTLEMENTS_PAGE_SIZE, offset: 0 })
      if (!active()) return
      settlements.value = page
      hasMore.value = page.length === SETTLEMENTS_PAGE_SIZE
    } catch (e: any) {
      if (active()) error.value = translateApiError(e)
      throw e
    } finally {
      if (active.latest()) loading.value = false
    }
  }

  async function loadMore() {
    const hid = useAuthStore().currentHouseholdId
    if (!hid || loadingMore.value || !hasMore.value) return
    loadingMore.value = true
    try {
      const page = await repo.fetchAll(hid, { limit: SETTLEMENTS_PAGE_SIZE, offset: settlements.value.length })
      const known = new Set(settlements.value.map(s => s.id))
      settlements.value.push(...page.filter(s => !known.has(s.id)))
      hasMore.value = page.length === SETTLEMENTS_PAGE_SIZE
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
    deletedSettlements.value = await repo.fetchAll(hid, { deleted: true, limit: SETTLEMENTS_PAGE_SIZE })
    deletedLoaded.value = true
  }

  /** Plausibilität vor dem Speichern prüfen (PD-F3: Duplikat, mehr als offene Schuld) */
  async function check(payload: SettlementCreatePayload): Promise<SettlementCheckResponse | undefined> {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return
    return repo.check(householdId, payload)
  }

  /**
   * Ausgleich speichern. Ohne `payload.id` wird eine Client-ID erzeugt — ein Retry mit
   * derselben ID (Timeout, Doppelklick) legt keinen zweiten Ausgleich an (CASA-08).
   */
  async function create(payload: SettlementCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    error.value = null
    try {
      const created = await repo.create(householdId, { ...payload, id: payload.id ?? crypto.randomUUID() })
      // Dedupe: falls Socket schneller war
      upsertTop(created)
      debouncedFetchBalances()
      return created
    } catch (e: any) {
      error.value = translateApiError(e)
      throw e
    }
  }

  async function remove(settlementId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic Delete
    const idx = settlements.value.findIndex(s => s.id === settlementId)
    const removed = idx !== -1 ? settlements.value[idx] : null
    if (idx !== -1) settlements.value.splice(idx, 1)

    try {
      await repo.remove(householdId, settlementId)
      debouncedFetchBalances()
      if (deletedLoaded.value) fetchDeleted(householdId).catch(() => {})
    } catch (e: any) {
      // Rollback
      if (removed && idx !== -1) settlements.value.splice(idx, 0, removed)
      error.value = translateApiError(e)
      throw e
    }
  }

  /** Gelöschten Ausgleich wiederherstellen (Rückgängig, Verlauf) */
  async function restore(settlementId: string) {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return
    error.value = null
    try {
      const restored = await repo.restore(householdId, settlementId)
      upsertTop(restored)
      deletedSettlements.value = deletedSettlements.value.filter(s => s.id !== settlementId)
      debouncedFetchBalances()
      return restored
    } catch (e: any) {
      error.value = translateApiError(e)
      throw e
    }
  }

  // Socket-Handler — Idempotent (Server gewinnt)
  function handleSettlementCreated(serverSettlement: SettlementInfo) {
    // Auch bei Wiederherstellung (Server sendet dann settlement_created)
    upsertTop(serverSettlement)
    deletedSettlements.value = deletedSettlements.value.filter(s => s.id !== serverSettlement.id)
    debouncedFetchBalances()
  }

  function handleSettlementDeleted(data: { id: string }) {
    settlements.value = settlements.value.filter(s => s.id !== data.id)
    debouncedFetchBalances()
    if (deletedLoaded.value) fetchDeleted().catch(() => {})
  }

  return {
    // State
    settlements,
    loading,
    error,
    hasMore,
    loadingMore,
    deletedSettlements,
    deletedLoaded,
    // Actions
    fetchAll,
    loadMore,
    fetchDeleted,
    check,
    create,
    remove,
    restore,
    // Socket-Handlers
    handleSettlementCreated,
    handleSettlementDeleted,
  }
})
