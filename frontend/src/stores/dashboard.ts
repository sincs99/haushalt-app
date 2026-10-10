import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineDashboardRepository } from '../repositories/dashboardRepository'
import type { DashboardResponse } from '../types'
import { createRequestGuard } from '../utils/householdGuard'

export const useDashboardStore = defineStore('dashboard', () => {
  const repo = createOnlineDashboardRepository()

  // State
  const data = ref<DashboardResponse | null>(null)
  const loading = ref(false)
  /** Letztes Laden gescheitert → Ansicht zeigt „Erneut versuchen“ statt nur der Begrüssung */
  const loadError = ref(false)

  // Debounce-Timer für Invalidierung
  let invalidateTimer: ReturnType<typeof setTimeout> | null = null
  // Verspätete Antworten eines anderen Haushalts/einer alten Sitzung verwerfen (CASA-12)
  const captureRequest = createRequestGuard()

  // Actions
  async function fetchDashboard() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'dashboard')

    loading.value = true
    try {
      const result = await repo.fetchDashboard(householdId)
      if (!active()) return
      data.value = result
      loadError.value = false
    } catch (e) {
      // Nicht weiterwerfen: wird auch ungewartet (Socket-Invalidierung, App-Start) aufgerufen
      console.error('Failed to fetch dashboard:', e)
      if (active()) loadError.value = true
    } finally {
      if (active.latest()) loading.value = false
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
