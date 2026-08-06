import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineChoresRepository } from '../repositories/choresRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type { ChoreInfo, ChoreCreatePayload, ChoreUpdatePayload, ChoreAssignmentInfo, HouseholdMemberInfo } from '../types'

export const useChoresStore = defineStore('chores', () => {
  const repo = createOnlineChoresRepository()
  const householdRepo = createOnlineHouseholdsRepository()

  // State
  const chores = ref<ChoreInfo[]>([])
  const assignments = ref<ChoreAssignmentInfo[]>([])
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)

  // Mutex für Toggle-Operationen (wie pendingToggles in todos.ts)
  const pendingToggles = new Set<string>()

  // Actions
  async function fetchChores() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      chores.value = await repo.fetchChores(householdId)
    } finally {
      loading.value = false
    }
  }

  async function fetchAssignments(params?: { from?: string; to?: string }) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      assignments.value = await repo.fetchAssignments(householdId, params)
    } finally {
      loading.value = false
    }
  }

  async function fetchMembers() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    members.value = await householdRepo.fetchMembers(householdId)
  }

  async function createChore(payload: ChoreCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const created = await repo.createChore(householdId, payload)
    // Dedupe: falls Socket schneller war
    const idx = chores.value.findIndex(c => c.id === created.id)
    if (idx === -1) {
      chores.value.push(created)
    } else {
      chores.value[idx] = created
    }
    return created
  }

  async function updateChore(choreId: string, payload: ChoreUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.updateChore(householdId, choreId, payload)
    const idx = chores.value.findIndex(c => c.id === choreId)
    if (idx !== -1) {
      chores.value[idx] = updated
    }
    // Bei Schedule-Änderung: Assignments neu laden
    if (payload.recurrence || payload.weekday !== undefined || payload.day_of_month !== undefined) {
      await fetchAssignments()
    }
    return updated
  }

  async function removeChore(choreId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic Delete
    const idx = chores.value.findIndex(c => c.id === choreId)
    const removed = idx !== -1 ? chores.value[idx] : null
    if (idx !== -1) chores.value.splice(idx, 1)
    // Auch zugehörige Assignments entfernen
    assignments.value = assignments.value.filter(a => a.chore_id !== choreId)

    try {
      await repo.removeChore(householdId, choreId)
    } catch (error) {
      // Rollback
      if (removed && idx !== -1) chores.value.splice(idx, 0, removed)
      throw error
    }
  }

  async function completeAssignment(assignmentId: string) {
    if (pendingToggles.has(assignmentId)) return
    pendingToggles.add(assignmentId)

    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) {
      pendingToggles.delete(assignmentId)
      return
    }

    const item = assignments.value.find(a => a.id === assignmentId)
    if (!item) {
      pendingToggles.delete(assignmentId)
      return
    }

    // Optimistic
    const prevCompletedAt = item.completed_at
    const prevCompletedBy = item.completed_by_user_id
    item.completed_at = new Date().toISOString()
    item.completed_by_user_id = authStore.user?.id ?? null

    try {
      const updated = await repo.completeAssignment(householdId, assignmentId)
      // Server gewinnt
      const currentIdx = assignments.value.findIndex(a => a.id === assignmentId)
      if (currentIdx !== -1) assignments.value[currentIdx] = updated
    } catch (error) {
      // Rollback
      const currentItem = assignments.value.find(a => a.id === assignmentId)
      if (currentItem) {
        currentItem.completed_at = prevCompletedAt
        currentItem.completed_by_user_id = prevCompletedBy
      }
      throw error
    } finally {
      pendingToggles.delete(assignmentId)
    }
  }

  async function uncompleteAssignment(assignmentId: string) {
    if (pendingToggles.has(assignmentId)) return
    pendingToggles.add(assignmentId)

    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) {
      pendingToggles.delete(assignmentId)
      return
    }

    const item = assignments.value.find(a => a.id === assignmentId)
    if (!item) {
      pendingToggles.delete(assignmentId)
      return
    }

    // Optimistic
    const prevCompletedAt = item.completed_at
    const prevCompletedBy = item.completed_by_user_id
    item.completed_at = null
    item.completed_by_user_id = null

    try {
      const updated = await repo.uncompleteAssignment(householdId, assignmentId)
      const currentIdx = assignments.value.findIndex(a => a.id === assignmentId)
      if (currentIdx !== -1) assignments.value[currentIdx] = updated
    } catch (error) {
      const currentItem = assignments.value.find(a => a.id === assignmentId)
      if (currentItem) {
        currentItem.completed_at = prevCompletedAt
        currentItem.completed_by_user_id = prevCompletedBy
      }
      throw error
    } finally {
      pendingToggles.delete(assignmentId)
    }
  }

  async function reassignAssignment(assignmentId: string, assignedUserId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.reassignAssignment(householdId, assignmentId, assignedUserId)
    const idx = assignments.value.findIndex(a => a.id === assignmentId)
    if (idx !== -1) assignments.value[idx] = updated
  }

  // Socket-Handler — Idempotent (Server gewinnt)
  function handleChoreCreated(serverChore: ChoreInfo) {
    const idx = chores.value.findIndex(c => c.id === serverChore.id)
    if (idx !== -1) {
      chores.value[idx] = serverChore
    } else {
      chores.value.push(serverChore)
    }
  }

  function handleChoreUpdated(serverChore: ChoreInfo) {
    const idx = chores.value.findIndex(c => c.id === serverChore.id)
    if (idx !== -1) {
      chores.value[idx] = serverChore
    }
  }

  function handleChoreDeleted(data: { id: string }) {
    chores.value = chores.value.filter(c => c.id !== data.id)
    assignments.value = assignments.value.filter(a => a.chore_id !== data.id)
  }

  function handleAssignmentCreated(serverAssignment: ChoreAssignmentInfo) {
    const idx = assignments.value.findIndex(a => a.id === serverAssignment.id)
    if (idx !== -1) {
      assignments.value[idx] = serverAssignment
    } else {
      assignments.value.push(serverAssignment)
      // Sortierung nach due_date beibehalten
      assignments.value.sort((a, b) => a.due_date.localeCompare(b.due_date))
    }
  }

  function handleAssignmentUpdated(serverAssignment: ChoreAssignmentInfo) {
    const idx = assignments.value.findIndex(a => a.id === serverAssignment.id)
    if (idx !== -1) {
      assignments.value[idx] = serverAssignment
    }
  }

  return {
    // State
    chores,
    assignments,
    members,
    loading,
    // Actions
    fetchChores,
    fetchAssignments,
    fetchMembers,
    createChore,
    updateChore,
    removeChore,
    completeAssignment,
    uncompleteAssignment,
    reassignAssignment,
    // Socket-Handlers
    handleChoreCreated,
    handleChoreUpdated,
    handleChoreDeleted,
    handleAssignmentCreated,
    handleAssignmentUpdated,
  }
})
