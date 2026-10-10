import api from '../api/client'
import type { AdminHousehold, AdminOverview, AdminUser } from '../types'

/** Plattform-Admin (backend/app/routers/admin.py) — nur für Betreiber-Konten. */
export interface AdminRepository {
  fetchOverview(): Promise<AdminOverview>
  searchHouseholds(q: string): Promise<AdminHousehold[]>
  setPlan(householdId: string, plan: 'free' | 'premium', expiresAt: string | null, note: string): Promise<AdminHousehold>
  searchUsers(q: string): Promise<AdminUser[]>
  setUserActive(userId: string, isActive: boolean): Promise<AdminUser>
}

export function createOnlineAdminRepository(): AdminRepository {
  return {
    async fetchOverview() {
      const { data } = await api.get<AdminOverview>('/api/admin/overview')
      return data
    },
    async searchHouseholds(q) {
      const { data } = await api.get<AdminHousehold[]>('/api/admin/households', { params: { q } })
      return data
    },
    async setPlan(householdId, plan, expiresAt, note) {
      const { data } = await api.patch<AdminHousehold>(`/api/admin/households/${householdId}/plan`, {
        plan,
        expires_at: expiresAt,
        note: note || null,
      })
      return data
    },
    async searchUsers(q) {
      const { data } = await api.get<AdminUser[]>('/api/admin/users', { params: { q } })
      return data
    },
    async setUserActive(userId, isActive) {
      const { data } = await api.patch<AdminUser>(`/api/admin/users/${userId}`, { is_active: isActive })
      return data
    },
  }
}

export const adminRepository: AdminRepository = createOnlineAdminRepository()
