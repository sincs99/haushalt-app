import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineNotesRepository } from '../repositories/notesRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type { NoteItem, HouseholdMemberInfo } from '../types'

export const useNotesStore = defineStore('notes', () => {
  // Repositories — einmal im Store-Setup erstellen
  const repo = createOnlineNotesRepository()
  const householdRepo = createOnlineHouseholdsRepository()

  // State
  const items = ref<NoteItem[]>([])
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)

  // Interner State für Race-Condition-Schutz
  const pendingTempIds = new Set<string>()

  // Computed
  const pinnedNotes = computed(() =>
    items.value
      .filter((n) => n.pinned)
      .sort((a, b) => b.created_at.localeCompare(a.created_at)),
  )

  const unpinnedNotes = computed(() =>
    items.value
      .filter((n) => !n.pinned)
      .sort((a, b) => b.created_at.localeCompare(a.created_at)),
  )

  // Actions
  async function fetchNotes() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      items.value = await repo.fetchAll(householdId)
    } finally {
      loading.value = false
    }
  }

  async function fetchMembers() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    members.value = await householdRepo.fetchMembers(householdId)
  }

  async function addNote(title: string, body?: string, tag?: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // 1. Optimistic: Sofort lokalen Temp-Eintrag erzeugen
    const tempId = crypto.randomUUID()
    const tempItem: NoteItem = {
      id: tempId,
      household_id: householdId,
      title,
      body: body ?? '',
      tag: tag ?? null,
      pinned: false,
      created_by_user_id: authStore.user?.id ?? null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    }
    items.value.push(tempItem)
    pendingTempIds.add(tempId)

    try {
      // 2. Server-Call via Repository
      const serverItem = await repo.create(householdId, {
        title,
        body,
        tag,
      })
      pendingTempIds.delete(tempId)

      // 3. Defensive Duplikat-Prüfung: Socket könnte schneller gewesen sein
      const serverIdx = items.value.findIndex((i) => i.id === serverItem.id)
      const tempIdx = items.value.findIndex((i) => i.id === tempId)

      if (serverIdx !== -1 && tempIdx !== -1) {
        // Socket war schneller → Server-Item existiert bereits → Temp-Item entfernen
        items.value.splice(tempIdx, 1)
      } else if (tempIdx !== -1) {
        // Normaler Fall → Temp-Item durch Server-Item ersetzen
        items.value[tempIdx] = serverItem
      }
    } catch (error) {
      pendingTempIds.delete(tempId)
      // 4. Rollback bei Fehler
      items.value = items.value.filter((i) => i.id !== tempId)
      throw error
    }
  }

  async function updateNote(noteId: string, data: Partial<NoteItem>) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const item = items.value.find((i) => i.id === noteId)
    if (!item) return

    // 1. Snapshot für Rollback
    const snapshot = { ...item }

    // 2. Optimistic: Sofort aktualisieren
    Object.assign(item, data)

    try {
      // 3. Server-Call
      await repo.update(householdId, noteId, data)
    } catch (error) {
      // 4. Rollback auf Snapshot
      Object.assign(item, snapshot)
      throw error
    }
  }

  async function togglePin(noteId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const item = items.value.find((i) => i.id === noteId)
    if (!item) return

    // 1. Optimistic Toggle
    const previousPinned = item.pinned
    item.pinned = !item.pinned

    try {
      // 2. Server-Call
      await repo.update(householdId, noteId, { pinned: item.pinned })
    } catch (error) {
      // 3. Rollback
      const currentItem = items.value.find((i) => i.id === noteId)
      if (currentItem) {
        currentItem.pinned = previousPinned
      }
      throw error
    }
  }

  async function deleteNote(noteId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // 1. Snapshot für Rollback
    const itemIndex = items.value.findIndex((i) => i.id === noteId)
    if (itemIndex === -1) return
    const removedItem = items.value[itemIndex]

    // 2. Optimistic: Sofort entfernen
    items.value.splice(itemIndex, 1)

    try {
      // 3. Server-Call
      await repo.remove(householdId, noteId)
    } catch (error) {
      // 4. Rollback: Item wieder einfügen an gleicher Position
      items.value.splice(itemIndex, 0, removedItem)
      throw error
    }
  }

  // Socket-Handler — Idempotente Merges (Server gewinnt immer)
  function handleNoteCreated(serverItem: NoteItem) {
    const existingIdx = items.value.findIndex((i) => i.id === serverItem.id)
    if (existingIdx !== -1) {
      // Server-Item existiert bereits (Socket war schneller als REST) → merge
      items.value[existingIdx] = serverItem
    } else {
      // Neues Item — entweder von anderem User, oder eigenes nach REST-Response
      // pendingTempIds enthält lokale UUIDs, serverItem.id ist Server-UUID → nie gleich
      items.value.push(serverItem)
    }
  }

  function handleNoteUpdated(serverItem: NoteItem) {
    const idx = items.value.findIndex((i) => i.id === serverItem.id)
    if (idx !== -1) {
      items.value[idx] = serverItem // Server gewinnt immer
    }
  }

  function handleNoteDeleted(data: { id: string }) {
    items.value = items.value.filter((i) => i.id !== data.id)
  }

  return {
    // State
    items,
    members,
    loading,
    // Computed
    pinnedNotes,
    unpinnedNotes,
    // Actions
    fetchNotes,
    fetchMembers,
    addNote,
    updateNote,
    togglePin,
    deleteNote,
    // Socket-Handlers
    handleNoteCreated,
    handleNoteUpdated,
    handleNoteDeleted,
  }
})
