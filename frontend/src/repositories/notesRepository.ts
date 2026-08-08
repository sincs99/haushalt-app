import api from '../api/client'
import type { NoteItem } from '../types'

export interface NotesRepository {
  fetchAll(householdId: string): Promise<NoteItem[]>
  create(
    householdId: string,
    data: {
      title: string
      body?: string
      tag?: string
      pinned?: boolean
    },
  ): Promise<NoteItem>
  update(
    householdId: string,
    noteId: string,
    data: Partial<NoteItem>,
  ): Promise<NoteItem>
  remove(householdId: string, noteId: string): Promise<void>
}

export function createOnlineNotesRepository(): NotesRepository {
  return {
    async fetchAll(householdId) {
      const { data } = await api.get<NoteItem[]>(
        `/api/households/${householdId}/notes/`,
      )
      return data
    },

    async create(householdId, payload) {
      const { data } = await api.post<NoteItem>(
        `/api/households/${householdId}/notes/`,
        {
          title: payload.title,
          body: payload.body ?? '',
          tag: payload.tag ?? null,
          pinned: payload.pinned ?? false,
        },
      )
      return data
    },

    async update(householdId, noteId, payload) {
      const { data } = await api.patch<NoteItem>(
        `/api/households/${householdId}/notes/${noteId}`,
        payload,
      )
      return data
    },

    async remove(householdId, noteId) {
      await api.delete(
        `/api/households/${householdId}/notes/${noteId}`,
      )
    },
  }
}
