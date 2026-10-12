import { describe, it, expect } from 'vitest'
import type { CalendarEvent, CalendarEventCreatePayload } from '../../types'
import { changedEventFields } from '../eventEdit'

const event = (o: Partial<CalendarEvent> = {}): CalendarEvent => ({
  id: 'e1',
  household_id: 'h1',
  title: 'Zahnarzt',
  starts_at: '2026-10-07T09:00:00+02:00',
  ends_at: '2026-10-07T10:00:00+02:00',
  all_day: false,
  calendar_id: 'c1',
  participant_ids: ['u1'],
  note: null,
  reminder: 'none',
  created_by_user_id: 'u1',
  created_at: '2026-10-01T08:00:00Z',
  ...o,
})

// Formularwerte so, wie CalendarView sie baut (Wanduhrzeit ohne Offset)
const form = (o: Partial<CalendarEventCreatePayload> = {}): CalendarEventCreatePayload => ({
  title: 'Zahnarzt',
  starts_at: '2026-10-07T09:00:00',
  ends_at: '2026-10-07T10:00:00',
  all_day: false,
  calendar_id: 'c1',
  participant_ids: ['u1'],
  note: null,
  reminder: 'none',
  ...o,
})

describe('changedEventFields (CASA-09)', () => {
  it('unverändert → leer (Offset im Original zählt nicht als Änderung)', () => {
    expect(changedEventFields(event(), form())).toEqual({})
  })

  it('nur Titel geändert → nur Titel', () => {
    expect(changedEventFields(event(), form({ title: 'Dentalhygiene' }))).toEqual({ title: 'Dentalhygiene' })
  })

  it('Zeit geändert → Zeitblock (Start, Ende, ganztägig) gemeinsam', () => {
    expect(changedEventFields(event(), form({ ends_at: '2026-10-07T11:00:00' }))).toEqual({
      starts_at: '2026-10-07T09:00:00',
      ends_at: '2026-10-07T11:00:00',
      all_day: false,
    })
  })

  it('Notiz geleert und Teilnehmer geändert (Reihenfolge egal)', () => {
    const original = event({ note: 'Karte mitnehmen', participant_ids: ['u1', 'u2'] })
    expect(changedEventFields(original, form({ note: null, participant_ids: ['u2', 'u1'] })))
      .toEqual({ note: null })
    expect(changedEventFields(original, form({ note: 'Karte mitnehmen', participant_ids: ['u2'] })))
      .toEqual({ participant_ids: ['u2'] })
  })

  it('Kalender und Erinnerung', () => {
    expect(changedEventFields(event(), form({ calendar_id: 'c2', reminder: '1h' })))
      .toEqual({ calendar_id: 'c2', reminder: '1h' })
  })
})
