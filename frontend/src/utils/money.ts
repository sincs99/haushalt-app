/**
 * Formatiert Rappen als CHF-String.
 * 2350 => "CHF 23.50", -500 => "-CHF 5.00"
 */
export function formatRappen(rappen: number, currency = 'CHF', locale?: string): string {
  const effectiveLocale = locale ?? (typeof window !== 'undefined' ? localStorage.getItem('haushalt_locale') ?? 'de' : 'de')
  const intlLocale = effectiveLocale === 'de' ? 'de-CH' : 'en-CH'
  return new Intl.NumberFormat(intlLocale, {
    style: 'currency',
    currency,
  }).format(rappen / 100)
}

/**
 * Parst eine Benutzereingabe zu Rappen (Integer).
 * "23.50" => 2350, "23,50" => 2350, "23" => 2300, " 23.5 " => 2350
 * Ungültig ("", "abc", "23.555", negative) => null
 * KEINE Float-Arithmetik — String-basierte Konvertierung.
 */
export function parseAmountToRappen(input: string): number | null {
  const trimmed = input.trim().replace(',', '.')
  if (!trimmed || /[^0-9.]/.test(trimmed)) return null

  const parts = trimmed.split('.')
  if (parts.length > 2) return null  // Mehrere Punkte

  const integerPart = parts[0]
  const decimalPart = parts[1] ?? ''

  if (decimalPart.length > 2) return null  // Mehr als 2 Nachkommastellen
  if (integerPart === '' && decimalPart === '') return null

  const paddedDecimal = decimalPart.padEnd(2, '0')
  const rappen = parseInt(integerPart || '0', 10) * 100 + parseInt(paddedDecimal, 10)

  if (rappen <= 0) return null  // 0 oder negativ
  if (!Number.isFinite(rappen)) return null

  return rappen
}

/**
 * Parst eine Gewichts-Eingabe in Kilogramm zu Gramm (Integer).
 * Komma → Punkt, Bereich 0,1–50 kg, ×1000, auf ganze Gramm gerundet.
 * Leerstring → undefined (kein Gewicht = gültig).
 * Ungültig → null.
 */
export function parseWeightKgToGrams(input: string): number | null | undefined {
  const trimmed = input.trim()
  if (!trimmed) return undefined

  const normalized = trimmed.replace(',', '.')
  const kg = parseFloat(normalized)

  if (!Number.isFinite(kg) || kg < 0.1 || kg > 50) return null

  return Math.round(kg * 1000)
}
