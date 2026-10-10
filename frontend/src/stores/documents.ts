import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineDocumentsRepository } from '../repositories/documentsRepository'
import { createOnlineFilesRepository } from '../repositories/filesRepository'
import { prepareImageForUpload } from '../utils/imageUpload'
import type { DocumentCategory, DocumentItem, DocumentMeta, StorageUsage } from '../types'
import { captureHousehold } from '../utils/householdGuard'

const PAGE_SIZE = 30
/** Max. Seiten pro Dokument, wie Backend (MAX_FILES_PER_DOCUMENT) */
export const MAX_DOCUMENT_FILES = 30

/** Fortschritt beim Hochladen mehrerer Seiten (1-basiert) */
export type UploadProgress = (current: number, total: number) => void

export const useDocumentsStore = defineStore('documents', () => {
  // Repository — einmal im Store-Setup erstellen
  const repo = createOnlineDocumentsRepository()
  const filesRepo = createOnlineFilesRepository()

  // State
  const items = ref<DocumentItem[]>([])
  const total = ref(0)
  const category = ref<DocumentCategory | null>(null)
  const query = ref('')
  const loading = ref(false)
  const loadingMore = ref(false)
  const storage = ref<StorageUsage | null>(null)

  // Zähler gegen veraltete Responses (Filter/Suche schneller gewechselt als API antwortet)
  let requestSeq = 0

  // Computed
  const hasMore = computed(() => items.value.length < total.value)

  function matchesFilter(doc: DocumentItem): boolean {
    if (category.value && doc.category !== category.value) return false
    const q = query.value.trim().toLowerCase()
    return !q || doc.title.toLowerCase().includes(q)
  }

  // Actions
  async function fetchDocuments() {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    const seq = ++requestSeq
    const inScope = captureHousehold(householdId)
    loading.value = true
    try {
      const page = await repo.fetchPage(householdId, {
        category: category.value,
        q: query.value,
        limit: PAGE_SIZE,
        offset: 0,
      })
      if (seq !== requestSeq || !inScope()) return
      items.value = page.items
      total.value = page.total
    } finally {
      if (seq === requestSeq) loading.value = false
    }
  }

  async function loadMore() {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId || loadingMore.value || !hasMore.value) return

    const seq = requestSeq
    const inScope = captureHousehold(householdId)
    loadingMore.value = true
    try {
      const page = await repo.fetchPage(householdId, {
        category: category.value,
        q: query.value,
        limit: PAGE_SIZE,
        offset: items.value.length,
      })
      if (seq !== requestSeq || !inScope()) return
      // Duplikate vermeiden (Socket-Events können Offsets verschieben)
      const known = new Set(items.value.map((i) => i.id))
      items.value.push(...page.items.filter((i) => !known.has(i.id)))
      total.value = page.total
    } finally {
      loadingMore.value = false
    }
  }

  async function fetchStorage() {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return
    const inScope = captureHousehold(householdId)
    const result = await repo.fetchStorage(householdId)
    if (inScope()) storage.value = result
  }

  async function setCategory(value: DocumentCategory | null) {
    category.value = value
    await fetchDocuments()
  }

  async function setQuery(value: string) {
    query.value = value
    await fetchDocuments()
  }

  /**
   * Lädt Seiten einzeln über /files hoch (je Request max. 10 MB) und gibt die
   * File-IDs zurück. Schlägt eine Seite fehl, werden die bereits hochgeladenen
   * wieder gelöscht (best-effort), damit keine verwaisten Dateien entstehen.
   */
  async function uploadFiles(householdId: string, files: File[], onProgress?: UploadProgress) {
    const ids: string[] = []
    try {
      for (const [index, file] of files.entries()) {
        onProgress?.(index + 1, files.length)
        // Fotos verkleinern (Handy-Kamera, HEIC); PDFs unverändert
        const upload = file.type.startsWith('image/') ? await prepareImageForUpload(file) : file
        ids.push((await filesRepo.uploadFile(householdId, upload)).id)
      }
      return ids
    } catch (error) {
      await discardFiles(householdId, ids)
      throw error
    }
  }

  async function discardFiles(householdId: string, fileIds: string[]) {
    await Promise.all(
      fileIds.map((id) => filesRepo.deleteFile(householdId, id).catch(() => {})),
    )
  }

  async function uploadDocument(files: File[], meta: DocumentMeta, onProgress?: UploadProgress) {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId || files.length === 0) return

    // Kein Optimistic Update: Upload kann am Server scheitern (Typ, Grösse, Quota)
    const fileIds = await uploadFiles(householdId, files, onProgress)
    let serverItem: DocumentItem
    try {
      serverItem = await repo.create(householdId, meta, fileIds)
    } catch (error) {
      await discardFiles(householdId, fileIds)
      throw error
    }
    handleDocumentCreated(serverItem)
    fetchStorage().catch(() => {})
    return serverItem
  }

  async function addPages(documentId: string, files: File[], onProgress?: UploadProgress) {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId || files.length === 0) return

    const fileIds = await uploadFiles(householdId, files, onProgress)
    try {
      handleDocumentUpdated(await repo.addFiles(householdId, documentId, fileIds))
    } catch (error) {
      await discardFiles(householdId, fileIds)
      throw error
    }
    fetchStorage().catch(() => {})
  }

  async function movePage(documentId: string, fileId: string, direction: -1 | 1) {
    const householdId = useAuthStore().currentHouseholdId
    const item = items.value.find((i) => i.id === documentId)
    if (!householdId || !item) return

    const idx = item.files.findIndex((f) => f.id === fileId)
    const target = idx + direction
    if (idx === -1 || target < 0 || target >= item.files.length) return

    // Optimistic: Seiten sofort tauschen, Rollback bei Fehler
    const snapshot = item.files
    const reordered = [...item.files]
    ;[reordered[idx], reordered[target]] = [reordered[target], reordered[idx]]
    item.files = reordered

    try {
      handleDocumentUpdated(
        await repo.reorderFiles(householdId, documentId, reordered.map((f) => f.id)),
      )
    } catch (error) {
      item.files = snapshot
      throw error
    }
  }

  async function removePage(documentId: string, fileId: string) {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    handleDocumentUpdated(await repo.removeFile(householdId, documentId, fileId))
    fetchStorage().catch(() => {})
  }

  async function updateDocument(documentId: string, data: Partial<DocumentMeta>) {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    const item = items.value.find((i) => i.id === documentId)
    if (!item) return

    // 1. Snapshot für Rollback
    const snapshot = { ...item }

    // 2. Optimistic: Sofort aktualisieren
    Object.assign(item, data)

    try {
      // 3. Server-Call — Server gewinnt
      handleDocumentUpdated(await repo.update(householdId, documentId, data))
    } catch (error) {
      // 4. Rollback auf Snapshot
      Object.assign(item, snapshot)
      throw error
    }
  }

  async function deleteDocument(documentId: string) {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    // 1. Snapshot für Rollback
    const itemIndex = items.value.findIndex((i) => i.id === documentId)
    if (itemIndex === -1) return
    const removedItem = items.value[itemIndex]

    // 2. Optimistic: Sofort entfernen
    items.value.splice(itemIndex, 1)
    total.value = Math.max(0, total.value - 1)

    try {
      // 3. Server-Call
      await repo.remove(householdId, documentId)
      fetchStorage().catch(() => {})
    } catch (error) {
      // 4. Rollback: Item wieder einfügen an gleicher Position
      items.value.splice(itemIndex, 0, removedItem)
      total.value += 1
      throw error
    }
  }

  // Socket-Handler — Idempotente Merges (Server gewinnt immer)
  function handleDocumentCreated(serverItem: DocumentItem) {
    const existingIdx = items.value.findIndex((i) => i.id === serverItem.id)
    if (existingIdx !== -1) {
      items.value[existingIdx] = serverItem
      return
    }
    if (!matchesFilter(serverItem)) return
    // Neueste zuerst (wie Backend-Sortierung)
    items.value.unshift(serverItem)
    total.value += 1
  }

  function handleDocumentUpdated(serverItem: DocumentItem) {
    const idx = items.value.findIndex((i) => i.id === serverItem.id)
    if (idx === -1) return
    if (matchesFilter(serverItem)) {
      items.value[idx] = serverItem
    } else {
      // Passt nach Kategorie-/Titeländerung nicht mehr zum aktiven Filter
      items.value.splice(idx, 1)
      total.value = Math.max(0, total.value - 1)
    }
  }

  function handleDocumentDeleted(data: { id: string }) {
    const before = items.value.length
    items.value = items.value.filter((i) => i.id !== data.id)
    if (items.value.length < before) {
      total.value = Math.max(0, total.value - 1)
    }
  }

  function reset() {
    requestSeq++
    items.value = []
    total.value = 0
    storage.value = null
  }

  return {
    // State
    items,
    total,
    category,
    query,
    loading,
    loadingMore,
    storage,
    // Computed
    hasMore,
    // Actions
    fetchDocuments,
    loadMore,
    fetchStorage,
    setCategory,
    setQuery,
    uploadDocument,
    addPages,
    movePage,
    removePage,
    updateDocument,
    deleteDocument,
    reset,
    // Socket-Handlers
    handleDocumentCreated,
    handleDocumentUpdated,
    handleDocumentDeleted,
  }
})
