/**
 * Unit-Tests für den Settlements-Store: Laden, Create, Optimistic Delete mit Rollback,
 * Socket-Handler und debounced Balances-Refetch.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { HOUSEHOLD_ID } from './helpers'

const { repo, expensesStore, auth } = vi.hoisted(() => ({
  repo: { fetchAll: vi.fn(), create: vi.fn(), remove: vi.fn() },
  expensesStore: { fetchBalances: vi.fn() },
  auth: { currentHouseholdId: null as string | null },
}))

vi.mock('../../repositories/settlementsRepository', () => ({ createOnlineSettlementsRepository: () => repo }))
vi.mock('../../utils/apiErrors', () => ({ translateApiError: (e: any) => `translated:${e?.response?.data?.detail ?? e?.message}` }))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))
vi.mock('../expenses', () => ({ useExpensesStore: () => expensesStore }))

import { useSettlementsStore } from '../settlements'

const s = (id: string, o: Record<string, unknown> = {}) => ({ id, amount_rappen: 100, ...o }) as any
const err = { isAxiosError: true, response: { status: 400, data: { detail: 'x' } } }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  vi.useFakeTimers()
  auth.currentHouseholdId = HOUSEHOLD_ID
})
afterEach(() => vi.useRealTimers())

describe('Laden', () => {
  test('fetchAll füllt den State und setzt loading zurück', async () => {
    const store = useSettlementsStore()
    repo.fetchAll.mockResolvedValue([s('a')])
    await store.fetchAll()
    expect(store.settlements).toHaveLength(1)
    expect(store.loading).toBe(false)
  })

  test('fetchAll-Fehler setzt error, wirft und setzt loading zurück', async () => {
    const store = useSettlementsStore()
    repo.fetchAll.mockRejectedValue(err)
    await expect(store.fetchAll()).rejects.toBe(err)
    expect(store.error).toBeTruthy()
    expect(store.loading).toBe(false)
  })

  test('ohne Haushalt passiert nichts', async () => {
    auth.currentHouseholdId = null
    const store = useSettlementsStore()
    await store.fetchAll()
    expect(await store.create({} as any)).toBeUndefined()
    await store.remove('a')
    expect(repo.fetchAll).not.toHaveBeenCalled()
    expect(repo.create).not.toHaveBeenCalled()
    expect(repo.remove).not.toHaveBeenCalled()
  })
})

describe('create / remove', () => {
  test('create fügt vorne ein, ohne Duplikat bei schnellerem Socket, und refetcht Balances debounced', async () => {
    const store = useSettlementsStore()
    store.settlements = [s('old')]
    repo.create.mockResolvedValue(s('new'))
    await store.create({} as any)
    expect(store.settlements.map(x => x.id)).toEqual(['new', 'old'])
    await store.create({} as any) // gleiche ID → kein Duplikat
    expect(store.settlements).toHaveLength(2)

    expect(expensesStore.fetchBalances).not.toHaveBeenCalled()
    vi.advanceTimersByTime(300)
    expect(expensesStore.fetchBalances).toHaveBeenCalledTimes(1) // zwei Trigger → ein Refetch
    expect(expensesStore.fetchBalances).toHaveBeenCalledWith(HOUSEHOLD_ID)
  })

  test('create-Fehler: error gesetzt, State unverändert, kein Balances-Refetch', async () => {
    const store = useSettlementsStore()
    repo.create.mockRejectedValue(err)
    await expect(store.create({} as any)).rejects.toBe(err)
    expect(store.error).toBeTruthy()
    expect(store.settlements).toEqual([])
    vi.advanceTimersByTime(1000)
    expect(expensesStore.fetchBalances).not.toHaveBeenCalled()
  })

  test('remove entfernt optimistisch und rollt an alter Position zurück', async () => {
    const store = useSettlementsStore()
    store.settlements = [s('a'), s('b'), s('c')]
    repo.remove.mockRejectedValue(err)
    const p = store.remove('b')
    expect(store.settlements.map(x => x.id)).toEqual(['a', 'c'])
    await expect(p).rejects.toBe(err)
    expect(store.settlements.map(x => x.id)).toEqual(['a', 'b', 'c'])
    expect(store.error).toBeTruthy()

    repo.remove.mockResolvedValue(undefined)
    await store.remove('b')
    expect(store.settlements.map(x => x.id)).toEqual(['a', 'c'])
    vi.advanceTimersByTime(300)
    expect(expensesStore.fetchBalances).toHaveBeenCalledTimes(1)
  })

  test('Debounce ohne Haushalt zum Feuerzeitpunkt refetcht nichts', () => {
    const store = useSettlementsStore()
    store.handleSettlementDeleted({ id: 'x' })
    auth.currentHouseholdId = null
    vi.advanceTimersByTime(300)
    expect(expensesStore.fetchBalances).not.toHaveBeenCalled()
  })
})

describe('Socket-Handler', () => {
  test('created ist idempotent (Server gewinnt), deleted entfernt; beide triggern Balances', () => {
    const store = useSettlementsStore()
    store.handleSettlementCreated(s('a'))
    store.handleSettlementCreated(s('a', { amount_rappen: 999 }))
    expect(store.settlements).toHaveLength(1)
    expect(store.settlements[0].amount_rappen).toBe(999)
    store.handleSettlementDeleted({ id: 'a' })
    expect(store.settlements).toEqual([])
    vi.advanceTimersByTime(300)
    expect(expensesStore.fetchBalances).toHaveBeenCalledTimes(1)
  })
})
