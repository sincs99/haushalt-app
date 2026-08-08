import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineShoppingRepository } from '../repositories/shoppingRepository'
import type { ShoppingItem, ShoppingList, ShoppingListUpdatePayload } from '../types'

// ── localStorage-Persistenz für aktive Liste ──

function getStoredActiveListId(householdId: string): string | null {
  return localStorage.getItem(`shopping_activeList_${householdId}`)
}

function storeActiveListId(householdId: string, listId: string) {
  localStorage.setItem(`shopping_activeList_${householdId}`, listId)
}

export const useShoppingStore = defineStore('shopping', () => {
  // Repository — einmal im Store-Setup erstellen
  const repo = createOnlineShoppingRepository()

  // State
  const items = ref<ShoppingItem[]>([])
  const lists = ref<ShoppingList[]>([])
  const loading = ref(false)
  const activeListId = ref<string | null>(null)

  // Interner State für Race-Condition-Schutz
  const pendingTempIds = new Set<string>()
  const pendingToggles = new Set<string>()

  // ── Computed ──

  const activeListItems = computed(() =>
    items.value.filter(i => i.list_id === activeListId.value),
  )

  // ── List Actions ──

  async function fetchLists() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    lists.value = await repo.fetchLists(householdId)

    // Aktive Liste aus localStorage oder erste Liste
    const stored = getStoredActiveListId(householdId)
    if (stored && lists.value.some(l => l.id === stored)) {
      activeListId.value = stored
    } else if (lists.value.length > 0) {
      activeListId.value = lists.value[0].id
      storeActiveListId(householdId, lists.value[0].id)
    }
  }

  function setActiveList(listId: string) {
    const authStore = useAuthStore()
    activeListId.value = listId
    if (authStore.currentHouseholdId) {
      storeActiveListId(authStore.currentHouseholdId, listId)
    }
  }

  async function createList(name: string, icon?: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const newList = await repo.createList(householdId, { name, icon })
    lists.value.push(newList)
    lists.value.sort((a, b) => a.position - b.position)
  }

  async function updateList(listId: string, data: ShoppingListUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.updateList(householdId, listId, data)
    const idx = lists.value.findIndex(l => l.id === listId)
    if (idx !== -1) {
      lists.value[idx] = updated
    }
  }

  async function deleteList(listId: string, force = false) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    await repo.deleteList(householdId, listId, force)
    lists.value = lists.value.filter(l => l.id !== listId)

    // Falls aktive Liste gelöscht wurde, erste verbleibende wählen
    if (activeListId.value === listId && lists.value.length > 0) {
      setActiveList(lists.value[0].id)
    } else if (lists.value.length === 0) {
      activeListId.value = null
    }
  }

  // ── Item Actions ──

  async function fetchItems() {
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

  async function addItem(name: string, quantity?: string, category?: string, store?: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    if (!activeListId.value) return

    // 1. Optimistic: Sofort lokalen Temp-Eintrag erzeugen
    const tempId = crypto.randomUUID()
    const tempItem: ShoppingItem = {
      id: tempId,
      household_id: householdId,
      list_id: activeListId.value,
      name,
      quantity: quantity ?? null,
      category: category ?? null,
      is_checked: false,
      added_by_user_id: authStore.user?.id ?? null,
      created_at: new Date().toISOString(),
      checked_at: null,
      store: store ?? null,
      assigned_to_user_id: null,
    }
    items.value.push(tempItem)
    pendingTempIds.add(tempId)

    try {
      // 2. Server-Call via Repository
      const serverItem = await repo.create(householdId, {
        name,
        list_id: activeListId.value,
        quantity,
        category,
        store,
      })
      pendingTempIds.delete(tempId)

      // 3. Defensive Duplikat-Prüfung: Socket könnte schneller gewesen sein
      const serverIdx = items.value.findIndex(i => i.id === serverItem.id)
      const tempIdx = items.value.findIndex(i => i.id === tempId)

      if (serverIdx !== -1 && tempIdx !== -1) {
        // Socket war schneller → Server-Item existiert bereits → Temp-Item entfernen
        items.value.splice(tempIdx, 1)
      } else if (tempIdx !== -1) {
        // Normaler Fall → Temp-Item durch Server-Item ersetzen
        items.value[tempIdx] = serverItem
      }
      // Falls weder server noch temp gefunden → nichts tun (edge case, harmlos)
    } catch (error) {
      pendingTempIds.delete(tempId)
      // 4. Rollback bei Fehler
      items.value = items.value.filter(i => i.id !== tempId)
      throw error
    }
  }

  async function toggleChecked(itemId: string) {
    if (pendingToggles.has(itemId)) return // Bereits in Flight → ignorieren
    pendingToggles.add(itemId)

    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) {
      pendingToggles.delete(itemId)
      return
    }

    const item = items.value.find(i => i.id === itemId)
    if (!item) {
      pendingToggles.delete(itemId)
      return
    }

    // 1. Optimistic Toggle
    const previousChecked = item.is_checked
    const previousCheckedAt = item.checked_at
    item.is_checked = !item.is_checked
    item.checked_at = item.is_checked ? new Date().toISOString() : null

    try {
      // 2. Server-Call
      await repo.update(householdId, itemId, { is_checked: item.is_checked })
    } catch (error) {
      // 3. Rollback — frisch nachschlagen, da Socket-Events das Objekt ersetzt haben könnten
      const currentItem = items.value.find(i => i.id === itemId)
      if (currentItem) {
        currentItem.is_checked = previousChecked
        currentItem.checked_at = previousCheckedAt
      }
      throw error
    } finally {
      pendingToggles.delete(itemId)
    }
  }

  async function toggleAssigned(itemId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const item = items.value.find(i => i.id === itemId)
    if (!item) return

    const newValue = item.assigned_to_user_id === authStore.user?.id
      ? null
      : authStore.user?.id ?? null

    // Optimistic Update
    const prev = item.assigned_to_user_id
    item.assigned_to_user_id = newValue

    try {
      await repo.update(householdId, itemId, { assigned_to_user_id: newValue })
    } catch (error) {
      const current = items.value.find(i => i.id === itemId)
      if (current) current.assigned_to_user_id = prev
      throw error
    }
  }

  async function deleteItem(itemId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // 1. Snapshot für Rollback
    const itemIndex = items.value.findIndex(i => i.id === itemId)
    if (itemIndex === -1) return
    const removedItem = items.value[itemIndex]

    // 2. Optimistic: Sofort entfernen
    items.value.splice(itemIndex, 1)

    try {
      // 3. Server-Call
      await repo.remove(householdId, itemId)
    } catch (error) {
      // 4. Rollback: Item wieder einfügen an gleicher Position
      items.value.splice(itemIndex, 0, removedItem)
      throw error
    }
  }

  // ── Socket-Handler: Listen ──

  function handleListCreated(serverList: ShoppingList) {
    const idx = lists.value.findIndex(l => l.id === serverList.id)
    if (idx !== -1) {
      lists.value[idx] = serverList
    } else {
      lists.value.push(serverList)
      lists.value.sort((a, b) => a.position - b.position)
    }
  }

  function handleListUpdated(serverList: ShoppingList) {
    const idx = lists.value.findIndex(l => l.id === serverList.id)
    if (idx !== -1) {
      lists.value[idx] = serverList
    }
  }

  function handleListDeleted(data: { id: string }) {
    lists.value = lists.value.filter(l => l.id !== data.id)
    // Falls aktive Liste gelöscht wurde, erste verbleibende wählen
    if (activeListId.value === data.id && lists.value.length > 0) {
      setActiveList(lists.value[0].id)
    } else if (activeListId.value === data.id) {
      activeListId.value = null
    }
  }

  // ── Socket-Handler: Items — Idempotente Merges (Server gewinnt immer) ──

  function handleItemCreated(serverItem: ShoppingItem) {
    // Idempotenter Merge: Duplikat-Check statt pendingTempIds-Guard.
    // So werden auch Items von anderen Usern korrekt gepusht,
    // selbst wenn wir gerade ein eigenes Item erstellen.
    const existingIdx = items.value.findIndex(i => i.id === serverItem.id)
    if (existingIdx !== -1) {
      items.value[existingIdx] = serverItem
    } else {
      items.value.push(serverItem)
    }
    // Der REST-Response-Handler in addItem() erkennt via serverIdx !== -1
    // dass das Socket-Event schon gepusht hat und entfernt nur das Temp-Item.
  }

  function handleItemUpdated(serverItem: ShoppingItem) {
    const idx = items.value.findIndex(i => i.id === serverItem.id)
    if (idx !== -1) {
      items.value[idx] = serverItem // Server gewinnt immer
    }
  }

  function handleItemDeleted(data: { id: string }) {
    items.value = items.value.filter(i => i.id !== data.id)
  }

  return {
    // State
    items,
    lists,
    loading,
    activeListId,
    // Computed
    activeListItems,
    // Actions (Listen)
    fetchLists,
    setActiveList,
    createList,
    updateList,
    deleteList,
    // Actions (Items)
    fetchItems,
    addItem,
    toggleChecked,
    deleteItem,
    toggleAssigned,
    // Socket-Handlers (Listen)
    handleListCreated,
    handleListUpdated,
    handleListDeleted,
    // Socket-Handlers (Items)
    handleItemCreated,
    handleItemUpdated,
    handleItemDeleted,
  }
})
