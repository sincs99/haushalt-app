/**
 * Teil-Updates für Ausgaben (CASA-09, PD-F7): Der Bearbeiten-Dialog sendet nur Felder,
 * die der Nutzer tatsächlich geändert hat. Ein älterer Dialog überschreibt damit keine
 * Korrektur eines anderen Mitglieds an anderen Feldern (z. B. den Betrag); bei echten
 * Konflikten schützt zusätzlich die Version (If-Match → 409).
 */
import type { Expense, ExpenseShare, ExpenseUpdatePayload, SplitType } from '../types'

export interface ExpenseFormValues {
  description: string
  amount_rappen: number
  paid_by_user_id: string
  expense_date: string
  category: string | null
  split_type: SplitType
  /** Teilnehmer bei gleichmässiger Aufteilung */
  participant_ids: string[]
  /** Anteile bei individueller Aufteilung (Anteile mit 0 werden ignoriert) */
  shares: ExpenseShare[]
}

function sameSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  const set = new Set(a)
  return b.every(x => set.has(x))
}

function positiveShares(shares: ExpenseShare[]): Map<string, number> {
  return new Map(shares.filter(s => s.amount_rappen > 0).map(s => [s.user_id, s.amount_rappen]))
}

function sameShares(a: ExpenseShare[], b: ExpenseShare[]): boolean {
  const ma = positiveShares(a)
  const mb = positiveShares(b)
  if (ma.size !== mb.size) return false
  for (const [uid, amount] of ma) {
    if (mb.get(uid) !== amount) return false
  }
  return true
}

/**
 * Liefert nur die geänderten Felder gegenüber `original`.
 *
 * - Kategorie entfernt → `category: null` (CASA-38).
 * - Gleichmässig: Teilnehmer nur bei Änderung; nur der Betrag geändert → das Backend
 *   verteilt auf die bisherigen Teilnehmer.
 * - Individuell: Anteile, sobald sich Anteile oder Betrag geändert haben (das Backend
 *   verlangt sie dann, weil die Summe stimmen muss).
 * - Wechsel der Aufteilung: `split_type` plus Teilnehmer bzw. Anteile.
 */
export function diffExpense(original: Expense, form: ExpenseFormValues): ExpenseUpdatePayload {
  const payload: ExpenseUpdatePayload = {}
  const description = form.description.trim()
  if (description !== original.description) payload.description = description
  if (form.amount_rappen !== original.amount_rappen) payload.amount_rappen = form.amount_rappen
  if (form.paid_by_user_id && form.paid_by_user_id !== original.paid_by_user_id) {
    payload.paid_by_user_id = form.paid_by_user_id
  }
  if (form.expense_date && form.expense_date !== original.expense_date) {
    payload.expense_date = form.expense_date
  }
  if ((form.category ?? null) !== (original.category ?? null)) {
    payload.category = form.category ?? null
  }

  const amountChanged = payload.amount_rappen !== undefined
  if (form.split_type !== original.split_type) {
    payload.split_type = form.split_type
    if (form.split_type === 'even') payload.participant_ids = [...form.participant_ids]
    else payload.shares = form.shares.filter(s => s.amount_rappen > 0)
  } else if (form.split_type === 'even') {
    const originalParticipants = original.shares.map(s => s.user_id)
    if (!sameSet(form.participant_ids, originalParticipants)) {
      payload.participant_ids = [...form.participant_ids]
    }
  } else if (amountChanged || !sameShares(form.shares, original.shares)) {
    payload.shares = form.shares.filter(s => s.amount_rappen > 0)
  }
  return payload
}
