/**
 * Hilfsfunktionen für Store-Namen (Geschäfte) der Einkaufsliste.
 *
 * Das Backend normalisiert Store-Werte (trim, Mehrfach-Whitespace, leer → null)
 * und behandelt Stores case-insensitive. Diese Helfer spiegeln das clientseitig,
 * damit Chip-Filter, Gruppierung und Merge-Warnung auch mit Altdaten
 * ("Coop" vs. "coop") konsistent sind.
 */

/** Trimmt, fasst Mehrfach-Whitespace zusammen, leerer String → null. */
export function normalizeStoreName(value: string | null | undefined): string | null {
  if (value == null) return null
  const collapsed = value.trim().split(/\s+/).filter(Boolean).join(' ')
  return collapsed || null
}

/** Case-insensitiver Vergleichsschlüssel (null für leere Werte). */
export function storeKey(value: string | null | undefined): string | null {
  const normalized = normalizeStoreName(value)
  return normalized === null ? null : normalized.toLowerCase()
}

/** Zwei Store-Werte sind gleich, wenn ihre Schlüssel übereinstimmen (beide leer zählt als gleich). */
export function storesEqual(a: string | null | undefined, b: string | null | undefined): boolean {
  return storeKey(a) === storeKey(b)
}

/** Liefert den Eintrag aus `stores`, der `value` case-insensitiv entspricht, sonst null. */
export function findCanonicalStore(
  stores: readonly string[],
  value: string | null | undefined,
): string | null {
  const key = storeKey(value)
  if (key === null) return null
  return stores.find(s => storeKey(s) === key) ?? null
}
