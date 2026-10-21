/**
 * Ausgaben-Store: Version/If-Match + Konflikt (PD-F7/CASA-09), Wiederherstellen (CASA-03),
 * „Mehr laden“ (CASA-23), veraltete Socket-Events, Verlauf gelöschter Ausgaben.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { Expense } from '../../types'

const { repo, auth, finance } = vi.hoisted(() => ({
  repo: {
    fetchAll: vi.fn(),
    get: vi.fn(),
    getBalances: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    restore: vi.fn(),
  },
  auth: { currentHouseholdId: 'h1' as string | null, user: { id: 'u1' } },
  finance: { fetchSummary: vi.fn() },
}))

vi.mock('../auth', () => ({ useAuthStore: () => auth }))
vi.mock('../finance', () => ({ useFinanceStore: () => finance }))
vi.mock('../../utils/apiErrors', () => ({ translateApiError: (e: any) => e?.response?.data?.detail?.code ?? 'err' }))
vi.mock('../../repositories/expensesRepository', () => ({ createOnlineExpensesRepository: () => repo }))
vi.mock('../../repositories/householdsRepository', () => ({
  createOnlineHouseholdsRepository: () => ({ fetchMembers: vi.fn() }),
}))

import { useExpensesStore, EXPENSES_PAGE_SIZE } from '../expenses'

function expense(over: Partial<Expense> = {}): Expense {
  return {
    id: 'e1',
    household_id: 'h1',
    description: 'Pizza',
    amount_rappen: 1000,
    currency: 'CHF',
    split_type: 'even',
    paid_by_user_id: 'u1',
    expense_date: '2026-10-01',
    created_at: '2026-10-01T10:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
    shares: [],
    category: null,
    recurring_bill_id: null,
    version: 1,
    ...over,
  }
}

const conflict = (current: Expense) => ({
  response: { status: 409, data: { detail: { code: 'EXPENSE_VERSION_CONFLICT', current } } },
})

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
  Object.values(repo).forEach(fn => fn.mockReset())
  repo.getBalances.mockResolvedValue({ balances: [] })
  finance.fetchSummary.mockReset().mockResolvedValue(undefined)
  auth.currentHouseholdId = 'h1'
})
afterEach(() => vi.useRealTimers())

describe('editExpense mit Version', () => {
  it('sendet die bekannte Version als If-Match', async () => {
    const s = useExpensesStore()
    s.expenses = [expense({ version: 4 })]
    repo.update.mockResolvedValue(expense({ version: 5, description: 'Neu' }))
    await s.editExpense('e1', { description: 'Neu' })
    expect(repo.update).toHaveBeenCalledWith('h1', 'e1', { description: 'Neu' }, 4)
    expect(s.expenses[0].version).toBe(5)
  })

  it('409: übernimmt den aktuellen Server-Stand und wirft weiter', async () => {
    const s = useExpensesStore()
    s.expenses = [expense({ version: 1 })]
    const current = expense({ version: 2, amount_rappen: 2500, updated_by_user_id: 'u2' })
    repo.update.mockRejectedValue(conflict(current))
    await expect(s.editExpense('e1', { amount_rappen: 1000 }, 1)).rejects.toBeDefined()
    expect(s.expenses[0].amount_rappen).toBe(2500)
    expect(s.error).toBe('EXPENSE_VERSION_CONFLICT')
  })

  it('EXPENSE_DELETED entfernt die Ausgabe aus der Liste', async () => {
    const s = useExpensesStore()
    s.expenses = [expense()]
    repo.update.mockRejectedValue({ response: { status: 409, data: { detail: { code: 'EXPENSE_DELETED' } } } })
    await expect(s.editExpense('e1', { description: 'x' })).rejects.toBeDefined()
    expect(s.expenses).toEqual([])
  })
})

describe('Socket-Events', () => {
  it('verwirft veraltete expense_updated-Events', () => {
    const s = useExpensesStore()
    s.expenses = [expense({ version: 3, description: 'Neu' })]
    s.handleExpenseUpdated(expense({ version: 2, description: 'Alt' }))
    expect(s.expenses[0].description).toBe('Neu')
  })

  it('sortiert neue/wiederhergestellte Ausgaben nach Datum ein', () => {
    const s = useExpensesStore()
    s.expenses = [expense({ id: 'b', expense_date: '2026-10-05' }), expense({ id: 'a', expense_date: '2026-09-01' })]
    s.handleExpenseCreated(expense({ id: 'm', expense_date: '2026-09-15' }))
    expect(s.expenses.map(e => e.id)).toEqual(['b', 'm', 'a'])
  })
})

describe('Löschen + Wiederherstellen (CASA-03)', () => {
  it('Undo nutzt den Restore-Endpunkt und behält den Rechnungsbezug', async () => {
    const s = useExpensesStore()
    const booked = expense({ recurring_bill_id: 'bill', booked_month: '2026-10-01' })
    s.expenses = [booked]
    repo.remove.mockResolvedValue(undefined)
    await s.removeExpense('e1')
    expect(s.expenses).toEqual([])

    repo.restore.mockResolvedValue({ ...booked, version: 3 })
    const restored = await s.restoreExpense('e1')
    expect(repo.restore).toHaveBeenCalledWith('h1', 'e1')
    expect(repo.create).not.toHaveBeenCalled()
    expect(restored?.recurring_bill_id).toBe('bill')
    expect(s.expenses.map(e => e.id)).toEqual(['e1'])
  })

  it('Restore-Fehler (Monat neu gebucht) wird weitergeworfen', async () => {
    const s = useExpensesStore()
    repo.restore.mockRejectedValue({ response: { status: 409, data: { detail: { code: 'BILL_ALREADY_BOOKED' } } } })
    await expect(s.restoreExpense('e1')).rejects.toBeDefined()
    expect(s.error).toBe('BILL_ALREADY_BOOKED')
  })

  it('Verlauf: fetchDeleted lädt gelöschte; Restore entfernt sie daraus', async () => {
    const s = useExpensesStore()
    repo.fetchAll.mockResolvedValue([expense({ deleted_at: '2026-10-02T10:00:00Z', deleted_by_user_id: 'u2' })])
    await s.fetchDeleted()
    expect(repo.fetchAll).toHaveBeenCalledWith('h1', { deleted: true, limit: EXPENSES_PAGE_SIZE })
    expect(s.deletedExpenses).toHaveLength(1)
    repo.restore.mockResolvedValue(expense())
    await s.restoreExpense('e1')
    expect(s.deletedExpenses).toEqual([])
  })
})

describe('Mehr laden (CASA-23)', () => {
  it('lädt seitenweise, überspringt Duplikate und erkennt das Ende', async () => {
    const s = useExpensesStore()
    const page1 = Array.from({ length: EXPENSES_PAGE_SIZE }, (_, i) =>
      expense({ id: `p1-${i}`, expense_date: '2026-10-01', created_at: `2026-10-01T10:${String(59 - (i % 60)).padStart(2, '0')}:00Z` }))
    repo.fetchAll.mockResolvedValueOnce(page1)
    await s.fetchExpenses()
    expect(s.hasMore).toBe(true)
    expect(repo.fetchAll).toHaveBeenLastCalledWith('h1', { limit: EXPENSES_PAGE_SIZE, offset: 0 })

    repo.fetchAll.mockResolvedValueOnce([page1[page1.length - 1], expense({ id: 'old', expense_date: '2026-01-01' })])
    await s.loadMore()
    expect(repo.fetchAll).toHaveBeenLastCalledWith('h1', { limit: EXPENSES_PAGE_SIZE, offset: EXPENSES_PAGE_SIZE })
    expect(s.expenses).toHaveLength(EXPENSES_PAGE_SIZE + 1)
    expect(s.expenses[s.expenses.length - 1].id).toBe('old')
    expect(s.hasMore).toBe(false)

    await s.loadMore() // Ende erreicht → kein weiterer Request
    expect(repo.fetchAll).toHaveBeenCalledTimes(2)
  })
})
