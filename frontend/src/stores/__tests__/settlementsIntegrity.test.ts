/**
 * Settlements-Store: Client-ID (Idempotenz, CASA-08), Plausibilitätsprüfung (PD-F3),
 * Wiederherstellen und „Mehr laden“.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { HOUSEHOLD_ID } from './helpers'

const { repo, expensesStore, auth } = vi.hoisted(() => ({
  repo: { fetchAll: vi.fn(), create: vi.fn(), remove: vi.fn(), restore: vi.fn(), check: vi.fn() },
  expensesStore: { fetchBalances: vi.fn() },
  auth: { currentHouseholdId: null as string | null },
}))

vi.mock('../../repositories/settlementsRepository', () => ({ createOnlineSettlementsRepository: () => repo }))
vi.mock('../../utils/apiErrors', () => ({ translateApiError: () => 'err' }))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))
vi.mock('../expenses', () => ({ useExpensesStore: () => expensesStore }))

import { useSettlementsStore, SETTLEMENTS_PAGE_SIZE } from '../settlements'

const s = (id: string, o: Record<string, unknown> = {}) => ({ id, amount_rappen: 100, ...o }) as any
const payload = { from_user_id: 'ben', to_user_id: 'anna', amount_rappen: 2500 }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  vi.useFakeTimers()
  auth.currentHouseholdId = HOUSEHOLD_ID
})
afterEach(() => vi.useRealTimers())

test('create erzeugt eine Client-ID; eine vorgegebene ID bleibt erhalten (Retry)', async () => {
  const store = useSettlementsStore()
  repo.create.mockImplementation(async (_h: string, p: any) => s(p.id))
  await store.create(payload)
  const generated = repo.create.mock.calls[0][1].id
  expect(generated).toMatch(/^[0-9a-f-]{36}$/)

  await store.create({ ...payload, id: 'fixed-id' })
  await store.create({ ...payload, id: 'fixed-id' })
  expect(repo.create.mock.calls[1][1].id).toBe('fixed-id')
  // Server liefert beim Retry denselben Ausgleich → kein Duplikat in der Liste
  expect(store.settlements.filter(x => x.id === 'fixed-id')).toHaveLength(1)
})

test('check reicht die Warnungen des Servers durch', async () => {
  const store = useSettlementsStore()
  repo.check.mockResolvedValue({ warnings: ['DUPLICATE_RECENT'], open_debt_rappen: 0 })
  expect(await store.check(payload)).toEqual({ warnings: ['DUPLICATE_RECENT'], open_debt_rappen: 0 })
  expect(repo.check).toHaveBeenCalledWith(HOUSEHOLD_ID, payload)
})

test('Undo nach Löschen nutzt restore statt eines neuen Ausgleichs', async () => {
  const store = useSettlementsStore()
  store.settlements = [s('a')]
  repo.remove.mockResolvedValue(undefined)
  await store.remove('a')
  expect(store.settlements).toEqual([])
  repo.restore.mockResolvedValue(s('a'))
  await store.restore('a')
  expect(repo.create).not.toHaveBeenCalled()
  expect(store.settlements.map(x => x.id)).toEqual(['a'])
  await vi.advanceTimersByTimeAsync(300)
  expect(expensesStore.fetchBalances).toHaveBeenCalled()
})

test('Verlauf: gelöschte laden; Wiederherstellung per Socket entfernt sie daraus', async () => {
  const store = useSettlementsStore()
  repo.fetchAll.mockResolvedValue([s('a', { deleted_at: '2026-10-01T10:00:00Z' })])
  await store.fetchDeleted()
  expect(repo.fetchAll).toHaveBeenCalledWith(HOUSEHOLD_ID, { deleted: true, limit: SETTLEMENTS_PAGE_SIZE })
  store.handleSettlementCreated(s('a'))
  expect(store.deletedSettlements).toEqual([])
  expect(store.settlements.map(x => x.id)).toEqual(['a'])
})

test('Mehr laden hängt die nächste Seite an', async () => {
  const store = useSettlementsStore()
  repo.fetchAll.mockResolvedValueOnce(Array.from({ length: SETTLEMENTS_PAGE_SIZE }, (_, i) => s(`p${i}`)))
  await store.fetchAll()
  expect(store.hasMore).toBe(true)
  repo.fetchAll.mockResolvedValueOnce([s('old')])
  await store.loadMore()
  expect(repo.fetchAll).toHaveBeenLastCalledWith(HOUSEHOLD_ID, { limit: SETTLEMENTS_PAGE_SIZE, offset: SETTLEMENTS_PAGE_SIZE })
  expect(store.settlements).toHaveLength(SETTLEMENTS_PAGE_SIZE + 1)
  expect(store.hasMore).toBe(false)
})
