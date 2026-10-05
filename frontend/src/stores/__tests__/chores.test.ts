/**
 * Unit-Tests für den Chores-Store: Dedupe beim Anlegen, optimistisches
 * Löschen/Erledigen mit Rollback, Toggle-Mutex und idempotente Socket-Handler.
 *
 * Repositories und Auth-Store sind gemockt — keine HTTP-Calls.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { ChoreAssignmentInfo, ChoreInfo } from '../../types'
import { deferred, HOUSEHOLD_ID, USER_ID } from './helpers'

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
  householdRepo: {
    fetchMembers: vi.fn(),
  },
  auth: {
    currentHouseholdId: null as string | null,
    user: null as { id: string } | null,
  },
}))

vi.mock('../../repositories/choresRepository', () => ({
  createOnlineChoresRepository: () => repo,
}))

vi.mock('../../repositories/householdsRepository', () => ({
  createOnlineHouseholdsRepository: () => householdRepo,
}))

vi.mock('../auth', () => ({
  useAuthStore: () => auth,
}))

import { useChoresStore } from '../chores'

function makeChore(overrides: Partial<ChoreInfo> = {}): ChoreInfo {
  return {
    id: 'chore-1',
    household_id: HOUSEHOLD_ID,
    title: 'Bad putzen',
    description: null,
    recurrence: 'weekly',
    weekday: 0,
    day_of_month: null,
    rotation_order: [USER_ID, 'user-2'],
    next_rotation_index: 0,
    anchor_date: '2026-01-05',
    active: true,
    created_at: '2026-01-01T00:00:00Z',
    created_by_user_id: USER_ID,
    ...overrides,
  }
}

function makeAssignment(overrides: Partial<ChoreAssignmentInfo> = {}): ChoreAssignmentInfo {
  return {
    id: 'asg-1',
    household_id: HOUSEHOLD_ID,
    chore_id: 'chore-1',
    assigned_user_id: USER_ID,
    due_date: '2026-01-05',
    completed_at: null,
    completed_by_user_id: null,
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

describe('createChore / updateChore', () => {
  test('createChore fügt das Server-Chore ein, ohne Duplikat falls der Socket schneller war', async () => {
    const store = useChoresStore()
    const pending = deferred<ChoreInfo>()
    repo.createChore.mockReturnValue(pending.promise)
    const serverChore = makeChore()

    const promise = store.createChore({ title: 'Bad putzen', recurrence: 'weekly', rotation_order: [USER_ID] })
    store.handleChoreCreated(serverChore)
    pending.resolve(serverChore)
    await promise

    expect(store.chores).toEqual([serverChore])
  })

  test('updateChore lädt Assignments nur bei Schedule-Änderung neu', async () => {
    const store = useChoresStore()
    store.chores.push(makeChore())
    repo.updateChore.mockResolvedValue(makeChore({ title: 'Küche' }))
    repo.fetchAssignments.mockResolvedValue([])

    await store.updateChore('chore-1', { title: 'Küche' })
    expect(store.chores[0].title).toBe('Küche')
    expect(repo.fetchAssignments).not.toHaveBeenCalled()

    await store.updateChore('chore-1', { weekday: 3 })
    expect(repo.fetchAssignments).toHaveBeenCalledTimes(1)
  })
})

describe('removeChore', () => {
  test('entfernt Chore und zugehörige Assignments optimistisch', async () => {
    const store = useChoresStore()
    store.chores.push(makeChore(), makeChore({ id: 'chore-2' }))
    store.assignments.push(makeAssignment(), makeAssignment({ id: 'asg-2', chore_id: 'chore-2' }))
    repo.removeChore.mockResolvedValue(undefined)

    await store.removeChore('chore-1')

    expect(store.chores.map(c => c.id)).toEqual(['chore-2'])
    expect(store.assignments.map(a => a.id)).toEqual(['asg-2'])
  })

  test('stellt bei Fehler Chore und Assignments wieder her', async () => {
    const store = useChoresStore()
    store.chores.push(makeChore({ id: 'chore-0' }), makeChore(), makeChore({ id: 'chore-2' }))
    store.assignments.push(
      makeAssignment({ id: 'asg-a', due_date: '2026-01-05' }),
      makeAssignment({ id: 'asg-b', chore_id: 'chore-2', due_date: '2026-01-06' }),
      makeAssignment({ id: 'asg-c', due_date: '2026-01-12' }),
    )
    repo.removeChore.mockRejectedValue(new Error('500'))

    await expect(store.removeChore('chore-1')).rejects.toThrow('500')

    expect(store.chores.map(c => c.id)).toEqual(['chore-0', 'chore-1', 'chore-2'])
    expect(store.assignments.map(a => a.id)).toEqual(['asg-a', 'asg-b', 'asg-c'])
  })
})

describe('completeAssignment / uncompleteAssignment', () => {
  test('erledigt optimistisch und übernimmt danach die Server-Version', async () => {
    const store = useChoresStore()
    store.assignments.push(makeAssignment())
    const pending = deferred<ChoreAssignmentInfo>()
    repo.completeAssignment.mockReturnValue(pending.promise)

    const promise = store.completeAssignment('asg-1')
    expect(store.assignments[0].completed_at).not.toBeNull()
    expect(store.assignments[0].completed_by_user_id).toBe(USER_ID)

    const serverVersion = makeAssignment({ completed_at: '2026-01-05T10:00:00Z', completed_by_user_id: USER_ID })
    pending.resolve(serverVersion)
    await promise
    expect(store.assignments[0]).toEqual(serverVersion)
  })

  test('Toggle-Mutex: complete und uncomplete teilen sich die Sperre', async () => {
    const store = useChoresStore()
    store.assignments.push(makeAssignment())
    const pending = deferred<ChoreAssignmentInfo>()
    repo.completeAssignment.mockReturnValue(pending.promise)

    const first = store.completeAssignment('asg-1')
    await store.completeAssignment('asg-1')
    await store.uncompleteAssignment('asg-1')

    expect(repo.completeAssignment).toHaveBeenCalledTimes(1)
    expect(repo.uncompleteAssignment).not.toHaveBeenCalled()

    pending.resolve(makeAssignment({ completed_at: '2026-01-05T10:00:00Z', completed_by_user_id: USER_ID }))
    await first
  })

  test('uncompleteAssignment rollt bei Fehler auf den erledigten Zustand zurück', async () => {
    const store = useChoresStore()
    store.assignments.push(makeAssignment({ completed_at: '2026-01-05T10:00:00Z', completed_by_user_id: 'user-2' }))
    repo.uncompleteAssignment.mockRejectedValue(new Error('offline'))

    await expect(store.uncompleteAssignment('asg-1')).rejects.toThrow('offline')

    expect(store.assignments[0]).toMatchObject({
      completed_at: '2026-01-05T10:00:00Z',
      completed_by_user_id: 'user-2',
    })
  })
})

describe('Socket-Handler', () => {
  test('chore_created ist idempotent', () => {
    const store = useChoresStore()
    store.handleChoreCreated(makeChore({ title: 'v1' }))
    store.handleChoreCreated(makeChore({ title: 'v2' }))

    expect(store.chores).toHaveLength(1)
    expect(store.chores[0].title).toBe('v2')
  })

  test('chore_deleted entfernt auch die zugehörigen Assignments', () => {
    const store = useChoresStore()
    store.chores.push(makeChore())
    store.assignments.push(makeAssignment(), makeAssignment({ id: 'asg-2', chore_id: 'other' }))

    store.handleChoreDeleted({ id: 'chore-1' })

    expect(store.chores).toEqual([])
    expect(store.assignments.map(a => a.id)).toEqual(['asg-2'])
  })

  test('assignment_created fügt nach due_date sortiert ein und ist idempotent', () => {
    const store = useChoresStore()
    store.assignments.push(makeAssignment({ id: 'a', due_date: '2026-01-05' }), makeAssignment({ id: 'c', due_date: '2026-01-19' }))

    store.handleAssignmentCreated(makeAssignment({ id: 'b', due_date: '2026-01-12' }))
    store.handleAssignmentCreated(makeAssignment({ id: 'b', due_date: '2026-01-12', assigned_user_id: 'user-2' }))

    expect(store.assignments.map(a => a.id)).toEqual(['a', 'b', 'c'])
    expect(store.assignments[1].assigned_user_id).toBe('user-2')
  })

  test('assignment_updated ignoriert unbekannte Assignments', () => {
    const store = useChoresStore()
    store.assignments.push(makeAssignment())

    store.handleAssignmentUpdated(makeAssignment({ id: 'unknown' }))
    store.handleAssignmentUpdated(makeAssignment({ completed_at: '2026-01-05T10:00:00Z' }))

    expect(store.assignments).toHaveLength(1)
    expect(store.assignments[0].completed_at).toBe('2026-01-05T10:00:00Z')
  })
})
