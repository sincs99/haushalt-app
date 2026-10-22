import { describe, expect, it } from 'vitest'
import { expenseToDraft, mergeExpenseDraft, type ExpenseDraft } from '../expenseDraft'
import { validateExpenseShares } from '../expenseShares'
import type { Expense } from '../../types'

function draft(overrides: Partial<ExpenseDraft> = {}): ExpenseDraft {
  return {
    description: 'Original', amountText: '100.00', expenseDate: '2026-10-22',
    paidByUserId: 'anna', selectedCategory: 'groceries', splitType: 'even',
    participantIds: ['anna', 'ben'], customShares: { anna: '50.00', ben: '50.00' },
    ...overrides,
  }
}

describe('expense conflict resolution', () => {
  it('preserves local text while incorporating unrelated server updates', () => {
    const local = draft({ description: 'My detailed correction' })
    const latest = draft({ amountText: '150.00', expenseDate: '2026-10-21', selectedCategory: null, paidByUserId: 'ben' })
    expect(mergeExpenseDraft(draft(), local, latest)).toEqual({ ...latest, description: local.description })
    expect(local).toEqual(draft({ description: 'My detailed correction' }))
  })

  it('lets explicit keep-local choice resolve overlapping edits without losing unrelated server fields', () => {
    const local = draft({ description: 'My correction', amountText: '120.00' })
    const latest = draft({ description: 'Their correction', amountText: '200.00', paidByUserId: 'ben' })
    expect(mergeExpenseDraft(draft(), local, latest)).toEqual({ ...local, paidByUserId: 'ben' })
  })

  it('retains raw invalid edits made while the conflict is visible for subsequent validation', () => {
    expect(mergeExpenseDraft(draft(), draft({ amountText: 'unfinished' }), draft({ amountText: '200.00' })).amountText).toBe('unfinished')
  })

  it.each(['100', '100,00', ' 100.0 '])('does not overwrite an unrelated server amount after formatting-only edits: %s', amountText => {
    const local = draft({ description: 'My correction', amountText })
    const latest = draft({ amountText: '200.00' })
    expect(mergeExpenseDraft(draft(), local, latest)).toEqual({ ...latest, description: 'My correction' })
  })

  it('adopts server shares after formatting-only changes and exclusion-equivalent zero entries', () => {
    const original = draft({ splitType: 'custom', customShares: { anna: '50.00', ben: '50.00', chris: '' } })
    const local = { ...original, description: 'My correction', customShares: { anna: '50', ben: '50,00', chris: '0.00', dana: '' } }
    const latest = { ...original, customShares: { anna: '75.00', ben: '25.00' }, participantIds: ['anna', 'ben'] }
    expect(mergeExpenseDraft(original, local, latest)).toEqual({ ...latest, description: 'My correction' })
  })

  it('keeps invalid custom input made while reviewing the conflict for correction', () => {
    const original = draft({ splitType: 'custom' })
    const local = { ...original, customShares: { anna: '-10', ben: '50.00' } }
    const latest = { ...original, customShares: { anna: '75.00', ben: '25.00' } }
    expect(mergeExpenseDraft(original, local, latest).customShares).toEqual(local.customShares)
  })

  it('adopts a server split change when local edits did not touch the split', () => {
    const latest = draft({ splitType: 'custom', customShares: { anna: '100.00' }, participantIds: ['anna'] })
    expect(mergeExpenseDraft(draft(), draft({ description: 'Mine', participantIds: ['ben', 'anna'] }), latest)).toEqual({ ...latest, description: 'Mine' })
  })

  it('keeps locally changed split settings together when the server changed the amount', () => {
    const local = draft({ splitType: 'custom', customShares: { anna: '25.00', ben: '75.00' } })
    const merged = mergeExpenseDraft(draft(), local, draft({ amountText: '200.00' }))
    expect(merged.splitType).toBe('custom')
    expect(merged.customShares).toEqual(local.customShares)
    // User must correct the visible mismatch before submitting the merged draft.
    expect(validateExpenseShares(merged.customShares).total).not.toBe(Number(merged.amountText) * 100)
  })

  it('copies server data into a new draft without mutating the saved version', () => {
    const expense = { description: 'Original', amount_rappen: 10000, expense_date: '2026-10-22',
      paid_by_user_id: 'anna', category: 'groceries', split_type: 'even',
      shares: [{ user_id: 'anna', amount_rappen: 5000 }, { user_id: 'ben', amount_rappen: 5000 }],
    } as Expense
    const result = expenseToDraft(expense)
    expect(result).toEqual(draft())
    result.customShares.anna = '1'
    expect(expense.shares[0].amount_rappen).toBe(5000)
  })
})
