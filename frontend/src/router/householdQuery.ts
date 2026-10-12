import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router'

/** Ausschnitt des Auth-Stores, den der Wechsel braucht */
export interface HouseholdSwitcher {
  households: Array<{ id: string }>
  currentHouseholdId: string | null
  switchHousehold(householdId: string): void
}

/**
 * Push-Links tragen den Haushalt (`?hh=<id>`, Backend push_service, CASA-40): Erinnerung
 * für Haushalt B antippen, während die App A zeigt → erst auf B wechseln, dann die Seite
 * öffnen. Unbekannte IDs (kein Mitglied mehr, /me noch nicht geladen) werden ignoriert.
 *
 * Liefert die Zielroute ohne `hh` (replace), oder null, wenn kein `hh` vorhanden ist.
 */
export function applyHouseholdQuery(
  to: Pick<RouteLocationNormalized, 'path' | 'query' | 'hash'>,
  auth: HouseholdSwitcher,
): RouteLocationRaw | null {
  if (!('hh' in to.query)) return null
  const { hh, ...query } = to.query
  if (
    typeof hh === 'string' &&
    hh !== auth.currentHouseholdId &&
    auth.households.some((h) => h.id === hh)
  ) {
    auth.switchHousehold(hh)
  }
  return { path: to.path, query, hash: to.hash, replace: true }
}
