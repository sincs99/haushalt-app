import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { useExpensesStore } from './expenses'
import { createOnlineSettlementsRepository } from '../repositories/settlementsRepository'
import type { SettlementInfo, SettlementCreatePayload } from '../types'

export const useSettlementsStore = defineStore('settlements', () => {
  const repo = createOnlineSettlementsRepository()

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
    const authStore = useAuthStore()
    const hid = householdId ?? authStore.currentHouseholdId
    if (!hid) return

    loading.value = true
    error.value = null
    try {
      settlements.value = await repo.fetchAll(hid)
    } catch (e: any) {
      error.value = e.message || 'Fehler beim Laden der Zahlungen'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function create(payload: SettlementCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    error.value = null
    try {
      const created = await repo.create(householdId, payload)
      // Dedupe: falls Socket schneller war
      const idx = settlements.value.findIndex(s => s.id === created.id)
      if (idx === -1) {
        settlements.value.unshift(created)
      }
      debouncedFetchBalances()
      return created
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || 'Fehler beim Erstellen'
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
    } catch (e: any) {
      // Rollback
      if (removed && idx !== -1) settlements.value.splice(idx, 0, removed)
      error.value = e.response?.data?.detail || e.message || 'Fehler beim Löschen'
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
