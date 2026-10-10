import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineChoresRepository } from '../repositories/choresRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type { ChoreInfo, ChoreCreatePayload, ChoreUpdatePayload, ChoreAssignmentInfo, HouseholdMemberInfo } from '../types'
import { upsertVersioned } from '../utils/syncVersion'
import { createRequestGuard } from '../utils/householdGuard'

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
  // Verspätete Antworten eines anderen Haushalts/einer alten Sitzung verwerfen (CASA-12)
  const captureRequest = createRequestGuard()

  // Ämtli und Einträge laden parallel → `loading` erst false, wenn beide fertig sind
  let loadsInFlight = 0
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
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const active = captureRequest(householdId, 'chores')
    startLoad()
    try {
      const result = await repo.fetchChores(householdId)
      if (active()) chores.value = result
    } finally {
      endLoad()
    }
  }

  async function fetchAssignments(params?: { from?: string; to?: string }) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const active = captureRequest(householdId, 'assignments')
    startLoad()
    try {
      const result = await repo.fetchAssignments(householdId, params)
      if (active()) assignments.value = result
    } finally {
      endLoad()
    }
  }

  async function fetchMembers() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'members')

    const result = await householdRepo.fetchMembers(householdId)
    if (active()) members.value = result
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

    const idx = chores.value.findIndex(c => c.id === choreId)
    const previous = idx !== -1 ? { ...chores.value[idx] } : null
    const updated = await repo.updateChore(householdId, choreId, payload)
    if (idx !== -1) {
      chores.value[idx] = updated
    }
    // Zeitplan geändert, pausiert oder reaktiviert: der Server hat künftige Einträge
    // gelöscht/neu angelegt → Assignments neu laden. Das UI sendet immer alle Felder,
    // deshalb zählt nur eine echte Wertänderung.
    const changed = (key: 'recurrence' | 'weekday' | 'day_of_month' | 'active') =>
      payload[key] !== undefined && (!previous || previous[key] !== payload[key])
    if (changed('recurrence') || changed('weekday') || changed('day_of_month') || changed('active')) {
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
    const removedAssignments = assignments.value.filter(a => a.chore_id === choreId)
    assignments.value = assignments.value.filter(a => a.chore_id !== choreId)

    try {
      await repo.removeChore(householdId, choreId)
    } catch (error) {
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
      if (updated) upsertVersioned(assignments.value, updated, false)
    } catch (error) {
      // Rollback
      const currentItem = assignments.value.find(a => a.id === assignmentId)
      if (currentItem && item) {
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
      if (updated) upsertVersioned(assignments.value, updated, false)
    } catch (error) {
      const currentItem = assignments.value.find(a => a.id === assignmentId)
      if (currentItem && item) {
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

  /** Zeitplanänderung/Pause auf einem anderen Gerät: diese Einträge gibt es nicht mehr */
  function handleAssignmentsDeleted(data: { chore_id: string; ids: string[] }) {
    const gone = new Set(data.ids)
    assignments.value = assignments.value.filter(a => !gone.has(a.id))
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
    handleAssignmentsDeleted,
  }
})
