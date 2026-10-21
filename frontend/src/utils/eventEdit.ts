import type { CalendarEvent, CalendarEventCreatePayload, CalendarEventUpdatePayload } from '../types'

/** Wanduhrzeit "YYYY-MM-DDTHH:MM" (API liefert mit Offset, das Formular ohne) */
function wallTime(iso: string | null | undefined): string | null {
  return iso ? iso.substring(0, 16) : null
}

function sameSet(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false
  const set = new Set(a)
  return b.every(x => set.has(x))
}

/**
 * Nur die im Bearbeiten-Dialog tatsächlich geänderten Felder (CASA-09).
 * Ein voller Schnappschuss würde eine zwischenzeitliche Änderung von jemand
 * anderem (z. B. Notiz ergänzt) still zurücksetzen.
 *
 * Start, Ende und "ganztägig" hängen voneinander ab (Validierung Ende >= Start,
 * Ganztägig-Ende 23:59) und gehen deshalb nur gemeinsam an die API.
 */
export function changedEventFields(original: CalendarEvent, form: CalendarEventCreatePayload): CalendarEventUpdatePayload {
  const changes: CalendarEventUpdatePayload = {}
  if (form.title !== original.title) changes.title = form.title
  const allDay = form.all_day ?? false
  if (
    wallTime(form.starts_at) !== wallTime(original.starts_at)
    || wallTime(form.ends_at) !== wallTime(original.ends_at)
    || allDay !== original.all_day
  ) {
    changes.starts_at = form.starts_at
    changes.ends_at = form.ends_at ?? null
    changes.all_day = allDay
  }
  if (form.calendar_id !== original.calendar_id) changes.calendar_id = form.calendar_id
  const participants = form.participant_ids ?? []
  if (!sameSet(participants, original.participant_ids)) changes.participant_ids = [...participants]
  if ((form.note ?? null) !== (original.note ?? null)) changes.note = form.note ?? null
  const reminder = form.reminder ?? 'none'
  if (reminder !== (original.reminder ?? 'none')) changes.reminder = reminder
  return changes
}
