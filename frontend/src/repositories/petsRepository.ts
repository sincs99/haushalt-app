import api from '../api/client'
import type {
  Pet, PetCreatePayload, PetUpdatePayload, FeedingLog, PetFeedingStatus,
  Medication, MedicationCreatePayload, MedicationUpdatePayload, MedicationLog,
  PetCareTask, PetCareTaskCreatePayload, PetCareTaskUpdatePayload,
} from '../types'

export interface PetsRepository {
  fetchAll(householdId: string): Promise<Pet[]>
  fetchOne(householdId: string, petId: string): Promise<Pet>
  create(householdId: string, data: PetCreatePayload): Promise<Pet>
  update(householdId: string, petId: string, data: PetUpdatePayload): Promise<Pet>
  remove(householdId: string, petId: string): Promise<void>
  fetchFeedingStatus(householdId: string): Promise<PetFeedingStatus[]>
  createFeeding(householdId: string, petId: string, slot: string): Promise<FeedingLog>
  deleteFeeding(householdId: string, petId: string, feedingId: string): Promise<void>
  feedAll(householdId: string, slot: string): Promise<FeedingLog[]>
  // Medications
  fetchMedications(householdId: string, petId: string, active?: boolean): Promise<Medication[]>
  createMedication(householdId: string, petId: string, data: MedicationCreatePayload): Promise<Medication>
  updateMedication(householdId: string, petId: string, medicationId: string, data: MedicationUpdatePayload): Promise<Medication>
  removeMedication(householdId: string, petId: string, medicationId: string): Promise<void>
  giveMedication(householdId: string, petId: string, medicationId: string): Promise<MedicationLog>
  fetchMedicationLog(householdId: string, petId: string, medicationId: string): Promise<MedicationLog[]>
  // Care Tasks
  fetchCareTasks(householdId: string, petId: string): Promise<PetCareTask[]>
  createCareTask(householdId: string, petId: string, data: PetCareTaskCreatePayload): Promise<PetCareTask>
  updateCareTask(householdId: string, petId: string, taskId: string, data: PetCareTaskUpdatePayload): Promise<PetCareTask>
  completeCareTask(householdId: string, petId: string, taskId: string): Promise<PetCareTask>
  removeCareTask(householdId: string, petId: string, taskId: string): Promise<void>
}

export function createOnlinePetsRepository(): PetsRepository {
  return {
    async fetchAll(householdId) {
      const { data } = await api.get<Pet[]>(
        `/api/households/${householdId}/pets/`,
      )
      return data
    },

    async fetchOne(householdId, petId) {
      const { data } = await api.get<Pet>(
        `/api/households/${householdId}/pets/${petId}`,
      )
      return data
    },

    async create(householdId, payload) {
      const { data } = await api.post<Pet>(
        `/api/households/${householdId}/pets/`,
        payload,
      )
      return data
    },

    async update(householdId, petId, payload) {
      const { data } = await api.patch<Pet>(
        `/api/households/${householdId}/pets/${petId}`,
        payload,
      )
      return data
    },

    async remove(householdId, petId) {
      await api.delete(
        `/api/households/${householdId}/pets/${petId}`,
      )
    },

    async fetchFeedingStatus(householdId) {
      const { data } = await api.get<PetFeedingStatus[]>(
        `/api/households/${householdId}/pets/feeding-status`,
      )
      return data
    },

    async createFeeding(householdId, petId, slot) {
      const { data } = await api.post<FeedingLog>(
        `/api/households/${householdId}/pets/${petId}/feedings`,
        { slot },
      )
      return data
    },

    async deleteFeeding(householdId, petId, feedingId) {
      await api.delete(
        `/api/households/${householdId}/pets/${petId}/feedings/${feedingId}`,
      )
    },

    async feedAll(householdId, slot) {
      const { data } = await api.post<FeedingLog[]>(
        `/api/households/${householdId}/pets/feed-all`,
        { slot },
      )
      return data
    },

    // ── Medications ──

    async fetchMedications(householdId, petId, active) {
      const params = active !== undefined ? { active } : {}
      const { data } = await api.get<Medication[]>(
        `/api/households/${householdId}/pets/${petId}/medications`,
        { params },
      )
      return data
    },

    async createMedication(householdId, petId, payload) {
      const { data } = await api.post<Medication>(
        `/api/households/${householdId}/pets/${petId}/medications`,
        payload,
      )
      return data
    },

    async updateMedication(householdId, petId, medicationId, payload) {
      const { data } = await api.patch<Medication>(
        `/api/households/${householdId}/pets/${petId}/medications/${medicationId}`,
        payload,
      )
      return data
    },

    async removeMedication(householdId, petId, medicationId) {
      await api.delete(
        `/api/households/${householdId}/pets/${petId}/medications/${medicationId}`,
      )
    },

    async giveMedication(householdId, petId, medicationId) {
      const { data } = await api.post<MedicationLog>(
        `/api/households/${householdId}/pets/${petId}/medications/${medicationId}/give`,
      )
      return data
    },

    async fetchMedicationLog(householdId, petId, medicationId) {
      const { data } = await api.get<MedicationLog[]>(
        `/api/households/${householdId}/pets/${petId}/medications/${medicationId}/log`,
      )
      return data
    },

    // ── Care Tasks ──

    async fetchCareTasks(householdId, petId) {
      const { data } = await api.get<PetCareTask[]>(
        `/api/households/${householdId}/pets/${petId}/care-tasks/`,
      )
      return data
    },

    async createCareTask(householdId, petId, payload) {
      const { data } = await api.post<PetCareTask>(
        `/api/households/${householdId}/pets/${petId}/care-tasks/`,
        payload,
      )
      return data
    },

    async updateCareTask(householdId, petId, taskId, payload) {
      const { data } = await api.patch<PetCareTask>(
        `/api/households/${householdId}/pets/${petId}/care-tasks/${taskId}`,
        payload,
      )
      return data
    },

    async completeCareTask(householdId, petId, taskId) {
      const { data } = await api.post<PetCareTask>(
        `/api/households/${householdId}/pets/${petId}/care-tasks/${taskId}/complete`,
      )
      return data
    },

    async removeCareTask(householdId, petId, taskId) {
      await api.delete(
        `/api/households/${householdId}/pets/${petId}/care-tasks/${taskId}`,
      )
    },
  }
}
