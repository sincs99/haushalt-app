import { describe, it, expect } from 'vitest'
import { activePets, archivedPets, hasHistory, isRecentDose, lastDose, MEDICATION_CONFIRM_HOURS } from '../petCare'

const log = (id: string, givenAt: string, by = 'u1') => ({
  id, household_id: 'h', medication_id: 'm', given_at: givenAt, given_by_user_id: by, created_at: givenAt,
})

describe('Medikamentengabe (PD-P1)', () => {
  it('lastDose nimmt die jüngste Gabe, auch wenn die Liste unsortiert ist', () => {
    expect(lastDose(undefined)).toBeNull()
    expect(lastDose([])).toBeNull()
    const logs = [log('a', '2026-10-10T06:00:00Z'), log('b', '2026-10-10T18:00:00Z'), log('c', '2026-10-09T18:00:00Z')]
    expect(lastDose(logs)?.id).toBe('b')
  })

  it('isRecentDose: Rückfrage nur innerhalb des Fensters', () => {
    const now = new Date('2026-10-10T12:00:00Z')
    expect(MEDICATION_CONFIRM_HOURS).toBe(4)
    expect(isRecentDose(null, now)).toBe(false)
    expect(isRecentDose(log('a', '2026-10-10T08:30:00Z'), now)).toBe(true)
    expect(isRecentDose(log('a', '2026-10-10T08:00:00Z'), now)).toBe(false)
    // Zweite Tagesdosis am Abend (2x täglich) → keine Rückfrage
    expect(isRecentDose(log('a', '2026-10-10T07:00:00Z'), new Date('2026-10-10T19:00:00Z'))).toBe(false)
  })
})

describe('Archiv (PD-P2)', () => {
  const pets = [{ id: 'a', archived: false }, { id: 'b', archived: true }] as any

  it('trennt aktive und archivierte Tiere', () => {
    expect(activePets(pets).map(p => p.id)).toEqual(['a'])
    expect(archivedPets(pets).map(p => p.id)).toEqual(['b'])
  })

  it('hasHistory: jede Art von Verlauf zählt', () => {
    const none = { feedings: 0, medications: 0, medication_logs: 0, care_tasks: 0 }
    expect(hasHistory(null)).toBe(false)
    expect(hasHistory(none)).toBe(false)
    expect(hasHistory({ ...none, feedings: 1 })).toBe(true)
    expect(hasHistory({ ...none, medications: 1 })).toBe(true)
  })
})
