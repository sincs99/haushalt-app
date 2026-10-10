import { describe, it, expect } from 'vitest'
import { activePets, archivedPets, hasHistory, isRecentDose, petHistoryConflict, lastDose, MEDICATION_CONFIRM_HOURS, needsUnfeedConfirmation } from '../petCare'

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

describe('Fütterung entfernen (CASA-30)', () => {
  const feeding = (by: string, id = 'f1') => ({
    id, household_id: 'h', pet_id: 'p', slot: 'morning' as const, fed_at: '2026-10-10T07:00:00Z', fed_by_user_id: by, date: '2026-10-10',
  })

  it('fragt nur bei Fütterungen anderer Personen nach', () => {
    expect(needsUnfeedConfirmation(null, 'me')).toBe(false)
    expect(needsUnfeedConfirmation(feeding('me'), 'me')).toBe(false)
    expect(needsUnfeedConfirmation(feeding('anna'), 'me')).toBe(true)
    // Optimistischer Platzhalter (eigener Tap in Flight) → keine Rückfrage
    expect(needsUnfeedConfirmation(feeding('anna', 'temp'), 'me')).toBe(false)
    expect(needsUnfeedConfirmation(feeding('anna'), null)).toBe(false)
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

describe('petHistoryConflict (409 PET_HAS_HISTORY)', () => {
  const history = { feedings: 3, medications: 1, medication_logs: 2, care_tasks: 0 }

  it('liefert die Zahlen aus der 409-Antwort', () => {
    const err = { response: { status: 409, data: { detail: { code: 'PET_HAS_HISTORY', message: 'x', history } } } }
    expect(petHistoryConflict(err)).toEqual(history)
  })

  it('andere Fehler → null', () => {
    expect(petHistoryConflict(new Error('x'))).toBeNull()
    expect(petHistoryConflict({ response: { status: 409, data: { detail: { code: 'MEDICATION_HAS_HISTORY' } } } })).toBeNull()
  })
})
