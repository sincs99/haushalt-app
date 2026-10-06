/**
 * Hilfsfunktionen für versionierte Server-Entitäten (Backend: SyncVersionMixin).
 *
 * Jede Änderung erhöht `version` serverseitig. Damit lassen sich veraltete
 * Socket-Events oder REST-Antworten erkennen, die nach einem neueren Stand
 * eintreffen (siehe docs/offline-first-phase2.md, Kapitel 4.4).
 */

export interface Versioned {
  id: string
  version: number
}

/**
 * true, wenn `incoming` älter ist als der bereits bekannte Stand.
 * Gleiche Version gilt nicht als veraltet (Echo / idempotente Wiederholung).
 */
export function isStale(current: Pick<Versioned, 'version'> | undefined, incoming: Pick<Versioned, 'version'>): boolean {
  return current !== undefined && current.version > incoming.version
}

/**
 * Ersetzt die Entität mit gleicher `id` durch `incoming`, sofern diese nicht veraltet ist.
 * Fehlt sie, wird sie nur bei `insertIfMissing` angehängt.
 *
 * @returns true, wenn die Liste verändert wurde
 */
export function upsertVersioned<T extends Versioned>(list: T[], incoming: T, insertIfMissing: boolean): boolean {
  const idx = list.findIndex(e => e.id === incoming.id)
  if (idx === -1) {
    if (!insertIfMissing) return false
    list.push(incoming)
    return true
  }
  if (isStale(list[idx], incoming)) return false
  list[idx] = incoming
  return true
}
