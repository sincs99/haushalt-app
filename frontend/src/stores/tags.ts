import { scopeRepository, isScopeChanged, currentDataGeneration, assertDataGeneration } from '../services/sessionScope'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineTagsRepository } from '../repositories/tagsRepository'
import type {
  TagCreatePayload,
  TagExecuteParams,
  TagExecuteResult,
  TagInfo,
  TagResolveResult,
  TagTargetType,
} from '../types'
import { createRequestGuard } from '../utils/householdGuard'

export const useTagsStore = defineStore('tags', () => {
  const repo = scopeRepository(createOnlineTagsRepository())

  // State
  const items = ref<TagInfo[]>([])
  const targets = ref<TagTargetType[]>([])
  const loading = ref(false)
  // Verspätete Antworten eines anderen Haushalts/einer alten Sitzung verwerfen (CASA-12)
  const captureRequest = createRequestGuard()

  // Computed
  const sortedTags = computed(() =>
    [...items.value].sort((a, b) => a.label.localeCompare(b.label)),
  )

  function currentHouseholdId(): string | null {
    return useAuthStore().currentHouseholdId
  }

  function upsert(tag: TagInfo) {
    const idx = items.value.findIndex((t) => t.id === tag.id)
    if (idx === -1) items.value.push(tag)
    else items.value[idx] = tag
  }

  // Actions
  async function fetchTags() {
    const actionGeneration = currentDataGeneration()
    const householdId = currentHouseholdId()
    if (!householdId) return
    const active = captureRequest(householdId, 'tags')
    loading.value = true
    try {
      const result = await repo.fetchAll(householdId)
      if (active()) items.value = result
    } finally {
      if (active.latest()) loading.value = false
    }
  }

  async function fetchTargets() {
    const actionGeneration = currentDataGeneration()
    const householdId = currentHouseholdId()
    if (!householdId) return
    const active = captureRequest(householdId, 'targets')
    const result = await repo.fetchTargets(householdId)
    if (active()) targets.value = result
  }

  async function createTag(payload: TagCreatePayload): Promise<TagInfo | undefined> {
    const actionGeneration = currentDataGeneration()
    const householdId = currentHouseholdId()
    if (!householdId) return
    // Kein Optimistic Create: der Token kommt vom Server
    const tag = await repo.create(householdId, payload)
    assertDataGeneration(actionGeneration)
    upsert(tag)
    return tag
  }

  async function updateTag(
    tagId: string,
    payload: Partial<Pick<TagInfo, 'label' | 'enabled' | 'target_type' | 'target_id' | 'action'>>,
  ) {
    const actionGeneration = currentDataGeneration()
    const householdId = currentHouseholdId()
    if (!householdId) return
    const item = items.value.find((t) => t.id === tagId)
    if (!item) return

    const snapshot = { ...item }
    // Optimistic nur für einfache Felder; Ziel-Wechsel liefert target_name vom Server
    if (payload.label !== undefined) item.label = payload.label
    if (payload.enabled !== undefined) item.enabled = payload.enabled
    try {
      const updated = await repo.update(householdId, tagId, payload)
      assertDataGeneration(actionGeneration)
      upsert(updated)
    } catch (error) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(error)) throw error
      const current = items.value.find((t) => t.id === tagId)
      if (current) Object.assign(current, snapshot)
      throw error
    }
  }

  async function setEnabled(tagId: string, enabled: boolean) {
    const actionGeneration = currentDataGeneration()
    await updateTag(tagId, { enabled })
    assertDataGeneration(actionGeneration)
  }

  async function regenerateToken(tagId: string): Promise<TagInfo | undefined> {
    const actionGeneration = currentDataGeneration()
    const householdId = currentHouseholdId()
    if (!householdId) return
    const tag = await repo.regenerateToken(householdId, tagId)
    assertDataGeneration(actionGeneration)
    upsert(tag)
    return tag
  }

  async function deleteTag(tagId: string) {
    const actionGeneration = currentDataGeneration()
    const householdId = currentHouseholdId()
    if (!householdId) return
    const idx = items.value.findIndex((t) => t.id === tagId)
    if (idx === -1) return
    const removed = items.value[idx]
    items.value.splice(idx, 1)
    try {
      await repo.remove(householdId, tagId)
      assertDataGeneration(actionGeneration)
    } catch (error) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(error)) throw error
      items.value.splice(Math.min(idx, items.value.length), 0, removed)
      throw error
    }
  }

  // Scan (/t/:token) — haushaltsunabhängig, der Server kennt den Tag-Haushalt
  function resolveToken(token: string): Promise<TagResolveResult> {
    return repo.resolve(token)
  }

  function executeToken(token: string, params?: TagExecuteParams): Promise<TagExecuteResult> {
    return repo.execute(token, params)
  }

  // Socket-Handler — Server gewinnt; Events anderer Haushalte ignorieren
  function handleTagCreated(tag: TagInfo) {
    if (tag.household_id !== currentHouseholdId()) return
    upsert(tag)
  }

  function handleTagUpdated(tag: TagInfo) {
    if (tag.household_id !== currentHouseholdId()) return
    upsert(tag)
  }

  function handleTagDeleted(data: { id: string }) {
    items.value = items.value.filter((t) => t.id !== data.id)
  }

  function $reset() {
    items.value = []
    targets.value = []
    loading.value = false
  }

  return {
    items,
    targets,
    loading,
    sortedTags,
    fetchTags,
    fetchTargets,
    createTag,
    updateTag,
    setEnabled,
    regenerateToken,
    deleteTag,
    resolveToken,
    executeToken,
    handleTagCreated,
    handleTagUpdated,
    handleTagDeleted,
    $reset,
  }
})
