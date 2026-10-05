import api from '../api/client'
import type { DocumentCategory, DocumentItem, DocumentList, DocumentMeta, StorageUsage } from '../types'

export interface DocumentListQuery {
  category?: DocumentCategory | null
  q?: string
  limit?: number
  offset?: number
}

export interface DocumentsRepository {
  fetchPage(householdId: string, query: DocumentListQuery): Promise<DocumentList>
  fetchStorage(householdId: string): Promise<StorageUsage>
  upload(householdId: string, file: File, meta: Partial<DocumentMeta>): Promise<DocumentItem>
  update(householdId: string, documentId: string, data: Partial<DocumentMeta>): Promise<DocumentItem>
  remove(householdId: string, documentId: string): Promise<void>
}

export function createOnlineDocumentsRepository(): DocumentsRepository {
  return {
    async fetchPage(householdId, query) {
      const params: Record<string, string | number> = {
        limit: query.limit ?? 50,
        offset: query.offset ?? 0,
      }
      if (query.category) params.category = query.category
      if (query.q?.trim()) params.q = query.q.trim()

      const { data } = await api.get<DocumentList>(
        `/api/households/${householdId}/documents/`,
        { params },
      )
      return data
    },

    async fetchStorage(householdId) {
      const { data } = await api.get<StorageUsage>(
        `/api/households/${householdId}/documents/storage`,
      )
      return data
    },

    async upload(householdId, file, meta) {
      const formData = new FormData()
      formData.append('file', file)
      // Leere Felder weglassen — Backend nutzt Defaults (Titel = Dateiname)
      for (const [key, value] of Object.entries(meta)) {
        if (value !== null && value !== undefined && value !== '') {
          formData.append(key, String(value))
        }
      }
      const { data } = await api.post<DocumentItem>(
        `/api/households/${householdId}/documents/upload`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      return data
    },

    async update(householdId, documentId, payload) {
      const { data } = await api.patch<DocumentItem>(
        `/api/households/${householdId}/documents/${documentId}`,
        payload,
      )
      return data
    },

    async remove(householdId, documentId) {
      await api.delete(
        `/api/households/${householdId}/documents/${documentId}`,
      )
    },
  }
}
