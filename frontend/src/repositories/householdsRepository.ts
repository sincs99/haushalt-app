import api from '../api/client'
import type { HouseholdInfo, HouseholdMemberInfo } from '../types'

export interface HouseholdsRepository {
  join(inviteCode: string): Promise<HouseholdInfo>
  fetchInviteCode(householdId: string): Promise<string>
  fetchMembers(householdId: string): Promise<HouseholdMemberInfo[]>
  create(name: string): Promise<HouseholdInfo>
  rename(householdId: string, name: string): Promise<void>
  leave(householdId: string): Promise<void>
  removeMember(householdId: string, userId: string): Promise<void>
}

export function createOnlineHouseholdsRepository(): HouseholdsRepository {
  return {
    async join(inviteCode) {
      const { data } = await api.post<HouseholdInfo>(
        '/api/households/join',
        { invite_code: inviteCode },
      )
      return data
    },

    async fetchInviteCode(householdId) {
      const { data } = await api.get<{ invite_code: string }>(
        `/api/households/${householdId}/invite-code`,
      )
      return data.invite_code
    },

    async fetchMembers(householdId) {
      const { data } = await api.get<HouseholdMemberInfo[]>(
        `/api/households/${householdId}/members`,
      )
      return data
    },

    async create(name) {
      const { data } = await api.post<HouseholdInfo>('/api/households/', { name })
      return data
    },

    async rename(householdId, name) {
      await api.patch(`/api/households/${householdId}`, { name })
    },

    async leave(householdId) {
      await api.post(`/api/households/${householdId}/leave`)
    },

    async removeMember(householdId, userId) {
      await api.delete(`/api/households/${householdId}/members/${userId}`)
    },
  }
}
