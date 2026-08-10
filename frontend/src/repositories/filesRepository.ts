import api from '../api/client'
import type { StoredFile } from '../types'

export interface FilesRepository {
  uploadFile(householdId: string, file: File): Promise<StoredFile>
  fetchFileAsObjectUrl(householdId: string, fileId: string): Promise<string>
  deleteFile(householdId: string, fileId: string): Promise<void>
  revokeObjectUrl(url: string): void
}

export function createOnlineFilesRepository(): FilesRepository {
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
      const { data } = await api.get(
        `/api/households/${householdId}/files/${fileId}`,
        { responseType: 'blob' },
      )
      return URL.createObjectURL(data)
    },

    async deleteFile(householdId, fileId) {
      await api.delete(`/api/households/${householdId}/files/${fileId}`)
    },

    revokeObjectUrl(url) {
      URL.revokeObjectURL(url)
    },
  }
}
