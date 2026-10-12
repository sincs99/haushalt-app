/**
 * Haushaltsdatum statt Gerätedatum (CASA-39) und Monatsrechnung.
 */
import { describe, it, expect } from 'vitest'
import { addMonths, householdDateString, localDateString, monthStart } from '../dates'

describe('householdDateString', () => {
  // 2026-10-10 23:30 UTC: in Zürich schon der 11., in New York noch der 10.
  const now = new Date('2026-10-10T23:30:00Z')

  it('rechnet in der Zeitzone des Haushalts', () => {
    expect(householdDateString('Europe/Zurich', now)).toBe('2026-10-11')
    expect(householdDateString('America/New_York', now)).toBe('2026-10-10')
  })

  it('fällt ohne oder mit ungültiger Zeitzone auf das Gerätedatum zurück', () => {
    expect(householdDateString(undefined, now)).toBe(localDateString(now))
    expect(householdDateString('Mars/Olympus', now)).toBe(localDateString(now))
  })
})

describe('Monatsrechnung', () => {
  it('monthStart', () => {
    expect(monthStart('2026-10-17')).toBe('2026-10-01')
  })

  it('addMonths über Jahresgrenzen', () => {
    expect(addMonths('2026-01-01', -1)).toBe('2025-12-01')
    expect(addMonths('2026-10-01', -12)).toBe('2025-10-01')
    expect(addMonths('2026-12-01', 1)).toBe('2027-01-01')
    expect(addMonths('2026-03-01', -14)).toBe('2025-01-01')
  })
})
