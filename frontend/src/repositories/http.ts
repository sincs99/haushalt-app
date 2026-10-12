import type { AxiosRequestConfig } from 'axios'
import api from '../api/client'

/**
 * DELETE, bei dem 404 als Erfolg gilt: Das Element ist schon weg (z. B. hat ein anderes
 * Mitglied es gleichzeitig gelöscht). Ohne das würde der Store den optimistisch
 * entfernten Eintrag zurückholen — ein „Geist“, der sich nicht mehr löschen lässt
 * (CASA-45, races.test.ts R4).
 */
export async function deleteIdempotent(url: string, config?: AxiosRequestConfig): Promise<void> {
  try {
    await api.delete(url, config)
  } catch (error) {
    if ((error as { response?: { status?: number } })?.response?.status === 404) return
    throw error
  }
}
