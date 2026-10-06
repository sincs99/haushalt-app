/**
 * Store-Tests für Client-IDs und Versions-Guards (Offline-Sync M0):
 * Rennen zwischen REST-Antwort und Socket-Event, veraltete Events.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ShoppingItem, TodoItem } from '../../types'

const shoppingRepo = { create: vi.fn(), update: vi.fn() }
const todosRepo = { create: vi.fn() }

vi.mock('../auth', () => ({
  useAuthStore: () => ({ currentHouseholdId: 'h1', user: { id: 'u1' } }),
}))
vi.mock('../../repositories/shoppingRepository', () => ({
  createOnlineShoppingRepository: () => shoppingRepo,
}))
vi.mock('../../repositories/todosRepository', () => ({
  createOnlineTodosRepository: () => todosRepo,
}))
vi.mock('../../repositories/householdsRepository', () => ({
  createOnlineHouseholdsRepository: () => ({}),
}))

const { useShoppingStore } = await import('../shopping')
const { useTodosStore } = await import('../todos')

function serverItem(id: string, overrides: Partial<ShoppingItem> = {}): ShoppingItem {
  return {
    id,
    household_id: 'h1',
    list_id: 'l1',
    name: 'Milch',
    quantity: null,
    category: null,
    is_checked: false,
    added_by_user_id: 'u1',
    created_at: '2026-10-06T10:00:00Z',
    checked_at: null,
    store: null,
    assigned_to_user_id: null,
    updated_at: '2026-10-06T10:00:00Z',
    version: 1,
    ...overrides,
  }
}

function serverTodo(id: string, overrides: Partial<TodoItem> = {}): TodoItem {
  return {
    id,
    household_id: 'h1',
    title: 'Velo flicken',
    description: null,
    assigned_to_user_id: null,
    due_date: null,
    is_done: false,
    created_by_user_id: 'u2',
    created_at: '2026-10-06T10:00:00Z',
    done_at: null,
    tags: [],
    updated_at: '2026-10-06T10:00:00Z',
    version: 1,
    reminders: [],
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('shopping: addItem mit Client-ID', () => {
  test('sendet die lokal erzeugte ID und ersetzt den optimistischen Eintrag', async () => {
    const store = useShoppingStore()
    store.activeListId = 'l1'
    shoppingRepo.create.mockImplementation(async (_h: string, data: { id: string }) => serverItem(data.id))

    const pending = store.addItem('Milch')
    // Sofort sichtbar, noch unbestätigt
    expect(store.items).toHaveLength(1)
    expect(store.items[0].version).toBe(0)
    const sentId = shoppingRepo.create.mock.calls[0][1].id
    expect(store.items[0].id).toBe(sentId)

    await pending
    expect(store.items).toHaveLength(1)
    expect(store.items[0]).toMatchObject({ id: sentId, version: 1 })
  })

  test('Socket-Event vor REST-Antwort erzeugt kein Duplikat', async () => {
    const store = useShoppingStore()
    store.activeListId = 'l1'
    let resolveCreate!: (item: ShoppingItem) => void
    shoppingRepo.create.mockImplementation(() => new Promise(r => { resolveCreate = r }))

    const pending = store.addItem('Milch')
    const sentId = shoppingRepo.create.mock.calls[0][1].id
    store.handleItemCreated(serverItem(sentId))
    expect(store.items).toHaveLength(1)

    resolveCreate(serverItem(sentId))
    await pending
    expect(store.items).toHaveLength(1)
  })

  test('Items anderer User während eigenem Create werden übernommen', async () => {
    const store = useShoppingStore()
    store.activeListId = 'l1'
    let resolveCreate!: (item: ShoppingItem) => void
    shoppingRepo.create.mockImplementation(() => new Promise(r => { resolveCreate = r }))

    const pending = store.addItem('Milch')
    const sentId = shoppingRepo.create.mock.calls[0][1].id
    store.handleItemCreated(serverItem('fremd', { name: 'Brot' }))
    resolveCreate(serverItem(sentId))
    await pending

    expect(store.items.map(i => i.id).sort()).toEqual([sentId, 'fremd'].sort())
  })

  test('Rollback bei Fehler entfernt den optimistischen Eintrag', async () => {
    const store = useShoppingStore()
    store.activeListId = 'l1'
    shoppingRepo.create.mockRejectedValue(new Error('offline'))

    await expect(store.addItem('Milch')).rejects.toThrow('offline')
    expect(store.items).toHaveLength(0)
  })
})

describe('shopping: Versions-Guard', () => {
  test('veraltetes Update-Event wird verworfen', () => {
    const store = useShoppingStore()
    store.items = [serverItem('a', { name: 'Hafermilch', version: 3 })]

    store.handleItemUpdated(serverItem('a', { name: 'Milch', version: 2 }))
    expect(store.items[0]).toMatchObject({ name: 'Hafermilch', version: 3 })

    store.handleItemUpdated(serverItem('a', { name: 'Sojamilch', version: 4 }))
    expect(store.items[0]).toMatchObject({ name: 'Sojamilch', version: 4 })
  })

  test('verspätete REST-Antwort überschreibt neueren Socket-Stand nicht', async () => {
    const store = useShoppingStore()
    store.items = [serverItem('a', { version: 1 })]
    shoppingRepo.update.mockImplementation(async () => {
      // Während der Request läuft, trifft bereits ein neuerer Stand per Socket ein
      store.handleItemUpdated(serverItem('a', { name: 'Neuer', version: 3 }))
      return serverItem('a', { name: 'Alt', version: 2 })
    })

    await store.updateItem('a', { name: 'Alt' })
    expect(store.items[0]).toMatchObject({ name: 'Neuer', version: 3 })
  })
})

describe('todos: handleTodoCreated', () => {
  test('Todo eines anderen Users während eigenem Create wird nicht verworfen', async () => {
    const store = useTodosStore()
    let resolveCreate!: (item: TodoItem) => void
    todosRepo.create.mockImplementation(() => new Promise(r => { resolveCreate = r }))

    const pending = store.addTodo('Eigenes Todo')
    const sentId = todosRepo.create.mock.calls[0][1].id
    store.handleTodoCreated(serverTodo('fremd'))
    expect(store.items.some(i => i.id === 'fremd')).toBe(true)

    resolveCreate(serverTodo(sentId, { title: 'Eigenes Todo', created_by_user_id: 'u1' }))
    await pending
    expect(store.items).toHaveLength(2)
  })

  test('Echo des eigenen Creates erzeugt kein Duplikat', async () => {
    const store = useTodosStore()
    todosRepo.create.mockImplementation(async (_h: string, data: { id: string }) => {
      store.handleTodoCreated(serverTodo(data.id))
      return serverTodo(data.id)
    })

    await store.addTodo('Velo flicken')
    expect(store.items).toHaveLength(1)
    expect(store.items[0].version).toBe(1)
  })
})
