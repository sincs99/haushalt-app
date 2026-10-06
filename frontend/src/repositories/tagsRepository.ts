import api from '../api/client'
import type {
  TagCreatePayload,
  TagExecuteResult,
  TagInfo,
  TagResolveResult,
  TagTargetType,
} from '../types'

export interface TagsRepository {
  fetchAll(householdId: string): Promise<TagInfo[]>
  fetchTargets(householdId: string): Promise<TagTargetType[]>
  create(householdId: string, payload: TagCreatePayload): Promise<TagInfo>
  update(
    householdId: string,
    tagId: string,
    payload: Partial<Pick<TagInfo, 'label' | 'enabled' | 'target_type' | 'target_id' | 'action'>>,
  ): Promise<TagInfo>
  regenerateToken(householdId: string, tagId: string): Promise<TagInfo>
  remove(householdId: string, tagId: string): Promise<void>
  /** Was würde der Tag tun? Ändert nichts (ausser Nutzungszähler bei *.open). */
  resolve(token: string): Promise<TagResolveResult>
  execute(token: string, params?: { slot?: 'morning' | 'evening' }): Promise<TagExecuteResult>
}

export function createOnlineTagsRepository(): TagsRepository {
  const base = (householdId: string) => `/api/households/${householdId}/tags/`

  return {
    async fetchAll(householdId) {
      const { data } = await api.get<TagInfo[]>(base(householdId))
      return data
    },

    async fetchTargets(householdId) {
      const { data } = await api.get<TagTargetType[]>(`${base(householdId)}targets`)
      return data
    },

    async create(householdId, payload) {
      const { data } = await api.post<TagInfo>(base(householdId), payload)
      return data
    },

    async update(householdId, tagId, payload) {
      const { data } = await api.patch<TagInfo>(`${base(householdId)}${tagId}`, payload)
      return data
    },

    async regenerateToken(householdId, tagId) {
      const { data } = await api.post<TagInfo>(`${base(householdId)}${tagId}/regenerate-token`)
      return data
    },

    async remove(householdId, tagId) {
      await api.delete(`${base(householdId)}${tagId}`)
    },

    async resolve(token) {
      const { data } = await api.post<TagResolveResult>(
        `/api/tags/resolve/${encodeURIComponent(token)}`,
      )
      return data
    },

    async execute(token, params) {
      const { data } = await api.post<TagExecuteResult>(
        `/api/tags/${encodeURIComponent(token)}/execute`,
        params ?? {},
      )
      return data
    },
  }
}
