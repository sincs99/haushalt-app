import api from '../api/client'
import type {
  Plant, PlantCreatePayload, PlantUpdatePayload, PlantCareStatus,
  PlantCareTask, PlantCareTaskCreatePayload, PlantCareTaskUpdatePayload,
  PlantCareLog, PlantCareCompleteResponse,
} from '../types'

export interface PlantsRepository {
  fetchAll(householdId: string): Promise<Plant[]>
  fetchOne(householdId: string, plantId: string): Promise<Plant>
  create(householdId: string, data: PlantCreatePayload): Promise<Plant>
  update(householdId: string, plantId: string, data: PlantUpdatePayload): Promise<Plant>
  remove(householdId: string, plantId: string): Promise<void>
  fetchCareStatus(householdId: string): Promise<PlantCareStatus[]>
  waterAll(householdId: string): Promise<PlantCareLog[]>
  // Care Tasks
  fetchCareTasks(householdId: string, plantId: string): Promise<PlantCareTask[]>
  createCareTask(householdId: string, plantId: string, data: PlantCareTaskCreatePayload): Promise<PlantCareTask>
  updateCareTask(householdId: string, plantId: string, taskId: string, data: PlantCareTaskUpdatePayload): Promise<PlantCareTask>
  completeCareTask(householdId: string, plantId: string, taskId: string, note?: string): Promise<PlantCareCompleteResponse>
  removeCareTask(householdId: string, plantId: string, taskId: string): Promise<void>
  // Care Log
  fetchCareLog(householdId: string, plantId: string): Promise<PlantCareLog[]>
}

export function createOnlinePlantsRepository(): PlantsRepository {
  return {
    async fetchAll(householdId) {
      const { data } = await api.get<Plant[]>(
        `/api/households/${householdId}/plants/`,
      )
      return data
    },

    async fetchOne(householdId, plantId) {
      const { data } = await api.get<Plant>(
        `/api/households/${householdId}/plants/${plantId}`,
      )
      return data
    },

    async create(householdId, payload) {
      const { data } = await api.post<Plant>(
        `/api/households/${householdId}/plants/`,
        payload,
      )
      return data
    },

    async update(householdId, plantId, payload) {
      const { data } = await api.patch<Plant>(
        `/api/households/${householdId}/plants/${plantId}`,
        payload,
      )
      return data
    },

    async remove(householdId, plantId) {
      await api.delete(
        `/api/households/${householdId}/plants/${plantId}`,
      )
    },

    async fetchCareStatus(householdId) {
      const { data } = await api.get<PlantCareStatus[]>(
        `/api/households/${householdId}/plants/care-status`,
      )
      return data
    },

    async waterAll(householdId) {
      const { data } = await api.post<PlantCareLog[]>(
        `/api/households/${householdId}/plants/water-all`,
      )
      return data
    },

    // ── Care Tasks ──

    async fetchCareTasks(householdId, plantId) {
      const { data } = await api.get<PlantCareTask[]>(
        `/api/households/${householdId}/plants/${plantId}/care-tasks/`,
      )
      return data
    },

    async createCareTask(householdId, plantId, payload) {
      const { data } = await api.post<PlantCareTask>(
        `/api/households/${householdId}/plants/${plantId}/care-tasks/`,
        payload,
      )
      return data
    },

    async updateCareTask(householdId, plantId, taskId, payload) {
      const { data } = await api.patch<PlantCareTask>(
        `/api/households/${householdId}/plants/${plantId}/care-tasks/${taskId}`,
        payload,
      )
      return data
    },

    async completeCareTask(householdId, plantId, taskId, note) {
      const { data } = await api.post<PlantCareCompleteResponse>(
        `/api/households/${householdId}/plants/${plantId}/care-tasks/${taskId}/complete`,
        note ? { note } : undefined,
      )
      return data
    },

    async removeCareTask(householdId, plantId, taskId) {
      await api.delete(
        `/api/households/${householdId}/plants/${plantId}/care-tasks/${taskId}`,
      )
    },

    // ── Care Log ──

    async fetchCareLog(householdId, plantId) {
      const { data } = await api.get<PlantCareLog[]>(
        `/api/households/${householdId}/plants/${plantId}/care-log`,
      )
      return data
    },
  }
}
