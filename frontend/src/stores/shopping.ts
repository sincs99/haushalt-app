import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineShoppingRepository } from '../repositories/shoppingRepository'
import type { BulkAddResponse, ShoppingItem, ShoppingList, ShoppingListUpdatePayload } from '../types'
import { upsertVersioned } from '../utils/syncVersion'
import { findCanonicalStore, storesEqual } from '../utils/storeName'
import { ingredientKey } from '../utils/ingredientKey'

// ── localStorage-Persistenz für aktive Liste ──

function getStoredActiveListId(householdId: string): string | null {
  return localStorage.getItem(`shopping_activeList_${householdId}`)
}

function storeActiveListId(householdId: string, listId: string) {
  localStorage.setItem(`shopping_activeList_${householdId}`, listId)
}

// ── localStorage-Persistenz für Store-Filter ──

function getStoredStoreFilter(householdId: string): string | null {
  return localStorage.getItem(`shopping_storeFilter_${householdId}`)
}

function storeStoreFilter(householdId: string, store: string | null) {
  if (store) {
    localStorage.setItem(`shopping_storeFilter_${householdId}`, store)
  } else {
    localStorage.removeItem(`shopping_storeFilter_${householdId}`)
  }
}

export const useShoppingStore = defineStore('shopping', () => {
  // Repository — einmal im Store-Setup erstellen
  const repo = createOnlineShoppingRepository()

  // State
  const items = ref<ShoppingItem[]>([])
  const lists = ref<ShoppingList[]>([])
  const loading = ref(false)
  const activeListId = ref<string | null>(null)
  const stores = ref<string[]>([])
  const activeStoreFilter = ref<string | null>(null) // null = "Alle"

  // Interner State für Race-Condition-Schutz
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

    // Client-ID: ein Retry erzeugt keine doppelte Liste
    const newList = await repo.createList(householdId, { id: crypto.randomUUID(), name, icon })
    // Socket-Event kann schneller gewesen sein → Upsert statt push
    upsertVersioned(lists.value, newList, true)
    lists.value.sort((a, b) => a.position - b.position)
    return newList
  }

  async function updateList(listId: string, data: ShoppingListUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.updateList(householdId, listId, data)
    upsertVersioned(lists.value, updated, false)
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

  // ── Store-Filter Actions ──

  async function fetchStores() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    stores.value = await repo.fetchStores(householdId)

    // Aktiven Filter aus localStorage validieren (case-insensitive → kanonische Schreibweise)
    const stored = getStoredStoreFilter(householdId)
    const canonical = stored ? findCanonicalStore(stores.value, stored) : null
    if (canonical) {
      activeStoreFilter.value = canonical
      if (canonical !== stored) storeStoreFilter(householdId, canonical)
    } else {
      activeStoreFilter.value = null
    }
  }

  function setStoreFilter(store: string | null) {
    const authStore = useAuthStore()
    activeStoreFilter.value = store
    if (authStore.currentHouseholdId) {
      storeStoreFilter(authStore.currentHouseholdId, store)
    }
  }

  async function reassignStore(fromStore: string, toStore: string | null) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return { updated: 0 }

    const result = await repo.reassignStore(householdId, fromStore, toStore)

    // Tatsächlich verwendeter Ziel-Store: Das Backend merged case-insensitive in
    // eine bereits vorhandene Schreibweise (z. B. "coop" → "Coop").
    const targetStore = result.to_store ?? toStore

    // Optimistisch lokalen State patchen (Quell-Store case-insensitive matchen)
    for (const item of items.value) {
      if (storesEqual(item.store, fromStore)) {
        item.store = targetStore
      }
    }

    // Vor fetchStores() merken: fetchStores() verwirft den Filter auf fromStore,
    // weil dieser Store danach nicht mehr existiert
    const wasActiveFilter =
      activeStoreFilter.value !== null && storesEqual(activeStoreFilter.value, fromStore)

    // Stores-Liste aktualisieren
    await fetchStores()

    // Filter resetten falls der aktive Store umbenannt/aufgelöst wurde
    if (wasActiveFilter) {
      setStoreFilter(targetStore)
    }

    return result
  }

  async function updateItem(itemId: string, data: Partial<ShoppingItem>) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.update(householdId, itemId, data)
    upsertVersioned(items.value, updated, false)

    // Stores-Liste neu laden falls sich Store geändert hat
    if ('store' in data) {
      await fetchStores()
    }
  }

  async function addItem(
    name: string,
    quantity?: string,
    category?: string,
    store?: string,
  ): Promise<string | undefined> {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    if (!activeListId.value) return

    // 1. Optimistic: Sofort lokalen Eintrag mit endgültiger Client-ID erzeugen.
    //    Der Server übernimmt die ID → kein Temp-ID-Swap nötig.
    const itemId = crypto.randomUUID()
    const now = new Date().toISOString()
    const optimisticItem: ShoppingItem = {
      id: itemId,
      household_id: householdId,
      list_id: activeListId.value,
      name,
      quantity: quantity ?? null,
      category: category ?? null,
      is_checked: false,
      added_by_user_id: authStore.user?.id ?? null,
      created_at: now,
      checked_at: null,
      store: store ?? null,
      assigned_to_user_id: null,
      updated_at: now,
      version: 0, // noch nicht vom Server bestätigt
    }
    items.value.push(optimisticItem)

    try {
      // 2. Server-Call via Repository
      const serverItem = await repo.create(householdId, {
        id: itemId,
        name,
        list_id: activeListId.value,
        quantity,
        category,
        store,
      })

      // 3. Optimistischen Eintrag durch Server-Stand ersetzen. Gleiche ID wie das
      //    Socket-Event → egal wer zuerst kommt, es entsteht kein Duplikat.
      //    Kein Insert, falls das Item inzwischen gelöscht wurde.
      upsertVersioned(items.value, serverItem, false)
      return itemId
    } catch (error) {
      // 4. Rollback bei Fehler
      items.value = items.value.filter(i => i.id !== itemId)
      throw error
    }
  }

  /**
   * Mehrere Artikel auf eine Liste setzen ("Fehlende Zutaten" aus Rezept oder KI, PD-M2).
   * Der Server überspringt, was schon offen auf irgendeiner Liste steht (auch mit
   * Mengenangabe davor) — ein Retry legt nichts doppelt an. Ziel: übergebene oder
   * aktive Liste. Nach einem Haushaltswechsel wird die Antwort nicht mehr eingemischt.
   */
  async function bulkAddItems(names: string[], listId?: string): Promise<BulkAddResponse | undefined> {
    const householdId = useAuthStore().currentHouseholdId
    const targetListId = listId ?? activeListId.value
    if (!householdId || !targetListId || names.length === 0) return

    const result = await repo.bulkAdd(householdId, targetListId, names)
    if (useAuthStore().currentHouseholdId === householdId) {
      for (const item of result.added) upsertVersioned(items.value, item, true)
    }
    return result
  }

  /** Offene Artikel (alle Listen), deren Produkt dem Namen entspricht (PD-S1-Hinweis). */
  function findOpenDuplicates(name: string): ShoppingItem[] {
    const key = ingredientKey(name)
    if (!key) return []
    return items.value.filter(i => !i.is_checked && ingredientKey(i.name) === key)
  }

  /**
   * Stellt gelöschte Artikel vollständig wieder her (Undo): in ihrer ursprünglichen
   * Liste, mit Menge, Abteilung, Geschäft, Zuweisung und Abgehakt-Status.
   * Neue IDs, damit verspätete Lösch-Events der alten IDs nichts entfernen.
   * Scheitern einzelne Artikel, bleiben die übrigen erhalten und der erste Fehler
   * wird weitergereicht.
   */
  async function restoreItems(snapshots: ShoppingItem[]) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId || snapshots.length === 0) return

    const results = await Promise.allSettled(snapshots.map(async (snap) => {
      const itemId = crypto.randomUUID()
      const now = new Date().toISOString()
      items.value.push({
        ...snap,
        id: itemId,
        household_id: householdId,
        checked_at: snap.is_checked ? (snap.checked_at ?? now) : null,
        created_at: now,
        updated_at: now,
        version: 0, // noch nicht vom Server bestätigt
      })
      try {
        let serverItem = await repo.create(householdId, {
          id: itemId,
          name: snap.name,
          list_id: snap.list_id,
          quantity: snap.quantity ?? undefined,
          category: snap.category ?? undefined,
          store: snap.store ?? undefined,
          assigned_to_user_id: snap.assigned_to_user_id ?? undefined,
        })
        // Create kennt is_checked nicht → abgehakte Artikel nachträglich abhaken
        if (snap.is_checked) {
          serverItem = await repo.update(householdId, itemId, { is_checked: true })
        }
        if (serverItem) upsertVersioned(items.value, serverItem, false)
      } catch (error) {
        items.value = items.value.filter(i => i.id !== itemId)
        throw error
      }
    }))
    const failed = results.find((r): r is PromiseRejectedResult => r.status === 'rejected')
    if (failed) throw failed.reason
  }

  /**
   * Löscht mehrere Artikel (z. B. „Erledigte entfernen“). Scheitert ein Artikel,
   * bleibt er in der Liste; zurück kommen die tatsächlich gelöschten Artikel
   * (Snapshots fürs Undo) und die Anzahl der Fehlschläge.
   */
  async function deleteItems(itemIds: string[]) {
    const snapshots = new Map<string, ShoppingItem>()
    for (const i of items.value) {
      if (itemIds.includes(i.id)) snapshots.set(i.id, { ...i })
    }
    const results = await Promise.allSettled(itemIds.map(id => deleteItem(id).then(() => id)))
    const removed: ShoppingItem[] = []
    let failed = 0
    let firstError: unknown
    for (const r of results) {
      if (r.status === 'fulfilled') {
        const snap = snapshots.get(r.value)
        if (snap) removed.push(snap)
      } else {
        failed++
        if (firstError === undefined) firstError = r.reason
      }
    }
    return { removed, failed, error: firstError }
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
    if (upsertVersioned(lists.value, serverList, true)) {
      lists.value.sort((a, b) => a.position - b.position)
    }
  }

  function handleListUpdated(serverList: ShoppingList) {
    upsertVersioned(lists.value, serverList, false)
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

  // ── Socket-Handler: Items — Idempotente Merges (neuere Server-Version gewinnt) ──

  function handleItemCreated(serverItem: ShoppingItem) {
    // Idempotenter Merge per ID: eigene Items tragen bereits die Client-ID,
    // das Event ersetzt den optimistischen Eintrag statt ein Duplikat anzulegen.
    upsertVersioned(items.value, serverItem, true)
  }

  function handleItemUpdated(serverItem: ShoppingItem) {
    // Veraltete Events (niedrigere version) werden verworfen
    upsertVersioned(items.value, serverItem, false)
  }

  function handleItemDeleted(data: { id: string }) {
    items.value = items.value.filter(i => i.id !== data.id)
  }

  // ── Socket-Handler: Bulk-Update (Store-Reassign) ──

  function handleBulkUpdated(data: { item_ids: string[]; changes: { store: string | null } }) {
    const idSet = new Set(data.item_ids)
    for (const item of items.value) {
      if (idSet.has(item.id)) {
        if ('store' in data.changes) {
          item.store = data.changes.store
        }
      }
    }
    // Stores-Liste asynchron aktualisieren
    fetchStores()
  }

  return {
    // State
    items,
    lists,
    loading,
    activeListId,
    stores,
    activeStoreFilter,
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
    bulkAddItems,
    findOpenDuplicates,
    toggleChecked,
    deleteItem,
    deleteItems,
    restoreItems,
    toggleAssigned,
    updateItem,
    // Actions (Stores)
    fetchStores,
    setStoreFilter,
    reassignStore,
    // Socket-Handlers (Listen)
    handleListCreated,
    handleListUpdated,
    handleListDeleted,
    // Socket-Handlers (Items)
    handleItemCreated,
    handleItemUpdated,
    handleItemDeleted,
    handleBulkUpdated,
  }
})
