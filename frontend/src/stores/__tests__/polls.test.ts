/**
 * Polls-Store: Essens-Abstimmung entscheiden auf belegtem Tag (PD-M1, CASA-19).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { repo, auth } = vi.hoisted(() => ({
  repo: {
    fetchAll: vi.fn(), fetchOne: vi.fn(), create: vi.fn(), vote: vi.fn(),
    decide: vi.fn(), mealDecide: vi.fn(), remove: vi.fn(),
  },
  auth: { currentHouseholdId: 'h1' as string | null, user: { id: 'u1' } },
}))

vi.mock('../auth', () => ({ useAuthStore: () => auth }))
vi.mock('../../repositories/pollsRepository', () => ({ createOnlinePollsRepository: () => repo }))

import { mealPlanOccupiedEntry, usePollsStore } from '../polls'

const poll = (o: Record<string, unknown> = {}) => ({
  id: 'p1', status: 'offen', poll_type: 'meal', options: [], ...o,
}) as any

beforeEach(() => {
  setActivePinia(createPinia())
  Object.values(repo).forEach(fn => fn.mockReset())
  auth.currentHouseholdId = 'h1'
})

describe('mealDecidePoll', () => {
  it('sendet replace nur nach Rückfrage', async () => {
    const store = usePollsStore()
    store.polls = [poll()]
    repo.mealDecide.mockResolvedValue(poll({ status: 'entschieden' }))

    await store.mealDecidePoll('p1', 'o1')
    expect(repo.mealDecide).toHaveBeenLastCalledWith('h1', 'p1', { option_id: 'o1' })
    expect(store.polls[0].status).toBe('entschieden')

    await store.mealDecidePoll('p1', 'o1', true)
    expect(repo.mealDecide).toHaveBeenLastCalledWith('h1', 'p1', { option_id: 'o1', replace: true })
  })

  it('409 MEAL_PLAN_OCCUPIED wird mit dem bestehenden Eintrag durchgereicht, Abstimmung bleibt offen', async () => {
    const store = usePollsStore()
    store.polls = [poll()]
    const existing = { id: 'e1', date: '2026-10-17', free_text: 'Fondue', recipe_id: null, recipe: null }
    const err = { response: { status: 409, data: { detail: { code: 'MEAL_PLAN_OCCUPIED', entry: existing } } } }
    repo.mealDecide.mockRejectedValue(err)

    await expect(store.mealDecidePoll('p1', 'o1')).rejects.toBe(err)
    expect(mealPlanOccupiedEntry(err)).toEqual(existing)
    expect(store.polls[0].status).toBe('offen')
  })
})

describe('mealPlanOccupiedEntry', () => {
  it('erkennt nur den passenden Fehler', () => {
    expect(mealPlanOccupiedEntry(new Error('x'))).toBeNull()
    expect(mealPlanOccupiedEntry({ response: { status: 409, data: { detail: { code: 'CONFLICT_RETRY' } } } })).toBeNull()
    expect(mealPlanOccupiedEntry({ response: { status: 400, data: { detail: { code: 'MEAL_PLAN_OCCUPIED' } } } })).toBeNull()
  })
})
