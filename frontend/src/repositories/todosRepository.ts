import api from '../api/client'
import type { TodoItem } from '../types'

export interface TodosRepository {
  fetchAll(
    householdId: string,
    params?: { include_done?: boolean; assigned_to_me?: boolean },
  ): Promise<TodoItem[]>
  create(
    householdId: string,
    data: {
      title: string
      description?: string
      assigned_to_user_id?: string
      due_date?: string
    },
  ): Promise<TodoItem>
  update(
    householdId: string,
    todoId: string,
    data: Partial<TodoItem>,
  ): Promise<TodoItem>
  remove(householdId: string, todoId: string): Promise<void>
}

export function createOnlineTodosRepository(): TodosRepository {
  return {
    async fetchAll(householdId, params) {
      const { data } = await api.get<TodoItem[]>(
        `/api/households/${householdId}/todos/`,
        {
          params: {
            include_done: params?.include_done ?? false,
            assigned_to_me: params?.assigned_to_me ?? false,
          },
        },
      )
      return data
    },

    async create(householdId, payload) {
      const { data } = await api.post<TodoItem>(
        `/api/households/${householdId}/todos/`,
        {
          title: payload.title,
          description: payload.description ?? null,
          assigned_to_user_id: payload.assigned_to_user_id ?? null,
          due_date: payload.due_date ?? null,
        },
      )
      return data
    },

    async update(householdId, todoId, payload) {
      const { data } = await api.patch<TodoItem>(
        `/api/households/${householdId}/todos/${todoId}`,
        payload,
      )
      return data
    },

    async remove(householdId, todoId) {
      await api.delete(
        `/api/households/${householdId}/todos/${todoId}`,
      )
    },
  }
}
