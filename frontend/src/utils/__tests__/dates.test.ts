/**
 * Unit-Tests für Termin-Zeiten in Haushaltszeit und die Tages-Expansion.
 */
import type {} from 'vitest'
import { eventDate, eventTime, expandEventToDays, householdDateString, localDateString, todoDueDay } from '../dates'

// dates.ts lädt i18n, das beim Import localStorage liest (in Node nicht vorhanden)
vi.hoisted(() => {
  const store = new Map<string, string>()
  globalThis.localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: () => null,
    length: 0,
  } as Storage
})

describe('eventTime / eventDate', () => {
  test('liest Wanduhrzeit des Haushalts unabhängig von der Gerätezeitzone', () => {
    expect(eventTime('2026-10-07T09:00:00+02:00')).toBe('09:00')
    expect(eventDate('2026-10-07T09:00:00+02:00')).toBe('2026-10-07')
  })

  test('kurz nach Mitternacht bleibt auf dem Haushaltstag (UTC wäre Vortag)', () => {
    expect(eventDate('2026-10-07T00:30:00+02:00')).toBe('2026-10-07')
    expect(eventTime('2026-10-07T00:30:00+02:00')).toBe('00:30')
  })
})

describe('expandEventToDays', () => {
  test('mehrtägiger Termin in Haushaltszeit', () => {
    const days = expandEventToDays('2026-10-30T00:00:00+02:00', '2026-11-01T23:59:00+01:00')
    expect(days.map((d) => d.date)).toEqual(['2026-10-30', '2026-10-31', '2026-11-01'])
    expect(days[2]).toEqual({ date: '2026-11-01', dayIndex: 3, totalDays: 3 })
  })

  test('ohne Ende → ein Tag', () => {
    expect(expandEventToDays('2026-10-07T09:00:00+02:00', null)).toEqual([
      { date: '2026-10-07', dayIndex: 1, totalDays: 1 },
    ])
  })
})

describe('localDateString', () => {
  it('liefert das lokale Datum, auch kurz nach Mitternacht', () => {
    expect(localDateString(new Date(2026, 9, 6, 0, 30))).toBe('2026-10-06')
    expect(localDateString(new Date(2026, 0, 1, 23, 59))).toBe('2026-01-01')
  })
})

describe('householdDateString (CASA-39)', () => {
  it('uses the household time zone, not the device', () => {
    // 23:30 UTC am 9.10. = 01:30 am 10.10. in Zürich, aber 9.10. in New York
    const now = new Date('2026-10-09T23:30:00Z')
    expect(householdDateString('Europe/Zurich', now)).toBe('2026-10-10')
    expect(householdDateString('America/New_York', now)).toBe('2026-10-09')
  })

  it('falls back to the device date without (valid) time zone', () => {
    const now = new Date(2026, 9, 10, 12, 0)
    expect(householdDateString(null, now)).toBe('2026-10-10')
    expect(householdDateString('Not/AZone', now)).toBe('2026-10-10')
  })
})

describe('todoDueDay (CASA-39)', () => {
  it('takes the calendar day from the stored 00:00 UTC value', () => {
    expect(todoDueDay('2026-10-10T00:00:00Z')).toBe('2026-10-10')
    expect(todoDueDay('2026-10-10')).toBe('2026-10-10')
    expect(todoDueDay(null)).toBeNull()
  })
})
