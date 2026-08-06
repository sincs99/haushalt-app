import api from '../api/client'
import type { ChoreInfo, ChoreCreatePayload, ChoreUpdatePayload, ChoreAssignmentInfo } from '../types'

export interface ChoresRepository {
  fetchChores(householdId: string): Promise<ChoreInfo[]>
  createChore(householdId: string, payload: ChoreCreatePayload): Promise<ChoreInfo>
  updateChore(householdId: string, choreId: string, payload: ChoreUpdatePayload): Promise<ChoreInfo>
  removeChore(householdId: string, choreId: string): Promise<void>
  fetchAssignments(householdId: string, params?: { from?: string; to?: string }): Promise<ChoreAssignmentInfo[]>
  completeAssignment(householdId: string, assignmentId: string): Promise<ChoreAssignmentInfo>
  uncompleteAssignment(householdId: string, assignmentId: string): Promise<ChoreAssignmentInfo>
  reassignAssignment(householdId: string, assignmentId: string, assignedUserId: string): Promise<ChoreAssignmentInfo>
}

export function createOnlineChoresRepository(): ChoresRepository {
  return {
    async fetchChores(householdId) {
      const { data } = await api.get<ChoreInfo[]>(
        `/api/households/${householdId}/chores/`,
      )
      return data
    },

    async createChore(householdId, payload) {
      const { data } = await api.post<ChoreInfo>(
        `/api/households/${householdId}/chores/`,
        payload,
      )
      return data
    },

    async updateChore(householdId, choreId, payload) {
      const { data } = await api.patch<ChoreInfo>(
        `/api/households/${householdId}/chores/${choreId}`,
        payload,
      )
      return data
    },

    async removeChore(householdId, choreId) {
      await api.delete(
        `/api/households/${householdId}/chores/${choreId}`,
      )
    },

    async fetchAssignments(householdId, params) {
      const { data } = await api.get<ChoreAssignmentInfo[]>(
        `/api/households/${householdId}/chores/assignments`,
        { params },
      )
      return data
    },

    async completeAssignment(householdId, assignmentId) {
      const { data } = await api.post<ChoreAssignmentInfo>(
        `/api/households/${householdId}/chores/assignments/${assignmentId}/complete`,
      )
      return data
    },

    async uncompleteAssignment(householdId, assignmentId) {
      const { data } = await api.post<ChoreAssignmentInfo>(
        `/api/households/${householdId}/chores/assignments/${assignmentId}/uncomplete`,
      )
      return data
    },

    async reassignAssignment(householdId, assignmentId, assignedUserId) {
      const { data } = await api.patch<ChoreAssignmentInfo>(
        `/api/households/${householdId}/chores/assignments/${assignmentId}`,
        { assigned_user_id: assignedUserId },
      )
      return data
    },
  }
}
