import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineTasksRepository } from '../repositories/tasksRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type { UnifiedTask, HouseholdMemberInfo } from '../types'

export const useTasksStore = defineStore('tasks', () => {
  const repo = createOnlineTasksRepository()
  const householdRepo = createOnlineHouseholdsRepository()

  const items = ref<UnifiedTask[]>([])
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)

  async function fetchTasks() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      items.value = await repo.fetchTasks(householdId)
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

  async function claimTask(taskId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    await repo.claimTodo(householdId, taskId)
    // Refetch für konsistenten State
    await fetchTasks()
  }

  async function completeChoreAssignment(assignmentId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    await repo.completeChoreAssignment(householdId, assignmentId)
    await fetchTasks() // Refetch für konsistenten State
  }

  // Socket-Invalidierung: bei todo_* oder chore_assignment_* Events → refetch
  function invalidate() {
    fetchTasks()
  }

  return { items, members, loading, fetchTasks, fetchMembers, claimTask, completeChoreAssignment, invalidate }
})
