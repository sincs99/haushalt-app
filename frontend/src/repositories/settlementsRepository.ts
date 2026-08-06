import api from '../api/client'
import type { SettlementInfo, SettlementCreatePayload } from '../types'

export interface SettlementsRepository {
  fetchAll(householdId: string, params?: { limit?: number; offset?: number }): Promise<SettlementInfo[]>
  create(householdId: string, payload: SettlementCreatePayload): Promise<SettlementInfo>
  remove(householdId: string, settlementId: string): Promise<void>
}

export function createOnlineSettlementsRepository(): SettlementsRepository {
  return {
    async fetchAll(householdId, params) {
      const { data } = await api.get<SettlementInfo[]>(
        `/api/households/${householdId}/settlements/`,
        { params },
      )
      return data
    },

    async create(householdId, payload) {
      const { data } = await api.post<SettlementInfo>(
        `/api/households/${householdId}/settlements/`,
        payload,
      )
      return data
    },

    async remove(householdId, settlementId) {
      await api.delete(
        `/api/households/${householdId}/settlements/${settlementId}`,
      )
    },
  }
}
