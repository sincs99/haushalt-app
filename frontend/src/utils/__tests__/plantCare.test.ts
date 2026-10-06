import { describe, it, expect } from 'vitest'
import { careTaskName, daysUntil, dueText, isWaterDue } from '../plantCare'
import type { PlantCareStatus } from '../../types'

const t = (key: string, params?: Record<string, unknown>) =>
  params ? `${key}:${JSON.stringify(params)}` : key

const NOW = new Date(2024, 2, 10, 23, 30) // lokal 2024-03-10, spät abends

describe('plantCare utils', () => {
  it('daysUntil counts whole local days', () => {
    expect(daysUntil('2024-03-10', NOW)).toBe(0)
    expect(daysUntil('2024-03-11', NOW)).toBe(1)
    expect(daysUntil('2024-03-09', NOW)).toBe(-1)
    // Sommerzeitwechsel (31.03.) verfälscht die Tagesanzahl nicht
    expect(daysUntil('2024-04-01', new Date(2024, 2, 30, 12))).toBe(2)
  })

  it('dueText distinguishes overdue, today and future', () => {
    expect(dueText('2024-03-01', t, NOW)).toBe('plants.overdue')
    expect(dueText('2024-03-10', t, NOW)).toBe('plants.dueToday')
    expect(dueText('2024-03-13', t, NOW)).toBe('plants.dueIn:{"n":3}')
  })

  it('careTaskName prefers the label over the localized care type', () => {
    expect(careTaskName({ care_type: 'water', label: null }, t)).toBe('plants.careTypes.water')
    expect(careTaskName({ care_type: 'other', label: ' Blätter abwischen ' }, t)).toBe('Blätter abwischen')
    expect(careTaskName({ care_type: 'mist', label: '  ' }, t)).toBe('plants.careTypes.mist')
  })

  it('isWaterDue only looks at water tasks', () => {
    const base: PlantCareStatus = {
      plant_id: 'p', plant_name: 'x', species: null, location: null, photo_file_id: null,
      due_today: true, overdue: false,
      tasks: [{
        task_id: 't', care_type: 'fertilize', label: null, interval_days: 30,
        next_due_at: '2024-03-10', last_done_at: null, due_today: true, overdue: false,
      }],
    }
    expect(isWaterDue(base)).toBe(false)
    base.tasks.push({ ...base.tasks[0], task_id: 'w', care_type: 'water', due_today: false, overdue: true })
    expect(isWaterDue(base)).toBe(true)
  })
})
