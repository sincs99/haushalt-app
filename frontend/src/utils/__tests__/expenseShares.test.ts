import { describe, expect, it } from 'vitest'
import { validateExpenseShares } from '../expenseShares'

describe('custom expense shares', () => {
  it.each(['-10', 'abc', '1.001', '0.000', 'Infinity', '1e2', '1,2.3', '9007199254740992'])('rejects an invalid share even when the other shares cover the total: %s', invalid => {
    const result = validateExpenseShares({ anna: '100', ben: invalid })
    expect(result.total).toBe(10000)
    expect(result.valid).toBe(false)
    expect(result.invalidIds).toEqual(['ben'])
  })

  it.each(['', ' ', '0', '00', '0.00', '0,00', '.0', ',00', '0.'])('treats blank and explicit zero as exclusion: %s', zero => {
    expect(validateExpenseShares({ anna: '100', ben: zero })).toEqual({
      valid: true, total: 10000, invalidIds: [], shares: [{ user_id: 'anna', amount_rappen: 10000 }],
    })
  })

  it('produces an exact cent payload with comma and dot decimals', () => {
    expect(validateExpenseShares({ anna: ' 33,33 ', ben: '66.67' })).toEqual({
      valid: true, total: 10000, invalidIds: [],
      shares: [{ user_id: 'anna', amount_rappen: 3333 }, { user_id: 'ben', amount_rappen: 6667 }],
    })
  })
})
