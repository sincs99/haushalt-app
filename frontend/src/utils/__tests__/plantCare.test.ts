import { describe, it, expect } from 'vitest'
import {
  adviceKey, adviceTasks, careTaskName, daysUntil, dueText, isWaterDue, mergeCareNotes, planAdvice, planItems, selectPlan,
} from '../plantCare'
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

describe('KI-Pflegevorschlag → Pflegeaufgaben', () => {
  const advice = {
    watering_interval_days: 7,
    fertilizing_interval_days: 30,
    repotting_interval_months: 24,
  }

  it('adviceTasks maps intervals and converts repotting months to days', () => {
    expect(adviceTasks(advice)).toEqual([
      { care_type: 'water', interval_days: 7 },
      { care_type: 'fertilize', interval_days: 30 },
      { care_type: 'repot', interval_days: 720 },
    ])
  })

  it('adviceTasks skips null intervals', () => {
    expect(adviceTasks({ ...advice, fertilizing_interval_days: null, repotting_interval_months: null }))
      .toEqual([{ care_type: 'water', interval_days: 7 }])
  })

  it('adviceTasks drops out-of-range intervals instead of sending them', () => {
    expect(adviceTasks({ watering_interval_days: 0, fertilizing_interval_days: null, repotting_interval_months: 122 }))
      .toEqual([])
  })

  it('planAdvice creates missing tasks and updates changed intervals only', () => {
    const existing = [
      { id: 'w', care_type: 'water' as const, label: null, interval_days: 10 },
      { id: 'f', care_type: 'fertilize' as const, label: null, interval_days: 30 },
    ]
    expect(planAdvice(advice, existing)).toEqual({
      create: [{ care_type: 'repot', interval_days: 720 }],
      update: [{ id: 'w', care_type: 'water', from: 10, interval_days: 7 }],
    })
  })

  it('selectPlan übernimmt nur angehakte Einträge (PD-P5)', () => {
    const existing = [{ id: 'w', care_type: 'water' as const, label: null, interval_days: 10 }]
    const plan = planAdvice(advice, existing)
    expect(planItems(plan).map(adviceKey)).toEqual(['update:w', 'create:fertilize', 'create:repot'])
    expect(selectPlan(plan, null)).toEqual(plan)
    expect(selectPlan(plan, ['create:repot'])).toEqual({
      create: [{ care_type: 'repot', interval_days: 720 }],
      update: [],
    })
    // Alte Auswahl, Aufgabe inzwischen ersetzt → nichts Unerwartetes übernehmen
    expect(selectPlan(planAdvice(advice, [{ ...existing[0], id: 'neu' }]), ['update:w']).update).toEqual([])
  })

  it('planAdvice leaves labelled custom tasks alone', () => {
    const existing = [{ id: 'x', care_type: 'water' as const, label: 'Tauchbad', interval_days: 14 }]
    const plan = planAdvice({ ...advice, fertilizing_interval_days: null, repotting_interval_months: null }, existing)
    expect(plan.update).toEqual([])
    expect(plan.create).toEqual([{ care_type: 'water', interval_days: 7 }])
  })

  it('mergeCareNotes appends, never overwrites, and is idempotent', () => {
    expect(mergeCareNotes(null, ' Hell stellen. ')).toBe('Hell stellen.')
    expect(mergeCareNotes('Eigene Notiz', 'Hell stellen.')).toBe('Eigene Notiz\n\nHell stellen.')
    expect(mergeCareNotes('Eigene Notiz\n\nHell stellen.', 'Hell stellen.')).toBe('Eigene Notiz\n\nHell stellen.')
    expect(mergeCareNotes('Alt', '   ')).toBe('Alt')
    expect(mergeCareNotes('a'.repeat(1990), 'b'.repeat(100))).toHaveLength(2000)
  })
})
