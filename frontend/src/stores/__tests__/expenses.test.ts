import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { Expense } from '../../types'

const { repo, householdRepo, auth } = vi.hoisted(() => ({
  repo: {
    fetchAll: vi.fn(),
    getBalances: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
  householdRepo: { fetchMembers: vi.fn() },
  auth: { currentHouseholdId: 'h1' as string | null, user: { id: 'u1' } },
}))

vi.mock('../auth', () => ({ useAuthStore: () => auth }))
vi.mock('../../repositories/expensesRepository', () => ({
  createOnlineExpensesRepository: () => repo,
}))
vi.mock('../../repositories/householdsRepository', () => ({
  createOnlineHouseholdsRepository: () => householdRepo,
}))

import { useExpensesStore } from '../expenses'

function expense(over: Partial<Expense> = {}): Expense {
  return {
    id: 'e1',
    household_id: 'h1',
    description: 'Groceries',
    amount_rappen: 1000,
    currency: 'CHF',
    split_type: 'even',
    paid_by_user_id: 'u1',
    expense_date: '2024-01-01',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    shares: [],
    category: null,
    recurring_bill_id: null,
    ...over,
  }
}

describe('expenses store', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    Object.values(repo).forEach(fn => fn.mockReset())
    householdRepo.fetchMembers.mockReset()
    repo.getBalances.mockResolvedValue({ balances: [] })
    auth.currentHouseholdId = 'h1'
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  describe('fetchExpenses', () => {
    it('loads expenses', async () => {
      repo.fetchAll.mockResolvedValue([expense()])
      const s = useExpensesStore()
      await s.fetchExpenses()
      expect(s.expenses).toHaveLength(1)
      expect(s.loading).toBe(false)
      expect(s.error).toBeNull()
    })

    it('sets a translated error, resets loading and rethrows on failure', async () => {
      repo.fetchAll.mockRejectedValue({ response: { data: { detail: 'Server says no' } } })
      const s = useExpensesStore()
      await expect(s.fetchExpenses()).rejects.toBeDefined()
      expect(s.error).toBe('Server says no')
      expect(s.loading).toBe(false)
    })

    it('does nothing without a household', async () => {
      auth.currentHouseholdId = null
      const s = useExpensesStore()
      await s.fetchExpenses()
      expect(repo.fetchAll).not.toHaveBeenCalled()
    })
  })

  it('fetchBalances swallows errors (non-critical)', async () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {})
    repo.getBalances.mockRejectedValue(new Error('x'))
    const s = useExpensesStore()
    await expect(s.fetchBalances()).resolves.toBeUndefined()
    expect(s.balances).toBeNull()
    spy.mockRestore()
  })

  describe('addExpense', () => {
    it('inserts at the front without duplicating and schedules a debounced balances refresh', async () => {
      const s = useExpensesStore()
      s.expenses = [expense({ id: 'old' })]
      repo.create.mockResolvedValue(expense({ id: 'new' }))
      await s.addExpense({} as any)
      await s.addExpense({} as any) // same id again → no duplicate
      expect(s.expenses.map(e => e.id)).toEqual(['new', 'old'])

      expect(repo.getBalances).not.toHaveBeenCalled()
      await vi.advanceTimersByTimeAsync(300)
      expect(repo.getBalances).toHaveBeenCalledTimes(1) // debounced into one call
    })

    it('sets error and rethrows on failure', async () => {
      repo.create.mockRejectedValue({ message: 'Bad', response: { data: {} } })
      const s = useExpensesStore()
      await expect(s.addExpense({} as any)).rejects.toBeDefined()
      expect(s.error).toBe('Bad')
      expect(s.expenses).toEqual([])
    })
  })

  it('editExpense replaces the expense with the server version', async () => {
    const s = useExpensesStore()
    s.expenses = [expense()]
    repo.update.mockResolvedValue(expense({ description: 'Edited' }))
    await s.editExpense('e1', {} as any)
    expect(s.expenses[0].description).toBe('Edited')
  })

  describe('removeExpense', () => {
    it('removes optimistically', async () => {
      const s = useExpensesStore()
      s.expenses = [expense({ id: 'a' }), expense({ id: 'b' })]
      repo.remove.mockResolvedValue(undefined)
      await s.removeExpense('a')
      expect(s.expenses.map(e => e.id)).toEqual(['b'])
    })

    it('restores at the original position and sets error on failure', async () => {
      const s = useExpensesStore()
      s.expenses = [expense({ id: 'a' }), expense({ id: 'b' }), expense({ id: 'c' })]
      repo.remove.mockRejectedValue({ response: { data: { detail: 'nope' } } })
      await expect(s.removeExpense('b')).rejects.toBeDefined()
      expect(s.expenses.map(e => e.id)).toEqual(['a', 'b', 'c'])
      expect(s.error).toBe('nope')
    })
  })

  describe('socket handlers', () => {
    it('handleExpenseCreated unshifts new and merges known expenses', () => {
      const s = useExpensesStore()
      s.handleExpenseCreated(expense({ id: 'a' }))
      s.handleExpenseCreated(expense({ id: 'b' }))
      s.handleExpenseCreated(expense({ id: 'a', description: 'Dup' }))
      expect(s.expenses.map(e => e.id)).toEqual(['b', 'a'])
      expect(s.expenses[1].description).toBe('Dup')
    })

    it('handleExpenseUpdated replaces known and inserts unknown expenses', () => {
      const s = useExpensesStore()
      s.expenses = [expense()]
      s.handleExpenseUpdated(expense({ description: 'New' }))
      s.handleExpenseUpdated(expense({ id: 'other' }))
      expect(s.expenses.map(e => e.id)).toEqual(['other', 'e1'])
      expect(s.expenses[1].description).toBe('New')
    })

    it('handleExpenseDeleted is idempotent and debounces balance refreshes', async () => {
      const s = useExpensesStore()
      s.expenses = [expense()]
      s.handleExpenseDeleted({ id: 'e1' })
      s.handleExpenseDeleted({ id: 'e1' })
      expect(s.expenses).toEqual([])
      await vi.advanceTimersByTimeAsync(300)
      expect(repo.getBalances).toHaveBeenCalledTimes(1)
    })
  })
})
