/**
 * Unit-Tests für die Datums-Hilfen der Kalender-Ansicht (Wochen-/Monatsbereich, Tagesüberschriften).
 */
import type {} from 'vitest'
import { addDaysToDate, formatDayHeader, formatWeekdayShort, getMonthGridRange } from '../calendarView'

describe('addDaysToDate', () => {
  it('addiert und subtrahiert Tage über Monats- und Jahresgrenzen', () => {
    expect(addDaysToDate('2026-11-09', 6)).toBe('2026-11-15')
    expect(addDaysToDate('2026-11-30', 1)).toBe('2026-12-01')
    expect(addDaysToDate('2026-12-28', 7)).toBe('2027-01-04')
    expect(addDaysToDate('2026-03-02', -7)).toBe('2026-02-23')
    expect(addDaysToDate('2028-02-28', 1)).toBe('2028-02-29')
  })

  describe('über die Zeitumstellung (Europe/Zurich)', () => {
    beforeAll(() => { vi.stubEnv('TZ', 'Europe/Zurich') })
    afterAll(() => { vi.unstubAllEnvs() })

    it('bleibt beim Kalendertag (Sommer- und Winterzeit)', () => {
      expect(addDaysToDate('2026-03-23', 7)).toBe('2026-03-30')
      expect(addDaysToDate('2026-03-29', 1)).toBe('2026-03-30')
      expect(addDaysToDate('2026-10-19', 7)).toBe('2026-10-26')
      expect(addDaysToDate('2026-10-25', -1)).toBe('2026-10-24')
    })
  })
})

describe('getMonthGridRange', () => {
  it('reicht vom Montag vor dem 1. bis zum Sonntag nach dem Monatsletzten', () => {
    // November 2026: 1. ist ein Sonntag, 30. ein Montag
    expect(getMonthGridRange(2026, 10)).toEqual({ from: '2026-10-26', to: '2026-12-06' })
  })

  it('beginnt am 1., wenn dieser ein Montag ist, und endet am Letzten, wenn dieser ein Sonntag ist', () => {
    // Juni 2026: 1. ist ein Montag; Februar 2026: 1. Sonntag, 28. Samstag
    expect(getMonthGridRange(2026, 5).from).toBe('2026-06-01')
    expect(getMonthGridRange(2026, 1)).toEqual({ from: '2026-01-26', to: '2026-03-01' })
    // Mai 2026: 31. ist ein Sonntag
    expect(getMonthGridRange(2026, 4).to).toBe('2026-05-31')
  })

  it('funktioniert über den Jahreswechsel', () => {
    expect(getMonthGridRange(2026, 11)).toEqual({ from: '2026-11-30', to: '2027-01-03' })
  })
})

describe('formatDayHeader / formatWeekdayShort', () => {
  it('formatiert nach App-Sprache (de → de-CH, sonst en-US)', () => {
    expect(formatDayHeader('2026-11-11', 'de')).toBe('11. Nov.')
    expect(formatDayHeader('2026-11-11', 'en')).toBe('Nov 11')
    expect(formatWeekdayShort('2026-11-11', 'de')).toBe('Mi')
    expect(formatWeekdayShort('2026-11-11', 'en')).toBe('Wed')
  })
})
