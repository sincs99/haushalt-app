import { parseAmountToRappen } from './money'
import type { ExpenseShare } from '../types'

/** Empty fields and explicit zero mean exclusion; any other invalid entry blocks saving. */
export function validateExpenseShares(values: Record<string, string>) {
  const shares: ExpenseShare[] = []
  const invalidIds: string[] = []
  let total = 0
  for (const [userId, value] of Object.entries(values)) {
    const normalized = value.trim().replace(',', '.')
    if (!normalized || /^(?:0+(?:\.0{0,2})?|\.0{1,2})$/.test(normalized)) continue
    const amount = parseAmountToRappen(value)
    if (amount === null || !Number.isSafeInteger(amount)) {
      invalidIds.push(userId)
      continue
    }
    total += amount
    shares.push({ user_id: userId, amount_rappen: amount })
  }
  return { shares, invalidIds, total, valid: invalidIds.length === 0 && Number.isSafeInteger(total) }
}
