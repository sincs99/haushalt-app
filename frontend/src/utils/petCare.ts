import type { FeedingLog, MedicationLog, Pet, PetHistory } from '../types'

/**
 * Rückfrage vor einer weiteren Gabe, wenn die letzte weniger als so viele Stunden
 * zurückliegt (PD-P1, später pro Medikament konfigurierbar). Die Gabe bleibt immer möglich.
 */
export const MEDICATION_CONFIRM_HOURS = 4

/** Jüngste Gabe (Logs kommen sortiert, Socket-Events können aber dazwischenfunken). */
export function lastDose(logs: MedicationLog[] | undefined): MedicationLog | null {
  if (!logs || logs.length === 0) return null
  return logs.reduce((latest, log) => (log.given_at > latest.given_at ? log : latest))
}

/** Liegt die letzte Gabe weniger als `hours` Stunden zurück? → vor erneuter Gabe nachfragen. */
export function isRecentDose(
  log: MedicationLog | null,
  now: Date = new Date(),
  hours: number = MEDICATION_CONFIRM_HOURS,
): boolean {
  if (!log) return false
  const elapsed = now.getTime() - new Date(log.given_at).getTime()
  return elapsed < hours * 3_600_000
}

/** Uhrzeit "HH:MM" (lokal). */
export function formatClock(iso: string): string {
  return new Date(iso).toLocaleTimeString('de-CH', { hour: '2-digit', minute: '2-digit' })
}

/** Aktive (nicht archivierte) Tiere — nur sie werden gefüttert und erinnert. */
export function activePets(pets: Pet[]): Pet[] {
  return pets.filter(p => !p.archived)
}

export function archivedPets(pets: Pet[]): Pet[] {
  return pets.filter(p => p.archived)
}

/** Hat das Tier Verlauf, der beim endgültigen Löschen verloren ginge? */
export function hasHistory(history: PetHistory | null | undefined): boolean {
  if (!history) return false
  return history.feedings + history.medication_logs + history.care_tasks + history.medications > 0
}

/**
 * Entfernen einer Fütterung, die jemand anderes erfasst hat, braucht eine Rückfrage
 * mit Name und Uhrzeit (CASA-30). Eigene Fütterungen bleiben ein Tap (Undo per Toast).
 */
export function needsUnfeedConfirmation(
  feeding: FeedingLog | null | undefined,
  currentUserId: string | null | undefined,
): boolean {
  if (!feeding || feeding.id === 'temp' || !currentUserId) return false
  return feeding.fed_by_user_id !== currentUserId
}
