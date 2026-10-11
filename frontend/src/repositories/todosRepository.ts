import api from '../api/client'
import { deleteIdempotent } from './http'
import type { TodoItem, TodoReminder } from '../types'

export interface TodosRepository {
  fetchAll(
    householdId: string,
    params?: { include_done?: boolean; assigned_to_me?: boolean },
  ): Promise<TodoItem[]>
  create(
    householdId: string,
    data: {
      id?: string
      title: string
      description?: string
      /** Zuständige; leer = offen für alle */
      assignee_ids?: string[]
      due_date?: string
      tags?: string[]
    },
  ): Promise<TodoItem>
  update(
    householdId: string,
    todoId: string,
    data: Partial<TodoItem>,
  ): Promise<TodoItem>
  remove(householdId: string, todoId: string): Promise<void>
  /** "Ich übernehme": mich zu den Zuständigen hinzufügen (idempotent) */
  claim(householdId: string, todoId: string): Promise<TodoItem>
  addReminder(householdId: string, todoId: string, remindAt: string): Promise<TodoReminder>
  deleteReminder(householdId: string, todoId: string, reminderId: string): Promise<void>
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
          // Client-generierte ID: wiederholter Create liefert dasselbe Todo statt Duplikat
          ...(payload.id ? { id: payload.id } : {}),
          title: payload.title,
          description: payload.description ?? null,
          assignee_ids: payload.assignee_ids ?? [],
          due_date: payload.due_date ?? null,
          tags: payload.tags ?? [],
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
      await deleteIdempotent(
        `/api/households/${householdId}/todos/${todoId}`,
      )
    },

    async claim(householdId, todoId) {
      const { data } = await api.post<TodoItem>(
        `/api/households/${householdId}/todos/${todoId}/claim`,
      )
      return data
    },

    async addReminder(householdId, todoId, remindAt) {
      const { data } = await api.post<TodoReminder>(
        `/api/households/${householdId}/todos/${todoId}/reminders/`,
        { remind_at: remindAt },
      )
      return data
    },

    async deleteReminder(householdId, todoId, reminderId) {
      await deleteIdempotent(
        `/api/households/${householdId}/todos/${todoId}/reminders/${reminderId}`,
      )
    },
  }
}
