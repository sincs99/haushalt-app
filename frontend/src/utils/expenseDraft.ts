import type { Expense, SplitType } from '../types'
import { parseAmountToRappen } from './money'
import { validateExpenseShares } from './expenseShares'

export interface ExpenseDraft {
  description: string
  amountText: string
  expenseDate: string
  paidByUserId: string
  selectedCategory: string | null
  splitType: SplitType
  participantIds: string[]
  customShares: Record<string, string>
}

export function expenseToDraft(expense: Expense): ExpenseDraft {
  return {
    description: expense.description,
    amountText: (expense.amount_rappen / 100).toFixed(2),
    expenseDate: expense.expense_date,
    paidByUserId: expense.paid_by_user_id ?? '',
    selectedCategory: expense.category ?? null,
    splitType: expense.split_type,
    participantIds: expense.shares.map(s => s.user_id),
    customShares: Object.fromEntries(expense.shares.map(s => [s.user_id, (s.amount_rappen / 100).toFixed(2)])),
  }
}

function splitFingerprint(draft: ExpenseDraft): string {
  const parsed = validateExpenseShares(draft.customShares)
  return JSON.stringify([
    draft.splitType,
    draft.splitType === 'even'
      ? [...draft.participantIds].sort()
      : parsed.valid
        ? parsed.shares.map(share => [share.user_id, share.amount_rappen] as const).sort(([a], [b]) => a.localeCompare(b))
        : Object.entries(draft.customShares).sort(([a], [b]) => a.localeCompare(b)),
  ])
}

function sameAmount(a: string, b: string): boolean {
  const left = parseAmountToRappen(a)
  const right = parseAmountToRappen(b)
  // Invalid unfinished input must remain recoverable as entered.
  return left !== null && right !== null && Number.isSafeInteger(left) && Number.isSafeInteger(right)
    ? left === right
    : a === b
}

/** Merge only after explicit user choice. User edits win overlaps; unrelated server edits survive. */
export function mergeExpenseDraft(original: ExpenseDraft, local: ExpenseDraft, latest: ExpenseDraft): ExpenseDraft {
  const merged = { ...local, participantIds: [...local.participantIds], customShares: { ...local.customShares } }
  const fields = ['description', 'amountText', 'expenseDate', 'paidByUserId', 'selectedCategory'] as const
  for (const key of fields) {
    const unchanged = key === 'amountText'
      ? sameAmount(local.amountText, original.amountText)
      : local[key] === original[key]
    if (unchanged) Object.assign(merged, { [key]: latest[key] })
  }
  if (splitFingerprint(local) === splitFingerprint(original)) {
    merged.splitType = latest.splitType
    merged.participantIds = [...latest.participantIds]
    merged.customShares = { ...latest.customShares }
  }
  return merged
}
