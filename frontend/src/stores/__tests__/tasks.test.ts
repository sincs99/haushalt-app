/**
 * Unit-Tests für den Tasks-Store (vereinheitlichte Aufgabenliste): Laden, Claim/Complete
 * mit Refetch, Socket-Invalidierung.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { deferred, HOUSEHOLD_ID } from './helpers'

const { repo, householdRepo, auth } = vi.hoisted(() => ({
  repo: { fetchTasks: vi.fn(), claimTodo: vi.fn(), completeChoreAssignment: vi.fn() },
  householdRepo: { fetchMembers: vi.fn() },
  auth: { currentHouseholdId: null as string | null },
}))

vi.mock('../../repositories/tasksRepository', () => ({ createOnlineTasksRepository: () => repo }))
vi.mock('../../repositories/householdsRepository', () => ({ createOnlineHouseholdsRepository: () => householdRepo }))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { useTasksStore } from '../tasks'

const task = (id: string) => ({ id }) as any

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  auth.currentHouseholdId = HOUSEHOLD_ID
})

test('fetchTasks setzt loading während des Requests und befüllt items', async () => {
  const store = useTasksStore()
  const pending = deferred<any[]>()
  repo.fetchTasks.mockReturnValue(pending.promise)
  const p = store.fetchTasks()
  expect(store.loading).toBe(true)
  pending.resolve([task('a')])
  await p
  expect(store.items).toEqual([task('a')])
  expect(store.loading).toBe(false)
})

test('fetchTasks-Fehler wirft weiter und setzt loading zurück; items bleiben', async () => {
  const store = useTasksStore()
  store.items = [task('a')]
  repo.fetchTasks.mockRejectedValue(new Error('x'))
  await expect(store.fetchTasks()).rejects.toThrow('x')
  expect(store.loading).toBe(false)
  expect(store.items).toEqual([task('a')])
})

test('fetchMembers lädt Mitglieder des aktiven Haushalts', async () => {
  const store = useTasksStore()
  householdRepo.fetchMembers.mockResolvedValue([{ user_id: 'u' }])
  await store.fetchMembers()
  expect(householdRepo.fetchMembers).toHaveBeenCalledWith(HOUSEHOLD_ID)
  expect(store.members).toHaveLength(1)
})

test('claimTask und completeChoreAssignment rufen das Repo und laden danach neu', async () => {
  const store = useTasksStore()
  repo.claimTodo.mockResolvedValue(undefined)
  repo.completeChoreAssignment.mockResolvedValue(undefined)
  repo.fetchTasks.mockResolvedValue([task('fresh')])
  await store.claimTask('t1')
  expect(repo.claimTodo).toHaveBeenCalledWith(HOUSEHOLD_ID, 't1')
  await store.completeChoreAssignment('a1')
  expect(repo.completeChoreAssignment).toHaveBeenCalledWith(HOUSEHOLD_ID, 'a1')
  expect(repo.fetchTasks).toHaveBeenCalledTimes(2)
  expect(store.items).toEqual([task('fresh')])
})

test('Fehler beim Claim: kein Refetch, Fehler wird weitergereicht', async () => {
  const store = useTasksStore()
  repo.claimTodo.mockRejectedValue(new Error('409'))
  await expect(store.claimTask('t1')).rejects.toThrow('409')
  expect(repo.fetchTasks).not.toHaveBeenCalled()
})

test('invalidate (Socket) löst einen Refetch aus', async () => {
  const store = useTasksStore()
  repo.fetchTasks.mockResolvedValue([task('x')])
  store.invalidate()
  await vi.waitFor(() => expect(store.items).toEqual([task('x')]))
})

test('ohne Haushalt: alle Aktionen sind No-Ops', async () => {
  auth.currentHouseholdId = null
  const store = useTasksStore()
  await store.fetchTasks(); await store.fetchMembers()
  await store.claimTask('t'); await store.completeChoreAssignment('a')
  for (const fn of [...Object.values(repo), householdRepo.fetchMembers]) expect(fn).not.toHaveBeenCalled()
})
