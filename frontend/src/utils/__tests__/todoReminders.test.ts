import { describe, it, expect } from 'vitest'
import type { TodoReminder } from '../../types'
import { nextPendingReminder } from '../todoReminders'

function reminder(id: string, remindAt: string, notifiedAt: string | null = null): TodoReminder {
  return { id, todo_id: 't1', remind_at: remindAt, notified_at: notifiedAt, created_at: '2026-01-01T00:00:00Z' }
}

const NOW = new Date('2026-10-10T10:00:00Z')

describe('nextPendingReminder (CASA-06)', () => {
  it('returns the earliest future reminder that was not sent yet', () => {
    const list = [
      reminder('late', '2026-10-12T08:00:00Z'),
      reminder('early', '2026-10-11T08:00:00Z'),
      reminder('past', '2026-10-09T08:00:00Z'),
    ]
    expect(nextPendingReminder(list, NOW)).toBe('2026-10-11T08:00:00Z')
  })

  it('hides the bell for a future reminder that is marked as notified', () => {
    const list = [reminder('cancelled', '2026-10-11T08:00:00Z', '2026-10-10T09:00:00Z')]
    expect(nextPendingReminder(list, NOW)).toBeNull()
  })

  it('handles missing reminder lists', () => {
    expect(nextPendingReminder(undefined, NOW)).toBeNull()
  })
})
