import api from '../api/client'
import type { UnifiedTask, TodoItem } from '../types'

export interface TasksRepository {
  fetchTasks(householdId: string): Promise<UnifiedTask[]>
  claimTodo(householdId: string, todoId: string): Promise<TodoItem>
  completeChoreAssignment(householdId: string, assignmentId: string): Promise<void>
}

export function createOnlineTasksRepository(): TasksRepository {
  return {
    async fetchTasks(householdId) {
      const { data } = await api.get<UnifiedTask[]>(
        `/api/households/${householdId}/tasks`,
      )
      return data
    },
    async claimTodo(householdId, todoId) {
      const { data } = await api.post<TodoItem>(
        `/api/households/${householdId}/todos/${todoId}/claim`,
      )
      return data
    },
    async completeChoreAssignment(householdId, assignmentId) {
      await api.post(
        `/api/households/${householdId}/chores/assignments/${assignmentId}/complete`,
      )
    },
  }
}
