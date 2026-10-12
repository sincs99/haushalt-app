/**
 * Finance-Store: Socket-Handler für Budget und Rechnungen (CASA-42) und Nachbuchen (PD-F4).
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { HOUSEHOLD_ID } from './helpers'

const { repo, auth } = vi.hoisted(() => ({
  repo: {
    getSummary: vi.fn(), getBudget: vi.fn(), upsertBudget: vi.fn(), fetchBills: vi.fn(),
    createBill: vi.fn(), updateBill: vi.fn(), removeBill: vi.fn(), bookBill: vi.fn(),
  },
  auth: { currentHouseholdId: null as string | null },
}))

vi.mock('../../repositories/financeRepository', () => ({ createOnlineFinanceRepository: () => repo }))
vi.mock('../../utils/apiErrors', () => ({ translateApiError: () => 'err' }))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { useFinanceStore } from '../finance'

const summary = (o: Record<string, unknown> = {}) => ({
  month: '2026-10-01', budget_rappen: 1000, total_spent_rappen: 400, remaining_rappen: 600,
  pending_bills: [{ id: 'b1', is_booked_this_month: false }], ...o,
}) as any
const budget = (month: string, amount = 2000) => ({ id: 'bud', month, amount_rappen: amount }) as any

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  vi.useFakeTimers()
  auth.currentHouseholdId = HOUSEHOLD_ID
})
afterEach(() => vi.useRealTimers())

describe('budget_updated / budget_deleted', () => {
  test('Budget eines anderen Monats überschreibt die Übersicht nicht', () => {
    const store = useFinanceStore()
    store.summary = summary()
    store.handleBudgetUpdated(budget('2026-11-01', 9999))
    expect(store.summary!.budget_rappen).toBe(1000)
    expect(store.budget).toBeNull()
  })

  test('Budget des angezeigten Monats aktualisiert Rest und Budget', () => {
    const store = useFinanceStore()
    store.summary = summary()
    store.handleBudgetUpdated(budget('2026-10-01', 2000))
    expect(store.summary!.budget_rappen).toBe(2000)
    expect(store.summary!.remaining_rappen).toBe(1600)
    expect(store.budget?.amount_rappen).toBe(2000)
  })

  test('budget_deleted für den angezeigten Monat entfernt das Budget', () => {
    const store = useFinanceStore()
    store.summary = summary()
    store.budget = budget('2026-10-01', 1000)
    store.handleBudgetDeleted({ month: '2026-11-01' })
    expect(store.summary!.budget_rappen).toBe(1000)
    store.handleBudgetDeleted({ month: '2026-10-01' })
    expect(store.summary!.budget_rappen).toBeNull()
    expect(store.summary!.remaining_rappen).toBeNull()
    expect(store.budget).toBeNull()
  })
})

describe('Rechnungs-Events', () => {
  test('created/updated/deleted laden die Übersicht (pending_bills) gebündelt nach', async () => {
    const store = useFinanceStore()
    store.summary = summary()
    repo.getSummary.mockResolvedValue(summary({ pending_bills: [] }))
    store.handleBillCreated({ id: 'b2' } as any)
    store.handleBillUpdated({ id: 'b2', active: false } as any)
    store.handleBillDeleted({ id: 'b1' })
    expect(repo.getSummary).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(300)
    expect(repo.getSummary).toHaveBeenCalledTimes(1)
    expect(store.summary!.pending_bills).toEqual([])
  })

  test('recurring_bill_booked markiert nur Buchungen des angezeigten Monats', () => {
    const store = useFinanceStore()
    store.summary = summary()
    store.handleBillBooked({ bill_id: 'b1', expense_id: 'e', booked_month: '2026-09-01' })
    expect(store.summary!.pending_bills[0].is_booked_this_month).toBe(false)
    store.handleBillBooked({ bill_id: 'b1', expense_id: 'e', booked_month: '2026-10-01' })
    expect(store.summary!.pending_bills[0].is_booked_this_month).toBe(true)
  })
})

test('bookBill mit Monat bucht nach (PD-F4)', async () => {
  const store = useFinanceStore()
  repo.bookBill.mockResolvedValue({ id: 'exp' })
  repo.getSummary.mockResolvedValue(summary())
  await store.bookBill('b1', 'anna', '2026-08-01')
  expect(repo.bookBill).toHaveBeenCalledWith(HOUSEHOLD_ID, 'b1', 'anna', '2026-08-01')
})

test('fetchBills lädt auch pausierte Rechnungen (Verwaltung)', async () => {
  const store = useFinanceStore()
  repo.fetchBills.mockResolvedValue([{ id: 'b1', active: false }])
  await store.fetchBills()
  expect(repo.fetchBills).toHaveBeenCalledWith(HOUSEHOLD_ID, true)
  expect(store.bills).toHaveLength(1)
})
