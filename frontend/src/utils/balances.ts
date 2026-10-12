/**
 * Salden ehemaliger Mitglieder (PD-F2): Wer den Haushalt verlassen hat, behält
 * seinen Saldo. Die Karte zeigt solche Einträge getrennt und gekennzeichnet; ein
 * Ausgleich mit ihnen bleibt möglich (das Backend erlaubt eine Ex-Mitglied-Seite).
 */
import type { BalanceEntry, HouseholdMemberInfo } from '../types'

export interface SettlementParty {
  id: string
  display_name: string | null
  former: boolean
}

function isFormer(entry: BalanceEntry, members: HouseholdMemberInfo[]): boolean {
  // Ältere API ohne Flag: nicht in der Mitgliederliste → ehemalig
  if (entry.is_member !== undefined) return !entry.is_member
  return !members.some(m => m.id === entry.user_id)
}

export function splitBalances(
  entries: BalanceEntry[],
  members: HouseholdMemberInfo[],
): { current: BalanceEntry[]; former: BalanceEntry[] } {
  const current: BalanceEntry[] = []
  const former: BalanceEntry[] = []
  for (const e of entries) (isFormer(e, members) ? former : current).push(e)
  return { current, former }
}

/** Anzeigename: aktuelles Mitglied, sonst Name aus dem Saldo-Eintrag, sonst null */
export function balanceUserName(
  userId: string,
  members: HouseholdMemberInfo[],
  entries: BalanceEntry[],
): string | null {
  const member = members.find(m => m.id === userId)
  if (member) return member.display_name
  return entries.find(e => e.user_id === userId)?.display_name ?? null
}

/** Auswahl im Ausgleich-Dialog: alle Mitglieder plus ehemalige mit offenem Saldo */
export function settlementParties(
  members: HouseholdMemberInfo[],
  entries: BalanceEntry[],
): SettlementParty[] {
  const parties: SettlementParty[] = members.map(m => ({ id: m.id, display_name: m.display_name, former: false }))
  for (const e of splitBalances(entries, members).former) {
    if (e.saldo_rappen !== 0) parties.push({ id: e.user_id, display_name: e.display_name ?? null, former: true })
  }
  return parties
}
