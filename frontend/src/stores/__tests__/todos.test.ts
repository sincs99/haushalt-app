/**
 * Unit-Tests für den Todos-Store: Optimistic Create/Toggle/Update/Delete,
 * Rollback, Rapid-Click-Mutex, Reminders und idempotente Socket-Handler.
 *
 * Repositories und Auth-Store sind gemockt — keine HTTP-Calls.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { TodoItem, TodoReminder } from '../../types'
import { deferred, HOUSEHOLD_ID, USER_ID } from './helpers'

const { repo, householdRepo, auth } = vi.hoisted(() => ({
  repo: {
    fetchAll: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    addReminder: vi.fn(),
    deleteReminder: vi.fn(),
  },
  householdRepo: {
    fetchMembers: vi.fn(),
  },
  auth: {
    currentHouseholdId: null as string | null,
    user: null as { id: string } | null,
  },
}))

vi.mock('../../repositories/todosRepository', () => ({
  createOnlineTodosRepository: () => repo,
}))

vi.mock('../../repositories/householdsRepository', () => ({
  createOnlineHouseholdsRepository: () => householdRepo,
}))

vi.mock('../auth', () => ({
  useAuthStore: () => auth,
}))

import { useTodosStore } from '../todos'

function makeTodo(overrides: Partial<TodoItem> = {}): TodoItem {
  return {
    id: 'todo-1',
    household_id: HOUSEHOLD_ID,
    title: 'Fenster putzen',
    description: null,
    assigned_to_user_id: null,
    due_date: null,
    is_done: false,
    created_by_user_id: USER_ID,
    created_at: '2026-01-01T00:00:00Z',
    done_at: null,
    tags: [],
    reminders: [],
    ...overrides,
  }
}

function makeReminder(overrides: Partial<TodoReminder> = {}): TodoReminder {
  return {
    id: 'rem-1',
    todo_id: 'todo-1',
    remind_at: '2026-02-01T09:00:00Z',
    notified_at: null,
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  auth.currentHouseholdId = HOUSEHOLD_ID
  auth.user = { id: USER_ID }
})

describe('fetch', () => {
  test('fetchTodos lädt Items und setzt loading während des Requests', async () => {
    const store = useTodosStore()
    const pending = deferred<TodoItem[]>()
    repo.fetchAll.mockReturnValue(pending.promise)

    const promise = store.fetchTodos()
    expect(store.loading).toBe(true)

    pending.resolve([makeTodo()])
    await promise
    expect(store.loading).toBe(false)
    expect(store.items).toHaveLength(1)
    expect(repo.fetchAll).toHaveBeenCalledWith(HOUSEHOLD_ID)
  })

  test('fetchTodos setzt loading auch bei Fehler zurück', async () => {
    const store = useTodosStore()
    repo.fetchAll.mockRejectedValue(new Error('offline'))

    await expect(store.fetchTodos()).rejects.toThrow('offline')
    expect(store.loading).toBe(false)
  })
})

describe('addTodo (optimistisch)', () => {
  test('zeigt sofort ein Temp-Todo und ersetzt es durch das Server-Todo', async () => {
    const store = useTodosStore()
    const pending = deferred<TodoItem>()
    repo.create.mockReturnValue(pending.promise)

    const promise = store.addTodo('Müll', 'Bio + Papier', 'user-2', '2026-02-01', ['haus'])

    expect(store.items).toHaveLength(1)
    const temp = store.items[0]
    expect(temp).toMatchObject({
      title: 'Müll',
      description: 'Bio + Papier',
      assigned_to_user_id: 'user-2',
      due_date: '2026-02-01',
      tags: ['haus'],
      is_done: false,
      created_by_user_id: USER_ID,
    })
    expect(repo.create).toHaveBeenCalledWith(HOUSEHOLD_ID, {
      title: 'Müll',
      description: 'Bio + Papier',
      assigned_to_user_id: 'user-2',
      due_date: '2026-02-01',
      tags: ['haus'],
    })

    const serverTodo = makeTodo({ id: 'server-1', title: 'Müll' })
    pending.resolve(serverTodo)
    await promise

    expect(store.items).toEqual([serverTodo])
  })

  test('rollt das Temp-Todo bei Repository-Fehler zurück und wirft weiter', async () => {
    const store = useTodosStore()
    const existing = makeTodo({ id: 'existing' })
    store.items.push(existing)
    repo.create.mockRejectedValue(new Error('500'))

    await expect(store.addTodo('Müll')).rejects.toThrow('500')
    expect(store.items).toEqual([existing])
  })

  test('kein Duplikat, wenn das Socket-Event vor der REST-Antwort ankommt', async () => {
    const store = useTodosStore()
    const pending = deferred<TodoItem>()
    repo.create.mockReturnValue(pending.promise)
    const serverTodo = makeTodo({ id: 'server-1', title: 'Müll' })

    const promise = store.addTodo('Müll')
    store.handleTodoCreated(serverTodo)

    pending.resolve(serverTodo)
    await promise

    expect(store.items).toHaveLength(1)
    expect(store.items[0].id).toBe('server-1')
  })

  test('Todos anderer User werden während eines eigenen Creates nicht verschluckt', async () => {
    const store = useTodosStore()
    const pending = deferred<TodoItem>()
    repo.create.mockReturnValue(pending.promise)

    const promise = store.addTodo('Müll')
    store.handleTodoCreated(makeTodo({ id: 'foreign', title: 'Einkaufen', created_by_user_id: 'user-2' }))

    pending.resolve(makeTodo({ id: 'server-1', title: 'Müll' }))
    await promise

    expect(store.items.map(i => i.id).sort()).toEqual(['foreign', 'server-1'])
  })
})

describe('toggleDone (erledigen)', () => {
  test('setzt is_done und done_at optimistisch', async () => {
    const store = useTodosStore()
    store.items.push(makeTodo())
    const pending = deferred<TodoItem>()
    repo.update.mockReturnValue(pending.promise)

    const promise = store.toggleDone('todo-1')
    expect(store.items[0].is_done).toBe(true)
    expect(store.items[0].done_at).not.toBeNull()
    expect(repo.update).toHaveBeenCalledWith(HOUSEHOLD_ID, 'todo-1', { is_done: true })

    pending.resolve(makeTodo({ is_done: true }))
    await promise
    expect(store.items[0].is_done).toBe(true)
  })

  test('Rapid-Click-Mutex: Klicks während laufendem Request werden ignoriert', async () => {
    const store = useTodosStore()
    store.items.push(makeTodo())
    const pending = deferred<TodoItem>()
    repo.update.mockReturnValue(pending.promise)

    const first = store.toggleDone('todo-1')
    await store.toggleDone('todo-1')

    expect(repo.update).toHaveBeenCalledTimes(1)
    expect(store.items[0].is_done).toBe(true)

    pending.resolve(makeTodo({ is_done: true }))
    await first

    repo.update.mockResolvedValue(makeTodo())
    await store.toggleDone('todo-1')
    expect(repo.update).toHaveBeenCalledTimes(2)
    expect(store.items[0].is_done).toBe(false)
    expect(store.items[0].done_at).toBeNull()
  })

  test('rollt bei Fehler zurück und gibt den Mutex wieder frei', async () => {
    const store = useTodosStore()
    store.items.push(makeTodo({ is_done: true, done_at: '2026-01-05T00:00:00Z' }))
    repo.update.mockRejectedValueOnce(new Error('offline'))

    await expect(store.toggleDone('todo-1')).rejects.toThrow('offline')
    expect(store.items[0].is_done).toBe(true)
    expect(store.items[0].done_at).toBe('2026-01-05T00:00:00Z')

    repo.update.mockResolvedValue(makeTodo())
    await store.toggleDone('todo-1')
    expect(store.items[0].is_done).toBe(false)
  })
})

describe('updateTodo (claimen/bearbeiten)', () => {
  test('übernimmt sich selbst optimistisch als Zuständigen', async () => {
    const store = useTodosStore()
    store.items.push(makeTodo())
    const pending = deferred<TodoItem>()
    repo.update.mockReturnValue(pending.promise)

    const promise = store.updateTodo('todo-1', { assigned_to_user_id: USER_ID })
    expect(store.items[0].assigned_to_user_id).toBe(USER_ID)
    expect(repo.update).toHaveBeenCalledWith(HOUSEHOLD_ID, 'todo-1', { assigned_to_user_id: USER_ID })

    pending.resolve(makeTodo({ assigned_to_user_id: USER_ID }))
    await promise
    expect(store.items[0].assigned_to_user_id).toBe(USER_ID)
  })

  test('stellt bei Fehler den Snapshot wieder her', async () => {
    const store = useTodosStore()
    store.items.push(makeTodo({ title: 'Alt', assigned_to_user_id: 'user-2' }))
    repo.update.mockRejectedValue(new Error('403'))

    await expect(
      store.updateTodo('todo-1', { title: 'Neu', assigned_to_user_id: USER_ID }),
    ).rejects.toThrow('403')

    expect(store.items[0]).toMatchObject({ title: 'Alt', assigned_to_user_id: 'user-2' })
  })
})

describe('deleteTodo', () => {
  test('entfernt optimistisch und fügt bei Fehler an derselben Position wieder ein', async () => {
    const store = useTodosStore()
    store.items.push(makeTodo({ id: 'a' }), makeTodo({ id: 'b' }), makeTodo({ id: 'c' }))
    const pending = deferred<void>()
    repo.remove.mockReturnValue(pending.promise)

    const promise = store.deleteTodo('b')
    expect(store.items.map(i => i.id)).toEqual(['a', 'c'])
    expect(repo.remove).toHaveBeenCalledWith(HOUSEHOLD_ID, 'b')

    pending.reject(new Error('500'))
    await expect(promise).rejects.toThrow('500')
    expect(store.items.map(i => i.id)).toEqual(['a', 'b', 'c'])
  })

  test('ignoriert unbekannte IDs ohne Server-Call', async () => {
    const store = useTodosStore()
    await store.deleteTodo('unknown')
    expect(repo.remove).not.toHaveBeenCalled()
  })
})

describe('Reminders', () => {
  test('addReminder fügt sortiert ein und ersetzt den Temp-Reminder durch den Server-Reminder', async () => {
    const store = useTodosStore()
    store.items.push(makeTodo({ reminders: [makeReminder({ id: 'late', remind_at: '2026-03-01T09:00:00Z' })] }))
    const pending = deferred<TodoReminder>()
    repo.addReminder.mockReturnValue(pending.promise)

    const promise = store.addReminder('todo-1', '2026-02-01T09:00:00Z')
    expect(store.items[0].reminders.map(r => r.remind_at)).toEqual([
      '2026-02-01T09:00:00Z',
      '2026-03-01T09:00:00Z',
    ])

    pending.resolve(makeReminder({ id: 'server-rem', remind_at: '2026-02-01T09:00:00Z' }))
    await promise
    expect(store.items[0].reminders.map(r => r.id)).toEqual(['server-rem', 'late'])
  })

  test('addReminder entfernt den Temp-Reminder bei Fehler', async () => {
    const store = useTodosStore()
    store.items.push(makeTodo())
    repo.addReminder.mockRejectedValue(new Error('500'))

    await expect(store.addReminder('todo-1', '2026-02-01T09:00:00Z')).rejects.toThrow('500')
    expect(store.items[0].reminders).toEqual([])
  })

  test('deleteReminder stellt bei Fehler die vorherige Liste wieder her', async () => {
    const store = useTodosStore()
    const reminders = [makeReminder({ id: 'r1' }), makeReminder({ id: 'r2' })]
    store.items.push(makeTodo({ reminders }))
    repo.deleteReminder.mockRejectedValue(new Error('500'))

    await expect(store.deleteReminder('todo-1', 'r1')).rejects.toThrow('500')
    expect(store.items[0].reminders.map(r => r.id)).toEqual(['r1', 'r2'])
  })
})

describe('Socket-Handler', () => {
  test('todo_created ist idempotent — Server gewinnt', () => {
    const store = useTodosStore()
    store.handleTodoCreated(makeTodo({ title: 'v1' }))
    store.handleTodoCreated(makeTodo({ title: 'v2' }))

    expect(store.items).toHaveLength(1)
    expect(store.items[0].title).toBe('v2')
  })

  test('todo_updated ersetzt bestehende Todos und ignoriert unbekannte', () => {
    const store = useTodosStore()
    store.items.push(makeTodo())

    store.handleTodoUpdated(makeTodo({ is_done: true, done_at: '2026-01-05T00:00:00Z' }))
    store.handleTodoUpdated(makeTodo({ id: 'unknown' }))

    expect(store.items).toHaveLength(1)
    expect(store.items[0].is_done).toBe(true)
  })

  test('todo_deleted entfernt das Todo, mehrfaches Event ist harmlos', () => {
    const store = useTodosStore()
    store.items.push(makeTodo({ id: 'a' }), makeTodo({ id: 'b' }))

    store.handleTodoDeleted({ id: 'a' })
    store.handleTodoDeleted({ id: 'a' })

    expect(store.items.map(i => i.id)).toEqual(['b'])
  })
})
