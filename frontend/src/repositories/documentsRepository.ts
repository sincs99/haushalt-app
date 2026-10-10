import api from '../api/client'
import { deleteIdempotent } from './http'
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
  create(householdId: string, meta: DocumentMeta, fileIds: string[]): Promise<DocumentItem>
  update(householdId: string, documentId: string, data: Partial<DocumentMeta>): Promise<DocumentItem>
  addFiles(householdId: string, documentId: string, fileIds: string[]): Promise<DocumentItem>
  reorderFiles(householdId: string, documentId: string, fileIds: string[]): Promise<DocumentItem>
  removeFile(householdId: string, documentId: string, fileId: string): Promise<DocumentItem>
  remove(householdId: string, documentId: string): Promise<void>
}

export function createOnlineDocumentsRepository(): DocumentsRepository {
  const base = (householdId: string) => `/api/households/${householdId}/documents`

  return {
    async fetchPage(householdId, query) {
      const params: Record<string, string | number> = {
        limit: query.limit ?? 50,
        offset: query.offset ?? 0,
      }
      if (query.category) params.category = query.category
      if (query.q?.trim()) params.q = query.q.trim()

      const { data } = await api.get<DocumentList>(`${base(householdId)}/`, { params })
      return data
    },

    async fetchStorage(householdId) {
      const { data } = await api.get<StorageUsage>(`${base(householdId)}/storage`)
      return data
    },

    async create(householdId, meta, fileIds) {
      const { data } = await api.post<DocumentItem>(`${base(householdId)}/`, {
        ...meta,
        file_ids: fileIds,
      })
      return data
    },

    async update(householdId, documentId, payload) {
      const { data } = await api.patch<DocumentItem>(`${base(householdId)}/${documentId}`, payload)
      return data
    },

    async addFiles(householdId, documentId, fileIds) {
      const { data } = await api.post<DocumentItem>(
        `${base(householdId)}/${documentId}/files`,
        { file_ids: fileIds },
      )
      return data
    },

    async reorderFiles(householdId, documentId, fileIds) {
      const { data } = await api.put<DocumentItem>(
        `${base(householdId)}/${documentId}/files/order`,
        { file_ids: fileIds },
      )
      return data
    },

    async removeFile(householdId, documentId, fileId) {
      const { data } = await api.delete<DocumentItem>(
        `${base(householdId)}/${documentId}/files/${fileId}`,
      )
      return data
    },

    async remove(householdId, documentId) {
      await deleteIdempotent(`${base(householdId)}/${documentId}`)
    },
  }
}
