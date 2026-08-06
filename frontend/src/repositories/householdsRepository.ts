import api from '../api/client'
import type { HouseholdInfo, HouseholdMemberInfo } from '../types'

export interface HouseholdsRepository {
  join(inviteCode: string): Promise<HouseholdInfo>
  fetchInviteCode(householdId: string): Promise<string>
  fetchMembers(householdId: string): Promise<HouseholdMemberInfo[]>
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
  }
}
