/**
 * Client-IDs für idempotente Creates (Backend: services/client_ids.py) über einen
 * manuellen Retry hinweg (CASA-45).
 *
 * Scheitert ein Create mit Netzwerkfehler, weiss der Client nicht, ob der Server ihn
 * angelegt hat. Ein erneuter Versuch mit gleichem Inhalt nutzt deshalb dieselbe ID —
 * der Server liefert dann das bereits angelegte Element statt eines Duplikats.
 */

/** Kein HTTP-Status: Request kam nicht an oder Antwort ging verloren. */
export function isNetworkError(error: unknown): boolean {
  return !!error && typeof error === 'object' && !(error as { response?: unknown }).response
}

export function createRetryIds() {
  const pending = new Map<string, string>()
  return {
    /** ID für einen Create mit diesem Inhalt (die eines gescheiterten Versuchs, sonst neu). */
    idFor(key: string): string {
      return pending.get(key) ?? crypto.randomUUID()
    },
    /** Create gescheitert: bei Netzwerkfehler die ID für den nächsten Versuch merken. */
    failed(key: string, id: string, error: unknown): void {
      if (isNetworkError(error)) pending.set(key, id)
      else pending.delete(key)
    },
    /** Create erfolgreich (oder vom Server bestätigt): ID vergessen. */
    settled(key: string): void {
      pending.delete(key)
    },
  }
}
