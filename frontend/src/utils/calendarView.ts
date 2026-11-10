/**
 * Datums-Hilfen der Kalender-Ansicht (Woche/Monat/Liste und ihre Dialoge).
 * Arbeiten mit Kalendertagen "YYYY-MM-DD" in der lokalen Zeit des Geräts.
 */
import { localDateString } from './dates'

export function addDaysToDate(dateStr: string, days: number): string {
  const d = new Date(dateStr + 'T00:00:00')
  d.setDate(d.getDate() + days)
  return localDateString(d)
}

/** Sichtbarer Bereich des Monatsrasters: Montag vor dem 1. bis Sonntag nach dem Monatsletzten */
export function getMonthGridRange(year: number, month: number): { from: string; to: string } {
  const firstOfMonth = new Date(year, month, 1)
  const dayOfWeek = firstOfMonth.getDay()
  const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek
  const gridStart = new Date(firstOfMonth)
  gridStart.setDate(gridStart.getDate() + diffToMonday)

  const lastOfMonth = new Date(year, month + 1, 0)
  const lastDow = lastOfMonth.getDay()
  const diffToSunday = lastDow === 0 ? 0 : 7 - lastDow
  const gridEnd = new Date(lastOfMonth)
  gridEnd.setDate(gridEnd.getDate() + diffToSunday)

  return { from: localDateString(gridStart), to: localDateString(gridEnd) }
}

/** "11. Nov." (de) / "Nov 11" (en); `locale` ist die App-Sprache (vue-i18n) */
export function formatDayHeader(dateStr: string, locale: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString(locale === 'de' ? 'de-CH' : 'en-US', {
    day: 'numeric',
    month: 'short',
  })
}

/** "Mi" (de) / "Wed" (en) */
export function formatWeekdayShort(dateStr: string, locale: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString(locale === 'de' ? 'de-CH' : 'en-US', {
    weekday: 'short',
  })
}
