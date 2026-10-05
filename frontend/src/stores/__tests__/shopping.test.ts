/**
 * Unit-Tests für den Shopping-Store: Optimistic Updates, Rollback,
 * Rapid-Click-Mutex, idempotente Socket-Handler und Store-Filter.
 *
 * Repository und Auth-Store sind gemockt — keine HTTP-Calls.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ShoppingItem, ShoppingList } from '../../types'
import { createMemoryStorage, deferred, HOUSEHOLD_ID, USER_ID } from './helpers'

const { repo, auth } = vi.hoisted(() => ({
  repo: {
    fetchLists: vi.fn(),
    createList: vi.fn(),
    updateList: vi.fn(),
    deleteList: vi.fn(),
    fetchAll: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    fetchStores: vi.fn(),
    reassignStore: vi.fn(),
  },
  auth: {
    currentHouseholdId: null as string | null,
    user: null as { id: string } | null,
  },
}))

vi.mock('../../repositories/shoppingRepository', () => ({
  createOnlineShoppingRepository: () => repo,
}))

vi.mock('../auth', () => ({
  useAuthStore: () => auth,
}))

import { useShoppingStore } from '../shopping'

const LIST_ID = 'list-1'

function makeItem(overrides: Partial<ShoppingItem> = {}): ShoppingItem {
  return {
    id: 'item-1',
    household_id: HOUSEHOLD_ID,
    list_id: LIST_ID,
    name: 'Milch',
    quantity: null,
    category: null,
    is_checked: false,
    added_by_user_id: USER_ID,
    created_at: '2026-01-01T00:00:00Z',
    checked_at: null,
    store: null,
    assigned_to_user_id: null,
    ...overrides,
  }
}

function makeList(overrides: Partial<ShoppingList> = {}): ShoppingList {
  return {
    id: LIST_ID,
    household_id: HOUSEHOLD_ID,
    name: 'Wocheneinkauf',
    icon: null,
    position: 0,
    created_at: '2026-01-01T00:00:00Z',
    open_count: 0,
    ...overrides,
  }
}

function setupStore() {
  const store = useShoppingStore()
  store.activeListId = LIST_ID
  return store
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  vi.stubGlobal('localStorage', createMemoryStorage())
  auth.currentHouseholdId = HOUSEHOLD_ID
  auth.user = { id: USER_ID }
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('addItem (optimistisch)', () => {
  test('zeigt sofort ein Temp-Item und ersetzt es durch das Server-Item', async () => {
    const store = setupStore()
    const pending = deferred<ShoppingItem>()
    repo.create.mockReturnValue(pending.promise)

    const promise = store.addItem('Brot', '2', 'Backwaren', 'Migros')

    // Temp-Item ist sofort sichtbar
    expect(store.items).toHaveLength(1)
    const temp = store.items[0]
    expect(temp.name).toBe('Brot')
    expect(temp.quantity).toBe('2')
    expect(temp.store).toBe('Migros')
    expect(temp.list_id).toBe(LIST_ID)
    expect(temp.is_checked).toBe(false)
    expect(temp.added_by_user_id).toBe(USER_ID)
    expect(repo.create).toHaveBeenCalledWith(HOUSEHOLD_ID, {
      name: 'Brot',
      list_id: LIST_ID,
      quantity: '2',
      category: 'Backwaren',
      store: 'Migros',
    })

    const serverItem = makeItem({ id: 'server-1', name: 'Brot', store: 'Migros' })
    pending.resolve(serverItem)
    await promise

    expect(store.items).toEqual([serverItem])
    expect(store.items.some(i => i.id === temp.id)).toBe(false)
  })

  test('rollt das Temp-Item bei Repository-Fehler zurück und wirft weiter', async () => {
    const store = setupStore()
    const existing = makeItem({ id: 'existing' })
    store.items.push(existing)
    repo.create.mockRejectedValue(new Error('500'))

    await expect(store.addItem('Brot')).rejects.toThrow('500')

    expect(store.items).toEqual([existing])
  })

  test('kein Duplikat, wenn das Socket-Event vor der REST-Antwort ankommt', async () => {
    const store = setupStore()
    const pending = deferred<ShoppingItem>()
    repo.create.mockReturnValue(pending.promise)
    const serverItem = makeItem({ id: 'server-1', name: 'Brot' })

    const promise = store.addItem('Brot')
    // Socket ist schneller als die REST-Antwort
    store.handleItemCreated(serverItem)
    expect(store.items).toHaveLength(2) // Temp + Server, kurzzeitig

    pending.resolve(serverItem)
    await promise

    expect(store.items).toHaveLength(1)
    expect(store.items[0].id).toBe('server-1')
  })

  test('Items anderer User werden während eines eigenen Creates nicht verschluckt', async () => {
    const store = setupStore()
    const pending = deferred<ShoppingItem>()
    repo.create.mockReturnValue(pending.promise)

    const promise = store.addItem('Brot')
    const foreignItem = makeItem({ id: 'foreign', name: 'Käse', added_by_user_id: 'user-2' })
    store.handleItemCreated(foreignItem)

    pending.resolve(makeItem({ id: 'server-1', name: 'Brot' }))
    await promise

    expect(store.items.map(i => i.id).sort()).toEqual(['foreign', 'server-1'])
  })

  test('tut nichts ohne aktive Liste oder ohne Haushalt', async () => {
    const store = useShoppingStore()
    await store.addItem('Brot')
    expect(store.items).toHaveLength(0)

    store.activeListId = LIST_ID
    auth.currentHouseholdId = null
    await store.addItem('Brot')
    expect(store.items).toHaveLength(0)
    expect(repo.create).not.toHaveBeenCalled()
  })
})

describe('toggleChecked', () => {
  test('setzt is_checked und checked_at optimistisch und ruft das Repository auf', async () => {
    const store = setupStore()
    store.items.push(makeItem())
    const pending = deferred<ShoppingItem>()
    repo.update.mockReturnValue(pending.promise)

    const promise = store.toggleChecked('item-1')
    expect(store.items[0].is_checked).toBe(true)
    expect(store.items[0].checked_at).not.toBeNull()
    expect(repo.update).toHaveBeenCalledWith(HOUSEHOLD_ID, 'item-1', { is_checked: true })

    pending.resolve(makeItem({ is_checked: true }))
    await promise
    expect(store.items[0].is_checked).toBe(true)
  })

  test('Rapid-Click-Mutex: zweiter Klick während laufendem Request wird ignoriert', async () => {
    const store = setupStore()
    store.items.push(makeItem())
    const pending = deferred<ShoppingItem>()
    repo.update.mockReturnValue(pending.promise)

    const first = store.toggleChecked('item-1')
    await store.toggleChecked('item-1')
    await store.toggleChecked('item-1')

    expect(repo.update).toHaveBeenCalledTimes(1)
    expect(store.items[0].is_checked).toBe(true)

    pending.resolve(makeItem({ is_checked: true }))
    await first

    // Nach Abschluss ist der Mutex wieder frei
    repo.update.mockResolvedValue(makeItem())
    await store.toggleChecked('item-1')
    expect(repo.update).toHaveBeenCalledTimes(2)
    expect(store.items[0].is_checked).toBe(false)
    expect(store.items[0].checked_at).toBeNull()
  })

  test('rollt bei Fehler zurück und gibt den Mutex wieder frei', async () => {
    const store = setupStore()
    store.items.push(makeItem())
    repo.update.mockRejectedValueOnce(new Error('offline'))

    await expect(store.toggleChecked('item-1')).rejects.toThrow('offline')
    expect(store.items[0].is_checked).toBe(false)
    expect(store.items[0].checked_at).toBeNull()

    repo.update.mockResolvedValue(makeItem({ is_checked: true }))
    await store.toggleChecked('item-1')
    expect(store.items[0].is_checked).toBe(true)
  })

  test('Rollback trifft auch ein zwischenzeitlich per Socket ersetztes Objekt', async () => {
    const store = setupStore()
    store.items.push(makeItem())
    const pending = deferred<ShoppingItem>()
    repo.update.mockReturnValue(pending.promise)

    const promise = store.toggleChecked('item-1')
    // Socket ersetzt das Objekt, während der Request läuft
    store.handleItemUpdated(makeItem({ is_checked: true, checked_at: '2026-01-02T00:00:00Z' }))

    pending.reject(new Error('500'))
    await expect(promise).rejects.toThrow('500')

    expect(store.items).toHaveLength(1)
    expect(store.items[0].is_checked).toBe(false)
    expect(store.items[0].checked_at).toBeNull()
  })
})

describe('deleteItem', () => {
  test('entfernt optimistisch und ruft das Repository auf', async () => {
    const store = setupStore()
    store.items.push(makeItem({ id: 'a' }), makeItem({ id: 'b' }))
    repo.remove.mockResolvedValue(undefined)

    await store.deleteItem('a')

    expect(store.items.map(i => i.id)).toEqual(['b'])
    expect(repo.remove).toHaveBeenCalledWith(HOUSEHOLD_ID, 'a')
  })

  test('fügt das Item bei Fehler an derselben Position wieder ein', async () => {
    const store = setupStore()
    store.items.push(makeItem({ id: 'a' }), makeItem({ id: 'b' }), makeItem({ id: 'c' }))
    const pending = deferred<void>()
    repo.remove.mockReturnValue(pending.promise)

    const promise = store.deleteItem('b')
    expect(store.items.map(i => i.id)).toEqual(['a', 'c'])

    pending.reject(new Error('403'))
    await expect(promise).rejects.toThrow('403')
    expect(store.items.map(i => i.id)).toEqual(['a', 'b', 'c'])
  })
})

describe('Socket-Handler (Items)', () => {
  test('item_created ist idempotent — Server gewinnt', () => {
    const store = setupStore()
    store.handleItemCreated(makeItem({ name: 'Milch' }))
    store.handleItemCreated(makeItem({ name: 'Hafermilch' }))

    expect(store.items).toHaveLength(1)
    expect(store.items[0].name).toBe('Hafermilch')
  })

  test('item_updated ersetzt bestehende Items und ignoriert unbekannte', () => {
    const store = setupStore()
    store.items.push(makeItem())

    store.handleItemUpdated(makeItem({ name: 'Vollmilch', is_checked: true }))
    store.handleItemUpdated(makeItem({ id: 'unknown' }))

    expect(store.items).toHaveLength(1)
    expect(store.items[0]).toMatchObject({ name: 'Vollmilch', is_checked: true })
  })

  test('item_deleted entfernt das Item, mehrfaches Event ist harmlos', () => {
    const store = setupStore()
    store.items.push(makeItem({ id: 'a' }), makeItem({ id: 'b' }))

    store.handleItemDeleted({ id: 'a' })
    store.handleItemDeleted({ id: 'a' })

    expect(store.items.map(i => i.id)).toEqual(['b'])
  })

  test('shopping_items_bulk_updated setzt den Store nur auf den genannten Items', async () => {
    const store = setupStore()
    store.items.push(
      makeItem({ id: 'a', store: 'Coop' }),
      makeItem({ id: 'b', store: 'Coop' }),
      makeItem({ id: 'c', store: 'Migros' }),
    )
    repo.fetchStores.mockResolvedValue(['Aldi', 'Migros'])

    store.handleBulkUpdated({ item_ids: ['a', 'b'], changes: { store: 'Aldi' } })

    expect(store.items.map(i => i.store)).toEqual(['Aldi', 'Aldi', 'Migros'])
    expect(repo.fetchStores).toHaveBeenCalledWith(HOUSEHOLD_ID)
    await vi.waitFor(() => expect(store.stores).toEqual(['Aldi', 'Migros']))
  })
})

describe('Listen', () => {
  test('activeListItems filtert nach der aktiven Liste', () => {
    const store = setupStore()
    store.items.push(
      makeItem({ id: 'a', list_id: LIST_ID }),
      makeItem({ id: 'b', list_id: 'list-2' }),
    )

    expect(store.activeListItems.map(i => i.id)).toEqual(['a'])
    store.setActiveList('list-2')
    expect(store.activeListItems.map(i => i.id)).toEqual(['b'])
  })

  test('fetchLists stellt die aktive Liste aus localStorage wieder her', async () => {
    localStorage.setItem(`shopping_activeList_${HOUSEHOLD_ID}`, 'list-2')
    repo.fetchLists.mockResolvedValue([makeList(), makeList({ id: 'list-2', position: 1 })])
    const store = useShoppingStore()

    await store.fetchLists()
    expect(store.activeListId).toBe('list-2')
  })

  test('fetchLists fällt bei ungültigem gespeichertem Wert auf die erste Liste zurück', async () => {
    localStorage.setItem(`shopping_activeList_${HOUSEHOLD_ID}`, 'deleted-list')
    repo.fetchLists.mockResolvedValue([makeList(), makeList({ id: 'list-2', position: 1 })])
    const store = useShoppingStore()

    await store.fetchLists()
    expect(store.activeListId).toBe(LIST_ID)
    expect(localStorage.getItem(`shopping_activeList_${HOUSEHOLD_ID}`)).toBe(LIST_ID)
  })

  test('list_deleted für die aktive Liste wechselt auf die erste verbleibende', () => {
    const store = setupStore()
    store.lists.push(makeList(), makeList({ id: 'list-2', position: 1 }))

    store.handleListDeleted({ id: LIST_ID })
    expect(store.activeListId).toBe('list-2')

    store.handleListDeleted({ id: 'list-2' })
    expect(store.activeListId).toBeNull()
  })
})

describe('Store-Filter und reassign-store', () => {
  test('fetchStores übernimmt einen gültigen gespeicherten Filter', async () => {
    localStorage.setItem(`shopping_storeFilter_${HOUSEHOLD_ID}`, 'Coop')
    repo.fetchStores.mockResolvedValue(['Coop', 'Migros'])
    const store = useShoppingStore()

    await store.fetchStores()
    expect(store.stores).toEqual(['Coop', 'Migros'])
    expect(store.activeStoreFilter).toBe('Coop')
  })

  test('fetchStores verwirft einen Filter auf einen nicht mehr existierenden Store', async () => {
    localStorage.setItem(`shopping_storeFilter_${HOUSEHOLD_ID}`, 'Denner')
    repo.fetchStores.mockResolvedValue(['Coop', 'Migros'])
    const store = useShoppingStore()

    await store.fetchStores()
    expect(store.activeStoreFilter).toBeNull()
  })

  test('setStoreFilter persistiert pro Haushalt und entfernt bei null', () => {
    const store = useShoppingStore()

    store.setStoreFilter('Coop')
    expect(localStorage.getItem(`shopping_storeFilter_${HOUSEHOLD_ID}`)).toBe('Coop')

    store.setStoreFilter(null)
    expect(store.activeStoreFilter).toBeNull()
    expect(localStorage.getItem(`shopping_storeFilter_${HOUSEHOLD_ID}`)).toBeNull()
  })

  test('reassignStore benennt um: Items, Stores-Liste und aktiver Filter folgen', async () => {
    const store = setupStore()
    store.items.push(
      makeItem({ id: 'a', store: 'Coop' }),
      makeItem({ id: 'b', store: 'Migros' }),
    )
    store.setStoreFilter('Coop')
    repo.reassignStore.mockResolvedValue({ updated: 1 })
    repo.fetchStores.mockResolvedValue(['Coop City', 'Migros'])

    const result = await store.reassignStore('Coop', 'Coop City')

    expect(result).toEqual({ updated: 1 })
    expect(repo.reassignStore).toHaveBeenCalledWith(HOUSEHOLD_ID, 'Coop', 'Coop City')
    expect(store.items.map(i => i.store)).toEqual(['Coop City', 'Migros'])
    expect(store.stores).toEqual(['Coop City', 'Migros'])
    expect(store.activeStoreFilter).toBe('Coop City')
  })

  test('reassignStore löst auf (null): Items ohne Store, Filter zurück auf "Alle"', async () => {
    const store = setupStore()
    store.items.push(makeItem({ id: 'a', store: 'Coop' }))
    store.setStoreFilter('Coop')
    repo.reassignStore.mockResolvedValue({ updated: 1 })
    repo.fetchStores.mockResolvedValue([])

    await store.reassignStore('Coop', null)

    expect(store.items[0].store).toBeNull()
    expect(store.activeStoreFilter).toBeNull()
    expect(localStorage.getItem(`shopping_storeFilter_${HOUSEHOLD_ID}`)).toBeNull()
  })

  test('reassignStore lässt den lokalen State bei Server-Fehler unverändert', async () => {
    const store = setupStore()
    store.items.push(makeItem({ id: 'a', store: 'Coop' }))
    repo.reassignStore.mockRejectedValue(new Error('500'))

    await expect(store.reassignStore('Coop', 'Migros')).rejects.toThrow('500')
    expect(store.items[0].store).toBe('Coop')
    expect(repo.fetchStores).not.toHaveBeenCalled()
  })
})
