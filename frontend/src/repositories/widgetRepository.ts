import api from '../api/client'

export interface WidgetTokenStatus {
  exists: boolean
  token_prefix: string | null
  created_at: string | null
  last_used_at: string | null
}

export interface WidgetTokenCreated {
  token: string
  token_prefix: string
  created_at: string
}

/** Nur-Lese-Schlüssel fürs Homescreen-Widget (Backend: routers/widget.py) */
export function createOnlineWidgetRepository() {
  const url = (householdId: string) => `/api/households/${householdId}/widget-token`
  return {
    async fetchStatus(householdId: string): Promise<WidgetTokenStatus> {
      const { data } = await api.get<WidgetTokenStatus>(url(householdId))
      return data
    },
    async create(householdId: string): Promise<WidgetTokenCreated> {
      const { data } = await api.post<WidgetTokenCreated>(url(householdId))
      return data
    },
    async revoke(householdId: string): Promise<void> {
      await api.delete(url(householdId))
    },
  }
}
