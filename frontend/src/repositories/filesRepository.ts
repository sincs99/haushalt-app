import api from '../api/client'
import { deleteIdempotent } from './http'
import type { StoredFile } from '../types'

export interface FilesRepository {
  uploadFile(householdId: string, file: File): Promise<StoredFile>
  fetchFileAsObjectUrl(householdId: string, fileId: string): Promise<string>
  fetchFileBlob(householdId: string, fileId: string): Promise<Blob>
  deleteFile(householdId: string, fileId: string): Promise<void>
  revokeObjectUrl(url: string): void
}

export function createOnlineFilesRepository(): FilesRepository {
  async function fetchFileBlob(householdId: string, fileId: string): Promise<Blob> {
    const { data } = await api.get<Blob>(
      `/api/households/${householdId}/files/${fileId}`,
      { responseType: 'blob' },
    )
    return data
  }

  return {
    async uploadFile(householdId, file) {
      const formData = new FormData()
      formData.append('file', file)
      const { data } = await api.post<StoredFile>(
        `/api/households/${householdId}/files/`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      return data
    },

    async fetchFileAsObjectUrl(householdId, fileId) {
      // WICHTIG: <img src> kann keine JWT-Header senden!
      // Deshalb laden wir als Blob und nutzen createObjectURL
      return URL.createObjectURL(await fetchFileBlob(householdId, fileId))
    },

    fetchFileBlob,

    async deleteFile(householdId, fileId) {
      await deleteIdempotent(`/api/households/${householdId}/files/${fileId}`)
    },

    revokeObjectUrl(url) {
      URL.revokeObjectURL(url)
    },
  }
}
