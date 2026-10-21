/**
 * Vergleichsschlüssel eines Einkaufsartikels/einer Zutat — Spiegel von
 * `ingredient_key()` in backend/app/routers/shopping.py (PD-M2, PD-S1):
 * führende Menge + Einheit weg ("500 g Mehl" → "mehl"), klein, Whitespace normalisiert.
 * Der Server entscheidet beim Bulk-Add; hier dient er nur dem Hinweis
 * „steht schon auf der Liste“ beim manuellen Hinzufügen.
 */

const QUANTITY_UNITS = [
  'g', 'gr', 'gramm', 'kg', 'kilo', 'mg', 'l', 'liter', 'litre', 'dl', 'cl', 'ml', 'el', 'tl', 'msp',
  'stk', 'stück', 'stueck', 'st', 'pck', 'pkg', 'päckchen', 'packung', 'packungen', 'prise', 'prisen',
  'bund', 'dose', 'dosen', 'becher', 'glas', 'gläser', 'tasse', 'tassen', 'scheibe', 'scheiben',
  'zehe', 'zehen', 'zweig', 'zweige', 'handvoll', 'beutel', 'flasche', 'flaschen', 'x',
  'oz', 'lb', 'lbs', 'cup', 'cups', 'tbsp', 'tsp', 'pinch', 'can', 'cans', 'piece', 'pieces',
  'slice', 'slices', 'clove', 'cloves',
].join('|')

const LEADING_QUANTITY = new RegExp(
  '^(?:ca\\.?\\s*|etwa\\s+|approx\\.?\\s*)?'
  + '\\d+(?:[.,/]\\d+)?(?:\\s*-\\s*\\d+(?:[.,/]\\d+)?)?'
  + `(?:\\s*(?:${QUANTITY_UNITS})\\.?\\s+|\\s+)`,
  'i',
)

export function ingredientKey(value: string): string {
  const text = value.split(/\s+/).filter(Boolean).join(' ')
  const stripped = text.replace(LEADING_QUANTITY, '').trim()
  return (stripped || text).toLowerCase()
}
