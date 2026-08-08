import api from '../api/client'
import type { DashboardResponse } from '../types'

export interface DashboardRepository {
  fetchDashboard(householdId: string): Promise<DashboardResponse>
}

export function createOnlineDashboardRepository(): DashboardRepository {
  return {
    async fetchDashboard(householdId) {
      const { data } = await api.get<DashboardResponse>(
        `/api/households/${householdId}/dashboard`,
      )
      return data
    },
  }
}
