import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { TodoItem, TodoReminder } from '../../types'

const { repo, householdRepo, auth } = vi.hoisted(() => ({
  repo: {
    fetchAll: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    addReminder: vi.fn(),
    deleteReminder: vi.fn(),
  },
  householdRepo: { fetchMembers: vi.fn() },
  auth: { currentHouseholdId: 'h1' as string | null, user: { id: 'u1' } },
}))

vi.mock('../auth', () => ({ useAuthStore: () => auth }))
vi.mock('../../repositories/todosRepository', () => ({
  createOnlineTodosRepository: () => repo,
}))
vi.mock('../../repositories/householdsRepository', () => ({
  createOnlineHouseholdsRepository: () => householdRepo,
}))

import { useTodosStore } from '../todos'

function todo(over: Partial<TodoItem> = {}): TodoItem {
  return {
    id: 't1',
    household_id: 'h1',
    title: 'Task',
    description: null,
    assigned_to_user_id: null,
    due_date: null,
    is_done: false,
    created_by_user_id: 'u1',
    created_at: '2024-01-01T00:00:00Z',
    done_at: null,
    tags: [],
    reminders: [],
    ...over,
  }
}

function reminder(id: string, remind_at: string): TodoReminder {
  return { id, todo_id: 't1', remind_at, notified_at: null, created_at: '2024-01-01T00:00:00Z' }
}

describe('todos store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(repo).forEach(fn => fn.mockReset())
    householdRepo.fetchMembers.mockReset()
    auth.currentHouseholdId = 'h1'
  })

  it('fetchTodos loads items and resets loading on error', async () => {
    repo.fetchAll.mockResolvedValueOnce([todo()])
    const s = useTodosStore()
    await s.fetchTodos()
    expect(s.items).toHaveLength(1)
    expect(s.loading).toBe(false)

    repo.fetchAll.mockRejectedValueOnce(new Error('x'))
    await expect(s.fetchTodos()).rejects.toThrow()
    expect(s.loading).toBe(false)
  })

  it('fetchMembers stores the household members', async () => {
    householdRepo.fetchMembers.mockResolvedValue([{ user_id: 'u1' }])
    const s = useTodosStore()
    await s.fetchMembers()
    expect(s.members).toEqual([{ user_id: 'u1' }])
  })

  describe('addTodo', () => {
    it('swaps the optimistic temp todo for the server todo', async () => {
      const s = useTodosStore()
      repo.create.mockResolvedValue(todo({ id: 'srv' }))
      await s.addTodo('Task', undefined, undefined, undefined, ['a'])
      expect(s.items.map(i => i.id)).toEqual(['srv'])
      expect(repo.create).toHaveBeenCalledWith('h1', expect.objectContaining({ title: 'Task', tags: ['a'] }))
    })

    it('shows the temp todo while pending and rolls back on failure', async () => {
      const s = useTodosStore()
      let reject!: (e: Error) => void
      repo.create.mockReturnValue(new Promise((_, r) => (reject = r)))
      const p = s.addTodo('Task')
      expect(s.items).toHaveLength(1)
      expect(s.items[0].is_done).toBe(false)
      reject(new Error('fail'))
      await expect(p).rejects.toThrow('fail')
      expect(s.items).toHaveLength(0)
    })

    it('removes the temp todo when the socket already delivered the server todo', async () => {
      const s = useTodosStore()
      s.items = [todo({ id: 'srv' })]
      repo.create.mockResolvedValue(todo({ id: 'srv' }))
      await s.addTodo('Task')
      expect(s.items.map(i => i.id)).toEqual(['srv'])
    })
  })

  describe('toggleDone', () => {
    it('toggles optimistically and persists', async () => {
      const s = useTodosStore()
      s.items = [todo()]
      repo.update.mockResolvedValue(todo({ is_done: true }))
      const p = s.toggleDone('t1')
      expect(s.items[0].is_done).toBe(true)
      expect(s.items[0].done_at).not.toBeNull()
      await p
      expect(repo.update).toHaveBeenCalledWith('h1', 't1', { is_done: true })
    })

    it('rolls back on failure', async () => {
      const s = useTodosStore()
      s.items = [todo()]
      repo.update.mockRejectedValue(new Error('fail'))
      await expect(s.toggleDone('t1')).rejects.toThrow()
      expect(s.items[0].is_done).toBe(false)
      expect(s.items[0].done_at).toBeNull()
    })

    it('ignores concurrent toggles for the same todo', async () => {
      const s = useTodosStore()
      s.items = [todo()]
      let resolve!: () => void
      repo.update.mockReturnValue(new Promise<void>(r => (resolve = r)))
      const p = s.toggleDone('t1')
      await s.toggleDone('t1')
      expect(repo.update).toHaveBeenCalledTimes(1)
      resolve()
      await p
    })
  })

  describe('updateTodo', () => {
    it('applies changes optimistically', async () => {
      const s = useTodosStore()
      s.items = [todo()]
      repo.update.mockResolvedValue(todo({ title: 'New' }))
      const p = s.updateTodo('t1', { title: 'New' })
      expect(s.items[0].title).toBe('New')
      await p
    })

    it('rolls back to the snapshot on failure', async () => {
      const s = useTodosStore()
      s.items = [todo({ title: 'Old', description: 'd' })]
      repo.update.mockRejectedValue(new Error('fail'))
      await expect(s.updateTodo('t1', { title: 'New', description: null })).rejects.toThrow()
      expect(s.items[0].title).toBe('Old')
      expect(s.items[0].description).toBe('d')
    })
  })

  describe('deleteTodo', () => {
    it('restores at original position on failure', async () => {
      const s = useTodosStore()
      s.items = [todo({ id: 'a' }), todo({ id: 'b' }), todo({ id: 'c' })]
      repo.remove.mockRejectedValue(new Error('fail'))
      await expect(s.deleteTodo('b')).rejects.toThrow()
      expect(s.items.map(i => i.id)).toEqual(['a', 'b', 'c'])
    })

    it('removes on success', async () => {
      const s = useTodosStore()
      s.items = [todo({ id: 'a' }), todo({ id: 'b' })]
      repo.remove.mockResolvedValue(undefined)
      await s.deleteTodo('a')
      expect(s.items.map(i => i.id)).toEqual(['b'])
    })
  })

  describe('reminders', () => {
    it('addReminder inserts sorted and replaces the temp with the server reminder', async () => {
      const s = useTodosStore()
      s.items = [todo({ reminders: [reminder('r-late', '2030-01-02T00:00:00Z')] })]
      repo.addReminder.mockResolvedValue(reminder('r-srv', '2030-01-01T00:00:00Z'))
      const p = s.addReminder('t1', '2030-01-01T00:00:00Z')
      expect(s.items[0].reminders).toHaveLength(2)
      expect(s.items[0].reminders[0].remind_at).toBe('2030-01-01T00:00:00Z')
      await p
      expect(s.items[0].reminders.map(r => r.id)).toEqual(['r-srv', 'r-late'])
    })

    it('addReminder removes the temp reminder on failure', async () => {
      const s = useTodosStore()
      s.items = [todo()]
      repo.addReminder.mockRejectedValue(new Error('fail'))
      await expect(s.addReminder('t1', '2030-01-01T00:00:00Z')).rejects.toThrow()
      expect(s.items[0].reminders).toEqual([])
    })

    it('deleteReminder rolls back to the snapshot on failure', async () => {
      const s = useTodosStore()
      const r = reminder('r1', '2030-01-01T00:00:00Z')
      s.items = [todo({ reminders: [r] })]
      repo.deleteReminder.mockRejectedValue(new Error('fail'))
      await expect(s.deleteReminder('t1', 'r1')).rejects.toThrow()
      expect(s.items[0].reminders).toEqual([r])
    })

    it('deleteReminder removes on success', async () => {
      const s = useTodosStore()
      s.items = [todo({ reminders: [reminder('r1', '2030-01-01T00:00:00Z')] })]
      repo.deleteReminder.mockResolvedValue(undefined)
      await s.deleteReminder('t1', 'r1')
      expect(s.items[0].reminders).toEqual([])
    })
  })

  describe('socket handlers', () => {
    it('handleTodoCreated pushes new items and merges duplicates', () => {
      const s = useTodosStore()
      s.handleTodoCreated(todo())
      s.handleTodoCreated(todo({ title: 'Changed' }))
      expect(s.items).toHaveLength(1)
      expect(s.items[0].title).toBe('Changed')
    })

    it('handleTodoCreated does not push while an own create is pending (REST swap does it)', async () => {
      const s = useTodosStore()
      let resolve!: (t: TodoItem) => void
      repo.create.mockReturnValue(new Promise(r => (resolve = r)))
      const p = s.addTodo('Task')
      s.handleTodoCreated(todo({ id: 'srv' }))
      expect(s.items).toHaveLength(1) // only the temp item
      resolve(todo({ id: 'srv' }))
      await p
      expect(s.items.map(i => i.id)).toEqual(['srv'])
    })

    it('handleTodoUpdated replaces known items only', () => {
      const s = useTodosStore()
      s.items = [todo()]
      s.handleTodoUpdated(todo({ title: 'New' }))
      s.handleTodoUpdated(todo({ id: 'other' }))
      expect(s.items).toHaveLength(1)
      expect(s.items[0].title).toBe('New')
    })

    it('handleTodoDeleted is idempotent', () => {
      const s = useTodosStore()
      s.items = [todo()]
      s.handleTodoDeleted({ id: 't1' })
      s.handleTodoDeleted({ id: 't1' })
      expect(s.items).toEqual([])
    })
  })
})
