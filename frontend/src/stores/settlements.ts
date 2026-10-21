import { scopeRepository, isScopeChanged, currentDataGeneration, assertDataGeneration } from '../services/sessionScope'
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { useExpensesStore } from './expenses'
import { createOnlineSettlementsRepository } from '../repositories/settlementsRepository'
import { translateApiError } from '../utils/apiErrors'
import type { SettlementInfo, SettlementCreatePayload } from '../types'

export const useSettlementsStore = defineStore('settlements', () => {
  const repo = scopeRepository(createOnlineSettlementsRepository())

  // State
  const settlements = ref<SettlementInfo[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

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

  // Actions
  async function fetchAll(householdId?: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return

    loading.value = true
    error.value = null
    try {
      const scopedResult = await repo.fetchAll(hid)
      assertDataGeneration(actionGeneration)
      settlements.value = scopedResult
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      error.value = translateApiError(e)
      throw e
    } finally {
      assertDataGeneration(actionGeneration)
      loading.value = false
    }
  }

  async function create(payload: SettlementCreatePayload) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    error.value = null
    try {
      const created = await repo.create(householdId, payload)
      // Dedupe: falls Socket schneller war
      assertDataGeneration(actionGeneration)
      const idx = settlements.value.findIndex(s => s.id === created.id)
      if (idx === -1) {
        settlements.value.unshift(created)
      }
      debouncedFetchBalances()
      return created
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      error.value = translateApiError(e)
      throw e
    }
  }

  async function remove(settlementId: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic Delete
    const idx = settlements.value.findIndex(s => s.id === settlementId)
    const removed = idx !== -1 ? settlements.value[idx] : null
    if (idx !== -1) settlements.value.splice(idx, 1)

    try {
      await repo.remove(householdId, settlementId)
      assertDataGeneration(actionGeneration)
      debouncedFetchBalances()
    } catch (e: any) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      // Rollback
      if (removed && idx !== -1) settlements.value.splice(idx, 0, removed)
      error.value = translateApiError(e)
      throw e
    }
  }

  // Socket-Handler — Idempotent (Server gewinnt)
  function handleSettlementCreated(serverSettlement: SettlementInfo) {
    const idx = settlements.value.findIndex(s => s.id === serverSettlement.id)
    if (idx !== -1) {
      settlements.value[idx] = serverSettlement
    } else {
      settlements.value.unshift(serverSettlement)
    }
    debouncedFetchBalances()
  }

  function handleSettlementDeleted(data: { id: string }) {
    settlements.value = settlements.value.filter(s => s.id !== data.id)
    debouncedFetchBalances()
  }

  return {
    // State
    settlements,
    loading,
    error,
    // Actions
    fetchAll,
    create,
    remove,
    // Socket-Handlers
    handleSettlementCreated,
    handleSettlementDeleted,
  }
})
