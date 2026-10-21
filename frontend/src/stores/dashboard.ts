import { scopeRepository, isScopeChanged, currentDataGeneration, assertDataGeneration } from '../services/sessionScope'
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineDashboardRepository } from '../repositories/dashboardRepository'
import type { DashboardResponse } from '../types'

export const useDashboardStore = defineStore('dashboard', () => {
  const repo = scopeRepository(createOnlineDashboardRepository())

  // State
  const data = ref<DashboardResponse | null>(null)
  const loading = ref(false)
  /** Letztes Laden gescheitert → Ansicht zeigt „Erneut versuchen“ statt nur der Begrüssung */
  const loadError = ref(false)

  // Debounce-Timer für Invalidierung
  let invalidateTimer: ReturnType<typeof setTimeout> | null = null

  // Actions
  async function fetchDashboard() {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      const scopedResult = await repo.fetchDashboard(householdId)
      assertDataGeneration(actionGeneration)
      data.value = scopedResult
      loadError.value = false
    } catch (e) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(e)) throw e
      // Nicht weiterwerfen: wird auch ungewartet (Socket-Invalidierung, App-Start) aufgerufen
      console.error('Failed to fetch dashboard:', e)
      loadError.value = true
    } finally {
      assertDataGeneration(actionGeneration)
      loading.value = false
    }
  }

  /** Debounced Refetch — wird bei Socket-Events der Quellmodule aufgerufen */
  function invalidate() {
    if (invalidateTimer) clearTimeout(invalidateTimer)
    invalidateTimer = setTimeout(() => {
      fetchDashboard()
    }, 500)
  }

  return {
    data,
    loading,
    loadError,
    fetchDashboard,
    invalidate,
  }
})
