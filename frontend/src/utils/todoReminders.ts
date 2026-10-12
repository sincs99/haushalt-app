import type { TodoReminder } from '../types'

/**
 * Nächste noch ausstehende Erinnerung: in der Zukunft und noch nicht gesendet.
 * Eine Erinnerung mit `notified_at` ist erledigt (gesendet oder verworfen) — die
 * Glocke darf sie nicht mehr als kommend anzeigen (CASA-06).
 */
export function nextPendingReminder(reminders: TodoReminder[] | undefined, now: Date = new Date()): string | null {
  const pending = (reminders ?? [])
    .filter(r => !r.notified_at && new Date(r.remind_at).getTime() > now.getTime())
    .sort((a, b) => new Date(a.remind_at).getTime() - new Date(b.remind_at).getTime())
  return pending.length > 0 ? pending[0].remind_at : null
}
