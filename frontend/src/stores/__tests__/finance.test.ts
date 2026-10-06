/**
 * Unit-Tests für den Finance-Store: Summary/Budget/Bills, Fehlerpfade, Socket-Handler.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { deferred, HOUSEHOLD_ID } from './helpers'

const { repo, auth } = vi.hoisted(() => ({
  repo: {
    getSummary: vi.fn(), getBudget: vi.fn(), upsertBudget: vi.fn(), fetchBills: vi.fn(),
    createBill: vi.fn(), updateBill: vi.fn(), removeBill: vi.fn(), bookBill: vi.fn(),
  },
  auth: { currentHouseholdId: null as string | null },
}))

vi.mock('../../repositories/financeRepository', () => ({ createOnlineFinanceRepository: () => repo }))
vi.mock('../../utils/apiErrors', () => ({ translateApiError: (e: any) => `translated:${e?.response?.data?.detail ?? e?.message}` }))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { useFinanceStore } from '../finance'

const bill = (o: Record<string, unknown> = {}) => ({ id: 'b1', name: 'Miete', ...o }) as any
const budget = (amount = 1000) => ({ id: 'bud', amount_rappen: amount }) as any
const summary = (o: Record<string, unknown> = {}) => ({
  budget_rappen: 1000, total_spent_rappen: 400, remaining_rappen: 600,
  pending_bills: [{ id: 'b1', is_booked_this_month: false }], ...o,
}) as any
const apiError = (detail: string) => ({ isAxiosError: true, response: { status: 400, data: { detail } } })

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  auth.currentHouseholdId = HOUSEHOLD_ID
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

describe('Laden', () => {
  test('fetchSummary setzt loading und State; nutzt explizite Household-ID', async () => {
    const store = useFinanceStore()
    const pending = deferred<any>()
    repo.getSummary.mockReturnValue(pending.promise)
    const p = store.fetchSummary('other-hh')
    expect(store.loading).toBe(true)
    pending.resolve(summary())
    await p
    expect(repo.getSummary).toHaveBeenCalledWith('other-hh')
    expect(store.summary).toBeTruthy()
    expect(store.loading).toBe(false)
  })

  test('fetchSummary-Fehler landet in error statt zu werfen', async () => {
    const store = useFinanceStore()
    repo.getSummary.mockRejectedValue(apiError('boom'))
    await store.fetchSummary()
    expect(store.error).toBeTruthy()
    expect(store.loading).toBe(false)
    repo.getSummary.mockResolvedValue(summary())
    await store.fetchSummary()
    expect(store.error).toBeNull()
  })

  test('fetchBudget/fetchBills schlucken Fehler und behalten den alten State', async () => {
    const store = useFinanceStore()
    store.bills = [bill()]
    repo.fetchBills.mockRejectedValue(new Error('x'))
    repo.getBudget.mockRejectedValue(new Error('x'))
    await store.fetchBills()
    await store.fetchBudget(undefined, '2026-03')
    expect(store.bills).toHaveLength(1)
    expect(store.budget).toBeNull()
    repo.fetchBills.mockResolvedValue([bill(), bill({ id: 'b2' })])
    repo.getBudget.mockResolvedValue(budget())
    await store.fetchBills()
    await store.fetchBudget(undefined, '2026-03')
    expect(store.bills).toHaveLength(2)
    expect(repo.getBudget).toHaveBeenLastCalledWith(HOUSEHOLD_ID, '2026-03')
  })

  test('ohne Haushalt: keine Repository-Aufrufe', async () => {
    auth.currentHouseholdId = null
    const store = useFinanceStore()
    await store.fetchSummary(); await store.fetchBudget(); await store.fetchBills()
    expect(await store.upsertBudget({} as any)).toBeUndefined()
    expect(await store.createBill({} as any)).toBeUndefined()
    expect(await store.updateBill('b1', {})).toBeUndefined()
    expect(await store.removeBill('b1')).toBeUndefined()
    expect(await store.bookBill('b1')).toBeUndefined()
    for (const fn of Object.values(repo)) expect(fn).not.toHaveBeenCalled()
  })
})

describe('Mutationen', () => {
  test('upsertBudget setzt Budget und lädt die Summary nach', async () => {
    const store = useFinanceStore()
    repo.upsertBudget.mockResolvedValue(budget(2000))
    repo.getSummary.mockResolvedValue(summary())
    await store.upsertBudget({ amount_rappen: 2000 } as any)
    expect(store.budget?.amount_rappen).toBe(2000)
    expect(repo.getSummary).toHaveBeenCalledWith(HOUSEHOLD_ID)
  })

  test('Fehler bei upsertBudget/createBill/updateBill/removeBill/bookBill setzen error und werfen', async () => {
    const store = useFinanceStore()
    store.bills = [bill()]
    const err = apiError('nope')
    repo.upsertBudget.mockRejectedValue(err)
    repo.createBill.mockRejectedValue(err)
    repo.updateBill.mockRejectedValue(err)
    repo.removeBill.mockRejectedValue(err)
    repo.bookBill.mockRejectedValue(err)
    await expect(store.upsertBudget({} as any)).rejects.toBe(err)
    await expect(store.createBill({} as any)).rejects.toBe(err)
    await expect(store.updateBill('b1', {})).rejects.toBe(err)
    await expect(store.removeBill('b1')).rejects.toBe(err)
    await expect(store.bookBill('b1')).rejects.toBe(err)
    expect(store.error).toBeTruthy()
    expect(store.bills).toHaveLength(1) // kein Verlust bei Fehler
  })

  test('createBill/updateBill/removeBill aktualisieren die Liste erst nach Erfolg', async () => {
    const store = useFinanceStore()
    repo.createBill.mockResolvedValue(bill())
    await store.createBill({} as any)
    expect(store.bills).toHaveLength(1)
    repo.updateBill.mockResolvedValue(bill({ name: 'Neu' }))
    await store.updateBill('b1', { name: 'Neu' } as any)
    await store.updateBill('unknown', {})
    expect(store.bills.map(b => b.name)).toEqual(['Neu'])
    repo.removeBill.mockResolvedValue(undefined)
    await store.removeBill('b1')
    expect(store.bills).toEqual([])
  })

  test('bookBill lädt die Summary nach und liefert die Ausgabe', async () => {
    const store = useFinanceStore()
    repo.bookBill.mockResolvedValue({ id: 'exp' })
    repo.getSummary.mockResolvedValue(summary())
    expect(await store.bookBill('b1')).toEqual({ id: 'exp' })
    expect(repo.getSummary).toHaveBeenCalled()
  })
})

describe('Socket-Handler', () => {
  test('handleBudgetUpdated aktualisiert Budget und Rest in der Summary', () => {
    const store = useFinanceStore()
    store.handleBudgetUpdated(budget(500)) // ohne Summary: kein Fehler
    expect(store.budget?.amount_rappen).toBe(500)
    store.summary = summary()
    store.handleBudgetUpdated(budget(1500))
    expect(store.summary?.budget_rappen).toBe(1500)
    expect(store.summary?.remaining_rappen).toBe(1100)
  })

  test('Bill created/updated/deleted sind idempotent (Upsert)', () => {
    const store = useFinanceStore()
    store.handleBillCreated(bill())
    store.handleBillCreated(bill({ name: 'X' }))
    expect(store.bills).toHaveLength(1)
    store.handleBillUpdated(bill({ name: 'Y' }))
    store.handleBillUpdated(bill({ id: 'b2' })) // unbekannt → eingefügt
    expect(store.bills.map(b => b.name)).toEqual(['Y', 'Miete'])
    store.handleBillDeleted({ id: 'b1' })
    expect(store.bills.map(b => b.id)).toEqual(['b2'])
  })

  test('handleBillBooked markiert die Rechnung in der Summary', () => {
    const store = useFinanceStore()
    store.handleBillBooked({ bill_id: 'b1', expense_id: 'e' }) // ohne Summary
    store.summary = summary()
    store.handleBillBooked({ bill_id: 'unknown', expense_id: 'e' })
    expect(store.summary!.pending_bills[0].is_booked_this_month).toBe(false)
    store.handleBillBooked({ bill_id: 'b1', expense_id: 'e' })
    expect(store.summary!.pending_bills[0].is_booked_this_month).toBe(true)
  })
})
