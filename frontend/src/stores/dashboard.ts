import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineDashboardRepository } from '../repositories/dashboardRepository'
import type { DashboardResponse } from '../types'

/**
 * Weitere Socket-Events, nach denen das Dashboard neu lädt (CASA-43): Ämtli
 * angelegt/geändert/pausiert/gelöscht, Tiere (Pflegeaufgaben hängen am Tier) und
 * Kalender (Löschen entfernt seine Termine). Die übrigen Quellen bindet App.vue einzeln.
 */
export const DASHBOARD_EXTRA_EVENTS = [
  'chore_created',
  'chore_updated',
  'chore_deleted',
  'chore_assignments_deleted',
  'pet_created',
  'pet_updated',
  'pet_deleted',
  'calendar_deleted',
] as const

export const useDashboardStore = defineStore('dashboard', () => {
  const repo = createOnlineDashboardRepository()

  // State
  const data = ref<DashboardResponse | null>(null)
  const loading = ref(false)
  /** Letztes Laden gescheitert → Ansicht zeigt „Erneut versuchen“ statt nur der Begrüssung */
  const loadError = ref(false)

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
      loadError.value = false
    } catch (e) {
      // Nicht weiterwerfen: wird auch ungewartet (Socket-Invalidierung, App-Start) aufgerufen
      console.error('Failed to fetch dashboard:', e)
      loadError.value = true
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
    loadError,
    fetchDashboard,
    invalidate,
  }
})
