import type { ShoppingItem } from '../types'

export interface ShoppingItemEdit {
  name: string
  quantity: string | null
  store: string | null
  category: string | null
}

/**
 * Nur die im Bearbeiten-Dialog tatsächlich geänderten Felder (CASA-09).
 * Ein voller Schnappschuss würde eine zwischenzeitliche Änderung von jemand
 * anderem (z. B. Menge korrigiert) still zurücksetzen.
 */
export function changedItemFields(original: ShoppingItem, edit: ShoppingItemEdit): Partial<ShoppingItemEdit> {
  const changes: Partial<ShoppingItemEdit> = {}
  for (const key of ['name', 'quantity', 'store', 'category'] as const) {
    if ((original[key] ?? null) !== (edit[key] ?? null)) {
      ;(changes as Record<string, string | null>)[key] = edit[key]
    }
  }
  return changes
}
