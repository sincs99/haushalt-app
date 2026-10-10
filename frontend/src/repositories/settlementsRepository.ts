import api from '../api/client'
import { deleteIdempotent } from './http'
import type { SettlementInfo, SettlementCreatePayload, SettlementCheckResponse } from '../types'

export interface SettlementListParams {
  limit?: number
  offset?: number
  /** true: nur gelöschte Ausgleiche (Verlauf) */
  deleted?: boolean
}

export interface SettlementsRepository {
  fetchAll(householdId: string, params?: SettlementListParams): Promise<SettlementInfo[]>
  /** Plausibilität prüfen ohne zu speichern (Duplikat? mehr als offene Schuld?) */
  check(householdId: string, payload: SettlementCreatePayload): Promise<SettlementCheckResponse>
  create(householdId: string, payload: SettlementCreatePayload): Promise<SettlementInfo>
  remove(householdId: string, settlementId: string): Promise<void>
  restore(householdId: string, settlementId: string): Promise<SettlementInfo>
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

    async check(householdId, payload) {
      const { data } = await api.post<SettlementCheckResponse>(
        `/api/households/${householdId}/settlements/check`,
        payload,
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
      await deleteIdempotent(
        `/api/households/${householdId}/settlements/${settlementId}`,
      )
    },

    async restore(householdId, settlementId) {
      const { data } = await api.post<SettlementInfo>(
        `/api/households/${householdId}/settlements/${settlementId}/restore`,
      )
      return data
    },
  }
}
