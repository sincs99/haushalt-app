import { describe, it, expect } from 'vitest'
import type { BalanceEntry, HouseholdMemberInfo } from '../../types'
import { balanceUserName, settlementParties, splitBalances } from '../balances'

const members: HouseholdMemberInfo[] = [
  { id: 'u1', display_name: 'Anna', role: 'admin' },
  { id: 'u2', display_name: 'Ben', role: 'member' },
]

const entry = (user_id: string, saldo: number, o: Partial<BalanceEntry> = {}): BalanceEntry => ({
  user_id,
  paid_rappen: 0,
  owed_rappen: 0,
  settled_out_rappen: 0,
  settled_in_rappen: 0,
  saldo_rappen: saldo,
  is_member: true,
  display_name: null,
  ...o,
})

const entries = [
  entry('u1', -1500),
  entry('u3', 1500, { is_member: false, display_name: 'Cleo' }),
  entry('u2', 0),
]

describe('splitBalances (PD-F2)', () => {
  it('trennt aktuelle und ehemalige Mitglieder', () => {
    const { current, former } = splitBalances(entries, members)
    expect(current.map(e => e.user_id)).toEqual(['u1', 'u2'])
    expect(former.map(e => e.user_id)).toEqual(['u3'])
  })

  it('ältere API ohne is_member: wer nicht in der Mitgliederliste ist, gilt als ehemalig', () => {
    const legacy = [entry('u1', 0, { is_member: undefined }), entry('u9', 100, { is_member: undefined })]
    expect(splitBalances(legacy, members).former.map(e => e.user_id)).toEqual(['u9'])
  })
})

describe('balanceUserName', () => {
  it('Mitgliedsname, sonst Name aus dem Saldo, sonst null', () => {
    expect(balanceUserName('u1', members, entries)).toBe('Anna')
    expect(balanceUserName('u3', members, entries)).toBe('Cleo')
    expect(balanceUserName('u4', members, entries)).toBeNull()
  })
})

describe('settlementParties', () => {
  it('Ausgleich mit ehemaligen Mitgliedern bleibt wählbar (nur wenn Saldo offen)', () => {
    const parties = settlementParties(members, [...entries, entry('u5', 0, { is_member: false, display_name: 'Dora' })])
    expect(parties).toEqual([
      { id: 'u1', display_name: 'Anna', former: false },
      { id: 'u2', display_name: 'Ben', former: false },
      { id: 'u3', display_name: 'Cleo', former: true },
    ])
  })
})
