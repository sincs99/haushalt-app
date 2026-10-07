import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { ShoppingItem, ShoppingList } from '../../types'

const { repo, auth } = vi.hoisted(() => ({
  repo: {
    fetchAll: vi.fn(),
    fetchLists: vi.fn(),
    fetchStores: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    createList: vi.fn(),
    updateList: vi.fn(),
    deleteList: vi.fn(),
    reassignStore: vi.fn(),
  },
  auth: { currentHouseholdId: 'h1' as string | null, user: { id: 'u1' } },
}))

vi.mock('../auth', () => ({ useAuthStore: () => auth }))
vi.mock('../../repositories/shoppingRepository', () => ({
  createOnlineShoppingRepository: () => repo,
}))

import { useShoppingStore } from '../shopping'

function item(over: Partial<ShoppingItem> = {}): ShoppingItem {
  return {
    id: 'i1',
    household_id: 'h1',
    list_id: 'l1',
    name: 'Milk',
    quantity: null,
    category: null,
    is_checked: false,
    added_by_user_id: 'u1',
    created_at: '2024-01-01T00:00:00Z',
    checked_at: null,
    store: null,
    assigned_to_user_id: null,
    updated_at: '2024-01-01T00:00:00Z',
    version: 1,
    ...over,
  }
}

function list(id: string, position = 0): ShoppingList {
  return { id, household_id: 'h1', name: id, position } as ShoppingList
}

describe('shopping store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(repo).forEach(fn => fn.mockReset())
    auth.currentHouseholdId = 'h1'
    localStorage.clear()
  })

  it('fetchItems loads items and resets loading', async () => {
    repo.fetchAll.mockResolvedValue([item()])
    const s = useShoppingStore()
    const p = s.fetchItems()
    expect(s.loading).toBe(true)
    await p
    expect(s.loading).toBe(false)
    expect(s.items).toHaveLength(1)
    expect(repo.fetchAll).toHaveBeenCalledWith('h1')
  })

  it('fetchItems resets loading when the repository fails', async () => {
    repo.fetchAll.mockRejectedValue(new Error('x'))
    const s = useShoppingStore()
    await expect(s.fetchItems()).rejects.toThrow('x')
    expect(s.loading).toBe(false)
  })

  it('does nothing without a household', async () => {
    auth.currentHouseholdId = null
    const s = useShoppingStore()
    await s.fetchItems()
    expect(repo.fetchAll).not.toHaveBeenCalled()
  })

  it('fetchLists picks the stored active list, else the first', async () => {
    repo.fetchLists.mockResolvedValue([list('a'), list('b')])
    localStorage.setItem('shopping_activeList_h1', 'b')
    const s = useShoppingStore()
    await s.fetchLists()
    expect(s.activeListId).toBe('b')

    localStorage.clear()
    s.activeListId = null
    await s.fetchLists()
    expect(s.activeListId).toBe('a')
    expect(localStorage.getItem('shopping_activeList_h1')).toBe('a')
  })

  describe('addItem', () => {
    it('adds an optimistic item with a client-generated id and keeps it when the server confirms', async () => {
      const s = useShoppingStore()
      s.activeListId = 'l1'
      let resolve!: (v: ShoppingItem) => void
      repo.create.mockReturnValue(new Promise(r => (resolve = r)))

      const p = s.addItem('Milk')
      expect(s.items).toHaveLength(1)
      expect(s.items[0].name).toBe('Milk')
      expect(s.items[0].version).toBe(0) // noch nicht vom Server bestätigt
      const clientId = s.items[0].id
      // Die Client-ID wird mitgeschickt, der Server übernimmt sie
      expect(repo.create).toHaveBeenCalledWith('h1', expect.objectContaining({ id: clientId, name: 'Milk' }))

      resolve(item({ id: clientId, version: 1 }))
      await p
      expect(s.items).toHaveLength(1)
      expect(s.items[0].id).toBe(clientId) // kein Temp-ID-Swap
      expect(s.items[0].version).toBe(1)
    })

    it('rolls back the temp item and rethrows on failure', async () => {
      const s = useShoppingStore()
      s.activeListId = 'l1'
      repo.create.mockRejectedValue(new Error('fail'))
      await expect(s.addItem('Milk')).rejects.toThrow('fail')
      expect(s.items).toHaveLength(0)
    })

    it('does not duplicate when the socket event arrives before the REST response', async () => {
      const s = useShoppingStore()
      s.activeListId = 'l1'
      let resolve!: (v: ShoppingItem) => void
      repo.create.mockReturnValue(new Promise(r => (resolve = r)))

      const p = s.addItem('Milk')
      const clientId = s.items[0].id
      // Eigenes Item trägt die Client-ID → das Socket-Event ersetzt es per ID
      s.handleItemCreated(item({ id: clientId, version: 1 }))
      expect(s.items.map(i => i.id)).toEqual([clientId])
      resolve(item({ id: clientId, version: 1 }))
      await p
      expect(s.items.map(i => i.id)).toEqual([clientId])
    })

    it('is a no-op without an active list', async () => {
      const s = useShoppingStore()
      await s.addItem('Milk')
      expect(s.items).toHaveLength(0)
      expect(repo.create).not.toHaveBeenCalled()
    })
  })

  describe('toggleChecked', () => {
    it('optimistically toggles and sends the new value', async () => {
      const s = useShoppingStore()
      s.items = [item()]
      repo.update.mockResolvedValue(item({ is_checked: true }))
      const p = s.toggleChecked('i1')
      expect(s.items[0].is_checked).toBe(true)
      expect(s.items[0].checked_at).not.toBeNull()
      await p
      expect(repo.update).toHaveBeenCalledWith('h1', 'i1', { is_checked: true })
    })

    it('rolls back on failure', async () => {
      const s = useShoppingStore()
      s.items = [item()]
      repo.update.mockRejectedValue(new Error('fail'))
      await expect(s.toggleChecked('i1')).rejects.toThrow('fail')
      expect(s.items[0].is_checked).toBe(false)
      expect(s.items[0].checked_at).toBeNull()
    })

    it('ignores a second toggle while one is in flight', async () => {
      const s = useShoppingStore()
      s.items = [item()]
      let resolve!: () => void
      repo.update.mockReturnValue(new Promise<void>(r => (resolve = r)))
      const p1 = s.toggleChecked('i1')
      await s.toggleChecked('i1')
      expect(repo.update).toHaveBeenCalledTimes(1)
      resolve()
      await p1
      // lock released afterwards
      repo.update.mockResolvedValue(item())
      await s.toggleChecked('i1')
      expect(repo.update).toHaveBeenCalledTimes(2)
    })

    it('rolls back on the replaced object if a socket event swapped the item', async () => {
      const s = useShoppingStore()
      s.items = [item()]
      let reject!: (e: Error) => void
      repo.update.mockReturnValue(new Promise((_, r) => (reject = r)))
      const p = s.toggleChecked('i1')
      s.handleItemUpdated(item({ is_checked: true, name: 'Milk 2' }))
      reject(new Error('fail'))
      await expect(p).rejects.toThrow()
      expect(s.items[0].is_checked).toBe(false)
      expect(s.items[0].name).toBe('Milk 2')
    })
  })

  describe('deleteItem', () => {
    it('removes optimistically and keeps it removed on success', async () => {
      const s = useShoppingStore()
      s.items = [item({ id: 'a' }), item({ id: 'b' })]
      repo.remove.mockResolvedValue(undefined)
      await s.deleteItem('a')
      expect(s.items.map(i => i.id)).toEqual(['b'])
    })

    it('restores the item at its original position on failure', async () => {
      const s = useShoppingStore()
      s.items = [item({ id: 'a' }), item({ id: 'b' }), item({ id: 'c' })]
      repo.remove.mockRejectedValue(new Error('fail'))
      await expect(s.deleteItem('b')).rejects.toThrow('fail')
      expect(s.items.map(i => i.id)).toEqual(['a', 'b', 'c'])
    })
  })

  describe('deleteItems', () => {
    it('returns the removed snapshots and counts failures; failed items stay', async () => {
      const s = useShoppingStore()
      s.items = [item({ id: 'a', is_checked: true }), item({ id: 'b', is_checked: true })]
      repo.remove.mockImplementation(async (_h: string, id: string) => {
        if (id === 'b') throw new Error('fail')
      })
      const result = await s.deleteItems(['a', 'b'])
      expect(result.removed.map(i => i.id)).toEqual(['a'])
      expect(result.failed).toBe(1)
      expect(result.error).toBeInstanceOf(Error)
      expect(s.items.map(i => i.id)).toEqual(['b'])
    })
  })

  describe('restoreItems', () => {
    it('restores items checked, in their original list, with assignment', async () => {
      const s = useShoppingStore()
      s.activeListId = 'other'
      repo.create.mockImplementation(async (_h: string, p: { id: string; list_id: string }) =>
        item({ id: p.id, list_id: p.list_id, version: 1 }))
      repo.update.mockImplementation(async (_h: string, id: string) =>
        item({ id, list_id: 'l1', is_checked: true, assigned_to_user_id: 'u2', version: 2 }))
      await s.restoreItems([item({ id: 'old', list_id: 'l1', is_checked: true, assigned_to_user_id: 'u2', store: 'Coop' })])
      expect(repo.create.mock.calls[0][1]).toMatchObject({ list_id: 'l1', assigned_to_user_id: 'u2', store: 'Coop' })
      expect(repo.create.mock.calls[0][1].id).not.toBe('old')
      expect(repo.update).toHaveBeenCalledWith('h1', repo.create.mock.calls[0][1].id, { is_checked: true })
      expect(s.items).toHaveLength(1)
      expect(s.items[0]).toMatchObject({ list_id: 'l1', is_checked: true })
    })

    it('shows restored items optimistically and keeps the successful ones on partial failure', async () => {
      const s = useShoppingStore()
      repo.create.mockImplementation(async (_h: string, p: { id: string; name: string }) => {
        if (p.name === 'Bad') throw new Error('fail')
        return item({ id: p.id, name: p.name })
      })
      const p = s.restoreItems([item({ id: 'x', name: 'Good' }), item({ id: 'y', name: 'Bad' })])
      expect(s.items).toHaveLength(2)
      await expect(p).rejects.toThrow('fail')
      expect(s.items.map(i => i.name)).toEqual(['Good'])
      expect(repo.update).not.toHaveBeenCalled()
    })
  })

  it('addItem returns the new id and createList returns the list', async () => {
    const s = useShoppingStore()
    s.activeListId = 'l1'
    repo.create.mockImplementation(async (_h: string, p: { id: string }) => item({ id: p.id }))
    const id = await s.addItem('Brot')
    expect(s.items[0].id).toBe(id)
    repo.createList.mockResolvedValue(list('l2', 1))
    const created = await s.createList('Neu')
    expect(created?.id).toBe('l2')
  })

  describe('toggleAssigned', () => {
    it('assigns to the current user and unassigns on second call', async () => {
      const s = useShoppingStore()
      s.items = [item()]
      repo.update.mockResolvedValue(item())
      await s.toggleAssigned('i1')
      expect(s.items[0].assigned_to_user_id).toBe('u1')
      await s.toggleAssigned('i1')
      expect(s.items[0].assigned_to_user_id).toBeNull()
    })

    it('rolls back on failure', async () => {
      const s = useShoppingStore()
      s.items = [item()]
      repo.update.mockRejectedValue(new Error('fail'))
      await expect(s.toggleAssigned('i1')).rejects.toThrow()
      expect(s.items[0].assigned_to_user_id).toBeNull()
    })
  })

  describe('reassignStore', () => {
    it('moves the active store filter along when the active store is renamed', async () => {
      const s = useShoppingStore()
      s.setStoreFilter('Coop')
      repo.reassignStore.mockResolvedValue({ updated: 1 })
      repo.fetchStores.mockResolvedValue(['Coop City']) // 'Coop' gibt es nicht mehr
      await s.reassignStore('Coop', 'Coop City')
      expect(s.activeStoreFilter).toBe('Coop City')
    })

    it('follows the canonical spelling when the backend merges into an existing store', async () => {
      const s = useShoppingStore()
      s.setStoreFilter('coop')
      repo.reassignStore.mockResolvedValue({ updated: 1, to_store: 'Coop' })
      repo.fetchStores.mockResolvedValue(['Coop']) // 'coop' wurde in 'Coop' überführt
      await s.reassignStore('coop', 'coop')
      expect(s.activeStoreFilter).toBe('Coop')
    })

    it('resets the filter to "all" when the active store is dissolved', async () => {
      const s = useShoppingStore()
      s.setStoreFilter('Coop')
      repo.reassignStore.mockResolvedValue({ updated: 1 })
      repo.fetchStores.mockResolvedValue([])
      await s.reassignStore('Coop', null)
      expect(s.activeStoreFilter).toBeNull()
    })
  })

  describe('socket handlers', () => {
    it('handleItemCreated is idempotent', () => {
      const s = useShoppingStore()
      s.handleItemCreated(item())
      s.handleItemCreated(item({ name: 'Updated' }))
      expect(s.items).toHaveLength(1)
      expect(s.items[0].name).toBe('Updated')
    })

    it('handleItemUpdated replaces existing and ignores unknown ids', () => {
      const s = useShoppingStore()
      s.items = [item()]
      s.handleItemUpdated(item({ name: 'New' }))
      s.handleItemUpdated(item({ id: 'unknown' }))
      expect(s.items).toHaveLength(1)
      expect(s.items[0].name).toBe('New')
    })

    it('handleItemDeleted removes the item and tolerates repeats', () => {
      const s = useShoppingStore()
      s.items = [item()]
      s.handleItemDeleted({ id: 'i1' })
      s.handleItemDeleted({ id: 'i1' })
      expect(s.items).toHaveLength(0)
    })

    it('handleBulkUpdated patches the store of the given items and refreshes stores', () => {
      const s = useShoppingStore()
      repo.fetchStores.mockResolvedValue([])
      s.items = [item({ id: 'a', store: 'X' }), item({ id: 'b', store: 'X' })]
      s.handleBulkUpdated({ item_ids: ['a'], changes: { store: 'Y' } })
      expect(s.items.map(i => i.store)).toEqual(['Y', 'X'])
      expect(repo.fetchStores).toHaveBeenCalled()
    })

    it('handleListCreated merges idempotently and keeps position order', () => {
      const s = useShoppingStore()
      s.handleListCreated(list('b', 2))
      s.handleListCreated(list('a', 1))
      s.handleListCreated(list('a', 1))
      expect(s.lists.map(l => l.id)).toEqual(['a', 'b'])
    })

    it('handleListDeleted falls back to the first remaining list', () => {
      const s = useShoppingStore()
      s.lists = [list('a'), list('b')]
      s.activeListId = 'a'
      s.handleListDeleted({ id: 'a' })
      expect(s.activeListId).toBe('b')
      s.handleListDeleted({ id: 'b' })
      expect(s.activeListId).toBeNull()
    })
  })

  it('activeListItems only returns items of the active list', () => {
    const s = useShoppingStore()
    s.items = [item({ id: 'a', list_id: 'l1' }), item({ id: 'b', list_id: 'l2' })]
    s.activeListId = 'l2'
    expect(s.activeListItems.map(i => i.id)).toEqual(['b'])
  })

  it('store filter persists to localStorage and is validated on fetchStores', async () => {
    const s = useShoppingStore()
    s.setStoreFilter('Coop')
    expect(localStorage.getItem('shopping_storeFilter_h1')).toBe('Coop')
    repo.fetchStores.mockResolvedValue(['Coop', 'Migros'])
    await s.fetchStores()
    expect(s.activeStoreFilter).toBe('Coop')
    repo.fetchStores.mockResolvedValue(['Migros'])
    await s.fetchStores()
    expect(s.activeStoreFilter).toBeNull()
    s.setStoreFilter(null)
    expect(localStorage.getItem('shopping_storeFilter_h1')).toBeNull()
  })
})
