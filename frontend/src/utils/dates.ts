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

// ── Multi-day Event Expansion ──

export interface ExpandedEventDay {
  /** YYYY-MM-DD des Tages */
  date: string
  /** 1-basiert: welcher Tag des Spans */
  dayIndex: number
  /** Gesamtanzahl Tage im Span */
  totalDays: number
}

/**
 * Expandiert ein Event auf alle Tage zwischen starts_at und ends_at (inkl.).
 * Falls ends_at null/undefined oder gleich starts_at ist, wird nur 1 Tag zurückgegeben.
 */
export function expandEventToDays(startsAt: string, endsAt: string | null | undefined): ExpandedEventDay[] {
  const startDate = startsAt.substring(0, 10)
  const endDate = endsAt ? endsAt.substring(0, 10) : startDate

  // Falls endDate <= startDate: Einzel-Tag
  if (endDate <= startDate) {
    return [{ date: startDate, dayIndex: 1, totalDays: 1 }]
  }

  const days: ExpandedEventDay[] = []
  let current = startDate
  let idx = 1

  // Berechne Total
  const totalDays = daysBetween(startDate, endDate) + 1

  while (current <= endDate) {
    days.push({ date: current, dayIndex: idx, totalDays })
    current = addOneDayStr(current)
    idx++
  }

  return days
}

/** Hilfsfunktion: Differenz in Tagen */
function daysBetween(dateA: string, dateB: string): number {
  const a = new Date(dateA + 'T00:00:00')
  const b = new Date(dateB + 'T00:00:00')
  return Math.round((b.getTime() - a.getTime()) / (1000 * 60 * 60 * 24))
}

/** Hilfsfunktion: Einen Tag addieren → YYYY-MM-DD */
function addOneDayStr(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  d.setDate(d.getDate() + 1)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
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
