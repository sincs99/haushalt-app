import i18n from '../i18n'

function getIntlLocale(): string {
  const loc = i18n.global.locale
  // i18n.global.locale kann je nach Konfiguration ein ref oder ein normaler String sein
  const localeStr = typeof loc === 'object' && 'value' in loc ? loc.value : loc
  return localeStr === 'de' ? 'de-CH' : 'en-CH'
}

/**
 * Formatiert ein Datum im langen Format: "02.08.2026" (de) / "08/02/2026" (en)
 */
export function formatDate(dateStr: string): string {
  const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00')
  return d.toLocaleDateString(getIntlLocale(), {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  })
}

/**
 * Formatiert ein Datum kurz: "Mo. 02.08" (de) / "Mon 08/02" (en)
 */
export function formatDateShort(dateStr: string): string {
  const d = new Date(dateStr.includes('T') ? dateStr : dateStr + 'T00:00:00')
  return d.toLocaleDateString(getIntlLocale(), {
    weekday: 'short',
    day: '2-digit',
    month: '2-digit',
  })
}
