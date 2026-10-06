import api from '../api/client'
import type {
  AiPlantCareAdvice, AiPlantCareRequest, AiRecipeRequest, AiRecipeSuggestion, AiSettings, AiStatus,
} from '../types'

/**
 * KI-Assistent — alle Aufrufe gehen an das eigene Backend.
 * Der Anbieter (Anthropic-API) wird vom Frontend nie direkt angesprochen.
 */
export interface AiRepository {
  fetchStatus(): Promise<AiStatus>
  fetchSettings(householdId: string): Promise<AiSettings>
  updateSettings(householdId: string, aiEnabled: boolean): Promise<AiSettings>
  suggestRecipe(householdId: string, data: AiRecipeRequest): Promise<AiRecipeSuggestion>
  plantCare(householdId: string, data: AiPlantCareRequest): Promise<AiPlantCareAdvice>
}

export function createOnlineAiRepository(): AiRepository {
  return {
    async fetchStatus() {
      const { data } = await api.get<AiStatus>('/api/ai/status')
      return data
    },

    async fetchSettings(householdId) {
      const { data } = await api.get<AiSettings>(`/api/households/${householdId}/ai/settings`)
      return data
    },

    async updateSettings(householdId, aiEnabled) {
      const { data } = await api.put<AiSettings>(
        `/api/households/${householdId}/ai/settings`,
        { ai_enabled: aiEnabled },
      )
      return data
    },

    async suggestRecipe(householdId, payload) {
      const { data } = await api.post<AiRecipeSuggestion>(
        `/api/households/${householdId}/ai/recipe`,
        payload,
      )
      return data
    },

    async plantCare(householdId, payload) {
      const { data } = await api.post<AiPlantCareAdvice>(
        `/api/households/${householdId}/ai/plant-care`,
        payload,
      )
      return data
    },
  }
}
