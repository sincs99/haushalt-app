import { scopeRepository, isScopeChanged, currentDataGeneration, assertDataGeneration } from '../services/sessionScope'
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineChoresRepository } from '../repositories/choresRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type { ChoreInfo, ChoreCreatePayload, ChoreUpdatePayload, ChoreAssignmentInfo, HouseholdMemberInfo } from '../types'
import { upsertVersioned } from '../utils/syncVersion'

export const useChoresStore = defineStore('chores', () => {
  const repo = scopeRepository(createOnlineChoresRepository())
  const householdRepo = scopeRepository(createOnlineHouseholdsRepository())

  // State
  const chores = ref<ChoreInfo[]>([])
  const assignments = ref<ChoreAssignmentInfo[]>([])
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)

  // Mutex für Toggle-Operationen (wie pendingToggles in todos.ts)
  const pendingToggles = new Set<string>()

  // Ämtli und Einträge laden parallel → `loading` erst false, wenn beide fertig sind
  let loadsInFlight = 0
  function resetPending() {
    pendingToggles.clear()
    loadsInFlight = 0
  }
  function startLoad() {
    loadsInFlight++
    loading.value = true
  }
  function endLoad() {
    loadsInFlight = Math.max(0, loadsInFlight - 1)
    loading.value = loadsInFlight > 0
  }

  // Actions
  async function fetchChores() {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    startLoad()
    try {
      const scopedResult = await repo.fetchChores(householdId)
      assertDataGeneration(actionGeneration)
      chores.value = scopedResult
    } finally {
      assertDataGeneration(actionGeneration)
      endLoad()
    }
  }

  async function fetchAssignments(params?: { from?: string; to?: string }) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    startLoad()
    try {
      const scopedResult = await repo.fetchAssignments(householdId, params)
      assertDataGeneration(actionGeneration)
      assignments.value = scopedResult
    } finally {
      assertDataGeneration(actionGeneration)
      endLoad()
    }
  }

  async function fetchMembers() {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const scopedResult = await householdRepo.fetchMembers(householdId)
    assertDataGeneration(actionGeneration)

    members.value = scopedResult
  }

  async function createChore(payload: ChoreCreatePayload) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const created = await repo.createChore(householdId, payload)
    // Dedupe: falls Socket schneller war
    assertDataGeneration(actionGeneration)
    const idx = chores.value.findIndex(c => c.id === created.id)
    if (idx === -1) {
      chores.value.push(created)
    } else {
      chores.value[idx] = created
    }
    return created
  }

  async function updateChore(choreId: string, payload: ChoreUpdatePayload) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.updateChore(householdId, choreId, payload)
    assertDataGeneration(actionGeneration)
    const idx = chores.value.findIndex(c => c.id === choreId)
    if (idx !== -1) {
      chores.value[idx] = updated
    }
    // Bei Schedule-Änderung: Assignments neu laden
    if (payload.recurrence || payload.weekday !== undefined || payload.day_of_month !== undefined) {
      await fetchAssignments()
      assertDataGeneration(actionGeneration)
    }
    return updated
  }

  async function removeChore(choreId: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic Delete
    const idx = chores.value.findIndex(c => c.id === choreId)
    const removed = idx !== -1 ? chores.value[idx] : null
    if (idx !== -1) chores.value.splice(idx, 1)
    // Auch zugehörige Assignments entfernen
    const removedAssignments = assignments.value.filter(a => a.chore_id === choreId)
    assignments.value = assignments.value.filter(a => a.chore_id !== choreId)

    try {
      await repo.removeChore(householdId, choreId)
      assertDataGeneration(actionGeneration)
    } catch (error) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(error)) throw error
      // Rollback
      if (removed && idx !== -1) chores.value.splice(idx, 0, removed)
      const restored = removedAssignments.filter(r => !assignments.value.some(a => a.id === r.id))
      if (restored.length > 0) {
        assignments.value = [...assignments.value, ...restored]
          .sort((a, b) => a.due_date.localeCompare(b.due_date))
      }
      throw error
    }
  }

  async function completeAssignment(assignmentId: string) {
    const actionGeneration = currentDataGeneration()
    if (pendingToggles.has(assignmentId)) return
    pendingToggles.add(assignmentId)

    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) {
      pendingToggles.delete(assignmentId)
      return
    }

    // Optimistic (nur falls lokal geladen — im Dashboard ist das oft nicht der Fall)
    const item = assignments.value.find(a => a.id === assignmentId)
    const prevCompletedAt = item?.completed_at ?? null
    const prevCompletedBy = item?.completed_by_user_id ?? null
    if (item) {
      item.completed_at = new Date().toISOString()
      item.completed_by_user_id = authStore.user?.id ?? null
    }

    try {
      const updated = await repo.completeAssignment(householdId, assignmentId)
      // Server gewinnt, ausser ein Socket-Event hat schon einen neueren Stand geliefert
      assertDataGeneration(actionGeneration)
      if (updated) upsertVersioned(assignments.value, updated, false)
    } catch (error) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(error)) throw error
      // Rollback
      const currentItem = assignments.value.find(a => a.id === assignmentId)
      if (currentItem && item) {
        currentItem.completed_at = prevCompletedAt
        currentItem.completed_by_user_id = prevCompletedBy
      }
      throw error
    } finally {
      assertDataGeneration(actionGeneration)
      pendingToggles.delete(assignmentId)
    }
  }

  async function uncompleteAssignment(assignmentId: string) {
    const actionGeneration = currentDataGeneration()
    if (pendingToggles.has(assignmentId)) return
    pendingToggles.add(assignmentId)

    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) {
      pendingToggles.delete(assignmentId)
      return
    }

    // Optimistic (nur falls lokal geladen)
    const item = assignments.value.find(a => a.id === assignmentId)
    const prevCompletedAt = item?.completed_at ?? null
    const prevCompletedBy = item?.completed_by_user_id ?? null
    if (item) {
      item.completed_at = null
      item.completed_by_user_id = null
    }

    try {
      const updated = await repo.uncompleteAssignment(householdId, assignmentId)
      assertDataGeneration(actionGeneration)
      if (updated) upsertVersioned(assignments.value, updated, false)
    } catch (error) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(error)) throw error
      const currentItem = assignments.value.find(a => a.id === assignmentId)
      if (currentItem && item) {
        currentItem.completed_at = prevCompletedAt
        currentItem.completed_by_user_id = prevCompletedBy
      }
      throw error
    } finally {
      assertDataGeneration(actionGeneration)
      pendingToggles.delete(assignmentId)
    }
  }

  async function reassignAssignment(assignmentId: string, assignedUserId: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.reassignAssignment(householdId, assignmentId, assignedUserId)
    assertDataGeneration(actionGeneration)
    upsertVersioned(assignments.value, updated, false)
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
    const isNew = !assignments.value.some(a => a.id === serverAssignment.id)
    upsertVersioned(assignments.value, serverAssignment, true)
    if (isNew) {
      // Sortierung nach due_date beibehalten
      assignments.value.sort((a, b) => a.due_date.localeCompare(b.due_date))
    }
  }

  function handleAssignmentUpdated(serverAssignment: ChoreAssignmentInfo) {
    // Veraltete Events (niedrigere version) werden verworfen
    upsertVersioned(assignments.value, serverAssignment, false)
  }

  return {
    resetPending,
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
