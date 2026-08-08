import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineDashboardRepository } from '../repositories/dashboardRepository'
import type { DashboardResponse } from '../types'

export const useDashboardStore = defineStore('dashboard', () => {
  const repo = createOnlineDashboardRepository()

  // State
  const data = ref<DashboardResponse | null>(null)
  const loading = ref(false)

  // Debounce-Timer für Invalidierung
  let invalidateTimer: ReturnType<typeof setTimeout> | null = null

  // Actions
  async function fetchDashboard() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      data.value = await repo.fetchDashboard(householdId)
    } catch (e) {
      console.error('Failed to fetch dashboard:', e)
    } finally {
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
    fetchDashboard,
    invalidate,
  }
})
