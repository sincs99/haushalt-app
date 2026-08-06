import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineShoppingRepository } from '../repositories/shoppingRepository'
import type { ShoppingItem } from '../types'

export const useShoppingStore = defineStore('shopping', () => {
  // Repository — einmal im Store-Setup erstellen
  const repo = createOnlineShoppingRepository()

  // State
  const items = ref<ShoppingItem[]>([])
  const loading = ref(false)

  // Interner State für Race-Condition-Schutz
  const pendingTempIds = new Set<string>()
  const pendingToggles = new Set<string>()

  // Actions
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

  async function addItem(name: string, quantity?: string, category?: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // 1. Optimistic: Sofort lokalen Temp-Eintrag erzeugen
    const tempId = crypto.randomUUID()
    const tempItem: ShoppingItem = {
      id: tempId,
      household_id: householdId,
      name,
      quantity: quantity ?? null,
      category: category ?? null,
      is_checked: false,
      added_by_user_id: authStore.user?.id ?? null,
      created_at: new Date().toISOString(),
      checked_at: null,
    }
    items.value.push(tempItem)
    pendingTempIds.add(tempId)

    try {
      // 2. Server-Call via Repository
      const serverItem = await repo.create(householdId, { name, quantity, category })
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

  // Socket-Handler — Idempotente Merges (Server gewinnt immer)
  function handleItemCreated(serverItem: ShoppingItem) {
    // Wenn wir gerade selbst ein Item erstellt haben, könnte das Socket-Event
    // vor dem REST-Response kommen. In diesem Fall ignorieren — der REST-Response
    // erledigt den Temp→Server-Swap.
    if (pendingTempIds.size > 0) {
      const existingIdx = items.value.findIndex(i => i.id === serverItem.id)
      if (existingIdx !== -1) {
        items.value[existingIdx] = serverItem
      }
      // KEIN push — REST-Response-Handling macht den Swap
      return
    }
    // Normaler Fall (Event von anderem Haushaltsmitglied)
    const existingIdx = items.value.findIndex(i => i.id === serverItem.id)
    if (existingIdx !== -1) {
      items.value[existingIdx] = serverItem
    } else {
      items.value.push(serverItem)
    }
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
    loading,
    // Actions
    fetchItems,
    addItem,
    toggleChecked,
    deleteItem,
    // Socket-Handlers
    handleItemCreated,
    handleItemUpdated,
    handleItemDeleted,
  }
})
