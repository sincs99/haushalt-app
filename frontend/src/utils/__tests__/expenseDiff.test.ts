/**
 * Teil-Updates des Ausgaben-Dialogs (CASA-09/CASA-38): nur geänderte Felder senden.
 */
import { describe, it, expect } from 'vitest'
import { diffExpense, type ExpenseFormValues } from '../expenseDiff'
import type { Expense } from '../../types'

function expense(over: Partial<Expense> = {}): Expense {
  return {
    id: 'e1',
    household_id: 'h1',
    description: 'Pizza',
    amount_rappen: 3000,
    currency: 'CHF',
    split_type: 'even',
    paid_by_user_id: 'anna',
    expense_date: '2026-10-01',
    created_at: '2026-10-01T10:00:00Z',
    updated_at: '2026-10-01T10:00:00Z',
    shares: [
      { user_id: 'anna', amount_rappen: 1500 },
      { user_id: 'ben', amount_rappen: 1500 },
    ],
    category: 'groceries',
    recurring_bill_id: null,
    version: 3,
    ...over,
  }
}

function form(e: Expense, over: Partial<ExpenseFormValues> = {}): ExpenseFormValues {
  return {
    description: e.description,
    amount_rappen: e.amount_rappen,
    paid_by_user_id: e.paid_by_user_id ?? '',
    expense_date: e.expense_date,
    category: e.category,
    split_type: e.split_type,
    participant_ids: e.shares.map(s => s.user_id),
    shares: e.shares,
    ...over,
  }
}

describe('diffExpense', () => {
  it('liefert ein leeres Payload, wenn nichts geändert wurde', () => {
    const e = expense()
    expect(diffExpense(e, form(e, { participant_ids: ['ben', 'anna'] }))).toEqual({})
  })

  it('sendet bei einer Beschreibungsänderung nur die Beschreibung (kein Betrag → kein Lost Update)', () => {
    const e = expense()
    expect(diffExpense(e, form(e, { description: '  Pizza Margherita ' }))).toEqual({ description: 'Pizza Margherita' })
  })

  it('leert die Kategorie mit explizitem null (CASA-38)', () => {
    const e = expense()
    expect(diffExpense(e, form(e, { category: null }))).toEqual({ category: null })
  })

  it('nur Betrag geändert (gleichmässig): keine Teilnehmer senden', () => {
    const e = expense()
    expect(diffExpense(e, form(e, { amount_rappen: 4000 }))).toEqual({ amount_rappen: 4000 })
  })

  it('Teilnehmer geändert (gleichmässig): participant_ids senden', () => {
    const e = expense()
    expect(diffExpense(e, form(e, { participant_ids: ['anna'] }))).toEqual({ participant_ids: ['anna'] })
  })

  it('individuell: Betrag geändert → Anteile mitsenden; 0-Anteile entfallen', () => {
    const e = expense({ split_type: 'custom' })
    const shares = [
      { user_id: 'anna', amount_rappen: 4000 },
      { user_id: 'ben', amount_rappen: 0 },
    ]
    expect(diffExpense(e, form(e, { amount_rappen: 4000, shares }))).toEqual({
      amount_rappen: 4000,
      shares: [{ user_id: 'anna', amount_rappen: 4000 }],
    })
  })

  it('individuell: unveränderte Anteile werden nicht gesendet', () => {
    const e = expense({ split_type: 'custom' })
    expect(diffExpense(e, form(e, { paid_by_user_id: 'ben' }))).toEqual({ paid_by_user_id: 'ben' })
  })

  it('Wechsel der Aufteilung sendet split_type mit Teilnehmern bzw. Anteilen', () => {
    const e = expense()
    const shares = [{ user_id: 'anna', amount_rappen: 3000 }]
    expect(diffExpense(e, form(e, { split_type: 'custom', shares }))).toEqual({ split_type: 'custom', shares })
    const c = expense({ split_type: 'custom' })
    expect(diffExpense(c, form(c, { split_type: 'even', participant_ids: ['anna', 'ben'] }))).toEqual({
      split_type: 'even',
      participant_ids: ['anna', 'ben'],
    })
  })

  it('Datum geändert', () => {
    const e = expense()
    expect(diffExpense(e, form(e, { expense_date: '2026-09-30' }))).toEqual({ expense_date: '2026-09-30' })
  })
})
