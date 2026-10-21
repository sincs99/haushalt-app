import { scopeRepository, currentDataGeneration, assertDataGeneration } from '../services/sessionScope'
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineTasksRepository } from '../repositories/tasksRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type { UnifiedTask, HouseholdMemberInfo } from '../types'

export const useTasksStore = defineStore('tasks', () => {
  const repo = scopeRepository(createOnlineTasksRepository())
  const householdRepo = scopeRepository(createOnlineHouseholdsRepository())

  const items = ref<UnifiedTask[]>([])
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)

  async function fetchTasks() {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      const scopedResult = await repo.fetchTasks(householdId)
      assertDataGeneration(actionGeneration)
      items.value = scopedResult
    } finally {
      assertDataGeneration(actionGeneration)
      loading.value = false
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

  async function claimTask(taskId: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    await repo.claimTodo(householdId, taskId)
    // Refetch für konsistenten State
    assertDataGeneration(actionGeneration)
    await fetchTasks()
    assertDataGeneration(actionGeneration)
  }

  async function completeChoreAssignment(assignmentId: string) {
    const actionGeneration = currentDataGeneration()
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    await repo.completeChoreAssignment(householdId, assignmentId)
    assertDataGeneration(actionGeneration)
    await fetchTasks() // Refetch für konsistenten State
    assertDataGeneration(actionGeneration)
  }

  // Socket-Invalidierung: bei todo_* oder chore_assignment_* Events → refetch
  function invalidate() {
    // Ungewartet aufgerufen → Fehler hier abfangen (kein Unhandled Rejection)
    fetchTasks().catch((e) => console.error('Failed to refetch tasks:', e))
  }

  /** Haushaltswechsel: Daten gehören zum alten Haushalt. */
  function reset() {
    loading.value = false
    items.value = []
    members.value = []
  }

  return { items, members, loading, fetchTasks, fetchMembers, claimTask, completeChoreAssignment, invalidate, reset }
})
