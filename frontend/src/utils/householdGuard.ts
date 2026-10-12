/**
 * Haushalts-/Sitzungs-Generation (CASA-12).
 *
 * Jede Antwort, die nach einem `await` in einen Store geschrieben wird, muss noch zum
 * aktuellen Haushalt UND zur aktuellen Sitzung gehören. Der Zähler wird bei jedem
 * Haushaltswechsel (auch von/nach `null`) und bei jedem Logout erhöht
 * (resetHouseholdScopedStores, auth._clearState). Eine Antwort, die nach dem Wechsel
 * ankommt, wird verworfen — auch bei A → B → A und bei Logout + Login eines anderen
 * Users im selben Haushalt, wo die Haushalts-ID allein gleich bliebe.
 *
 * Verallgemeinert das frühere captureRequest aus pets.ts/plants.ts.
 */
import { useAuthStore } from '../stores/auth'

let generation = 0

/** Neue Generation: alle laufenden Requests gelten ab jetzt als veraltet. */
export function bumpHouseholdGeneration(): void {
  generation++
}

export function householdGeneration(): number {
  return generation
}

/**
 * Merkt sich Haushalt + Generation beim Start einer Aktion. Die zurückgegebene Funktion
 * ist true, solange beides unverändert ist — nach jedem `await` prüfen, bevor State
 * geschrieben wird.
 */
export function captureHousehold(householdId: string): () => boolean {
  const gen = generation
  return () => gen === generation && useAuthStore().currentHouseholdId === householdId
}

/** Ergebnis von captureRequest: `active()` für Daten, `active.latest()` für Ladeflags. */
export interface RequestGuard {
  (): boolean
  /**
   * Nur „neueste Anfrage für diesen Schlüssel?“ — ohne Haushaltsprüfung. Für `loading`
   * im finally: Nach einem Haushaltswechsel ohne neuen Fetch muss das Flag trotzdem
   * zurückgesetzt werden, sonst bliebe der Spinner stehen.
   */
  latest: () => boolean
}

/**
 * Wie captureHousehold, zusätzlich „nur die neueste Anfrage pro Schlüssel gewinnt“:
 * Ein älterer Fetch, der nach einem neueren zurückkommt, überschreibt dessen Ergebnis nicht.
 * Pro Store eine Instanz anlegen: `const captureRequest = createRequestGuard()`.
 */
export function createRequestGuard() {
  let seq = 0
  const latestByKey = new Map<string, number>()
  return function captureRequest(householdId: string, key: string): RequestGuard {
    const inScope = captureHousehold(householdId)
    const version = ++seq
    latestByKey.set(key, version)
    const latest = () => latestByKey.get(key) === version
    const active = (() => inScope() && latest()) as RequestGuard
    active.latest = latest
    return active
  }
}

/**
 * Socket-Payload eines anderen Haushalts? Payloads ohne `household_id` (z. B. reine
 * Lösch-Events `{ id }`) gelten als passend — sie kommen ohnehin nur aus dem Room.
 */
export function isForeignHouseholdPayload(payload: unknown, currentHouseholdId: string | null): boolean {
  if (!payload || typeof payload !== 'object') return false
  const hid = (payload as { household_id?: unknown }).household_id
  if (typeof hid !== 'string' || !hid) return false
  return hid !== currentHouseholdId
}
