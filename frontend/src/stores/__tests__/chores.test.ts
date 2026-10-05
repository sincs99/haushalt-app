import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { ChoreAssignmentInfo, ChoreInfo } from '../../types'

const { repo, householdRepo, auth } = vi.hoisted(() => ({
  repo: {
    fetchChores: vi.fn(),
    createChore: vi.fn(),
    updateChore: vi.fn(),
    removeChore: vi.fn(),
    fetchAssignments: vi.fn(),
    completeAssignment: vi.fn(),
    uncompleteAssignment: vi.fn(),
    reassignAssignment: vi.fn(),
  },
  householdRepo: { fetchMembers: vi.fn() },
  auth: { currentHouseholdId: 'h1' as string | null, user: { id: 'u1' } },
}))

vi.mock('../auth', () => ({ useAuthStore: () => auth }))
vi.mock('../../repositories/choresRepository', () => ({
  createOnlineChoresRepository: () => repo,
}))
vi.mock('../../repositories/householdsRepository', () => ({
  createOnlineHouseholdsRepository: () => householdRepo,
}))

import { useChoresStore } from '../chores'

function chore(over: Partial<ChoreInfo> = {}): ChoreInfo {
  return {
    id: 'c1',
    household_id: 'h1',
    title: 'Vacuum',
    description: null,
    recurrence: 'weekly',
    weekday: 0,
    day_of_month: null,
    rotation_order: ['u1'],
    next_rotation_index: 0,
    anchor_date: '2024-01-01',
    active: true,
    created_at: '2024-01-01T00:00:00Z',
    created_by_user_id: 'u1',
    ...over,
  } as ChoreInfo
}

function assignment(over: Partial<ChoreAssignmentInfo> = {}): ChoreAssignmentInfo {
  return {
    id: 'a1',
    household_id: 'h1',
    chore_id: 'c1',
    assigned_user_id: 'u1',
    due_date: '2024-01-01',
    completed_at: null,
    completed_by_user_id: null,
    created_at: '2024-01-01T00:00:00Z',
    ...over,
  }
}

describe('chores store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(repo).forEach(fn => fn.mockReset())
    householdRepo.fetchMembers.mockReset()
    auth.currentHouseholdId = 'h1'
  })

  it('fetchChores / fetchAssignments load data and reset loading', async () => {
    repo.fetchChores.mockResolvedValue([chore()])
    repo.fetchAssignments.mockResolvedValue([assignment()])
    const s = useChoresStore()
    await s.fetchChores()
    await s.fetchAssignments({ from: '2024-01-01' })
    expect(s.chores).toHaveLength(1)
    expect(s.assignments).toHaveLength(1)
    expect(s.loading).toBe(false)
    expect(repo.fetchAssignments).toHaveBeenCalledWith('h1', { from: '2024-01-01' })
  })

  it('fetchChores resets loading on failure', async () => {
    repo.fetchChores.mockRejectedValue(new Error('x'))
    const s = useChoresStore()
    await expect(s.fetchChores()).rejects.toThrow()
    expect(s.loading).toBe(false)
  })

  it('createChore dedupes when the socket event was faster', async () => {
    const s = useChoresStore()
    s.handleChoreCreated(chore())
    repo.createChore.mockResolvedValue(chore({ title: 'Server' }))
    const created = await s.createChore({} as any)
    expect(created?.title).toBe('Server')
    expect(s.chores).toHaveLength(1)
    expect(s.chores[0].title).toBe('Server')
  })

  describe('updateChore', () => {
    it('replaces the chore and refetches assignments only on schedule changes', async () => {
      const s = useChoresStore()
      s.chores = [chore()]
      repo.fetchAssignments.mockResolvedValue([])
      repo.updateChore.mockResolvedValue(chore({ title: 'New' }))
      await s.updateChore('c1', { title: 'New' } as any)
      expect(s.chores[0].title).toBe('New')
      expect(repo.fetchAssignments).not.toHaveBeenCalled()
      await s.updateChore('c1', { weekday: 2 } as any)
      expect(repo.fetchAssignments).toHaveBeenCalledTimes(1)
    })
  })

  describe('removeChore', () => {
    it('removes the chore and its assignments optimistically', async () => {
      const s = useChoresStore()
      s.chores = [chore()]
      s.assignments = [assignment(), assignment({ id: 'a2', chore_id: 'other' })]
      repo.removeChore.mockResolvedValue(undefined)
      await s.removeChore('c1')
      expect(s.chores).toEqual([])
      expect(s.assignments.map(a => a.id)).toEqual(['a2'])
    })

    it('restores the chore at its position on failure', async () => {
      const s = useChoresStore()
      s.chores = [chore({ id: 'x' }), chore({ id: 'c1' }), chore({ id: 'y' })]
      repo.removeChore.mockRejectedValue(new Error('fail'))
      await expect(s.removeChore('c1')).rejects.toThrow('fail')
      expect(s.chores.map(c => c.id)).toEqual(['x', 'c1', 'y'])
    })
  })

  describe('completeAssignment', () => {
    it('marks complete optimistically and lets the server response win', async () => {
      const s = useChoresStore()
      s.assignments = [assignment()]
      let resolve!: (a: ChoreAssignmentInfo) => void
      repo.completeAssignment.mockReturnValue(new Promise(r => (resolve = r)))
      const p = s.completeAssignment('a1')
      expect(s.assignments[0].completed_at).not.toBeNull()
      expect(s.assignments[0].completed_by_user_id).toBe('u1')
      resolve(assignment({ completed_at: '2024-02-02T00:00:00Z', completed_by_user_id: 'u1' }))
      await p
      expect(s.assignments[0].completed_at).toBe('2024-02-02T00:00:00Z')
    })

    it('rolls back on failure', async () => {
      const s = useChoresStore()
      s.assignments = [assignment()]
      repo.completeAssignment.mockRejectedValue(new Error('fail'))
      await expect(s.completeAssignment('a1')).rejects.toThrow()
      expect(s.assignments[0].completed_at).toBeNull()
      expect(s.assignments[0].completed_by_user_id).toBeNull()
    })

    it('ignores concurrent calls for the same assignment', async () => {
      const s = useChoresStore()
      s.assignments = [assignment()]
      let resolve!: (a: ChoreAssignmentInfo) => void
      repo.completeAssignment.mockReturnValue(new Promise(r => (resolve = r)))
      const p = s.completeAssignment('a1')
      await s.completeAssignment('a1')
      await s.uncompleteAssignment('a1')
      expect(repo.completeAssignment).toHaveBeenCalledTimes(1)
      expect(repo.uncompleteAssignment).not.toHaveBeenCalled()
      resolve(assignment({ completed_at: 'x' }))
      await p
    })
  })

  describe('uncompleteAssignment', () => {
    const done = () => assignment({ completed_at: '2024-01-01T10:00:00Z', completed_by_user_id: 'u2' })

    it('clears completion optimistically', async () => {
      const s = useChoresStore()
      s.assignments = [done()]
      repo.uncompleteAssignment.mockResolvedValue(assignment())
      const p = s.uncompleteAssignment('a1')
      expect(s.assignments[0].completed_at).toBeNull()
      await p
      expect(s.assignments[0].completed_by_user_id).toBeNull()
    })

    it('rolls back to previous completion on failure', async () => {
      const s = useChoresStore()
      s.assignments = [done()]
      repo.uncompleteAssignment.mockRejectedValue(new Error('fail'))
      await expect(s.uncompleteAssignment('a1')).rejects.toThrow()
      expect(s.assignments[0].completed_at).toBe('2024-01-01T10:00:00Z')
      expect(s.assignments[0].completed_by_user_id).toBe('u2')
    })
  })

  it('reassignAssignment replaces with the server version', async () => {
    const s = useChoresStore()
    s.assignments = [assignment()]
    repo.reassignAssignment.mockResolvedValue(assignment({ assigned_user_id: 'u2' }))
    await s.reassignAssignment('a1', 'u2')
    expect(s.assignments[0].assigned_user_id).toBe('u2')
  })

  describe('socket handlers', () => {
    it('chore created/updated/deleted are idempotent merges', () => {
      const s = useChoresStore()
      s.handleChoreCreated(chore())
      s.handleChoreCreated(chore({ title: 'Dup' }))
      expect(s.chores).toHaveLength(1)
      expect(s.chores[0].title).toBe('Dup')

      s.handleChoreUpdated(chore({ title: 'Upd' }))
      s.handleChoreUpdated(chore({ id: 'unknown' }))
      expect(s.chores).toHaveLength(1)
      expect(s.chores[0].title).toBe('Upd')

      s.assignments = [assignment()]
      s.handleChoreDeleted({ id: 'c1' })
      s.handleChoreDeleted({ id: 'c1' })
      expect(s.chores).toEqual([])
      expect(s.assignments).toEqual([])
    })

    it('handleAssignmentCreated dedupes and keeps due_date order', () => {
      const s = useChoresStore()
      s.handleAssignmentCreated(assignment({ id: 'late', due_date: '2024-03-01' }))
      s.handleAssignmentCreated(assignment({ id: 'early', due_date: '2024-01-01' }))
      s.handleAssignmentCreated(assignment({ id: 'early', due_date: '2024-01-01' }))
      expect(s.assignments.map(a => a.id)).toEqual(['early', 'late'])
    })

    it('handleAssignmentUpdated only replaces known assignments', () => {
      const s = useChoresStore()
      s.assignments = [assignment()]
      s.handleAssignmentUpdated(assignment({ completed_at: 'x' }))
      s.handleAssignmentUpdated(assignment({ id: 'unknown' }))
      expect(s.assignments).toHaveLength(1)
      expect(s.assignments[0].completed_at).toBe('x')
    })
  })
})
