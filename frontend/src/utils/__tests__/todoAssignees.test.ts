import { describe, it, expect } from 'vitest'
import type { HouseholdMemberInfo, TodoItem } from '../../types'
import {
  activeAssignees,
  assigneeStack,
  claimAction,
  isAssignedTo,
  isUnassigned,
  openUnassignedCount,
  openCountFor,
  sameAssignees,
  toggleAssignee,
  nextQuickAddAssignees,
} from '../todoAssignees'

const members: HouseholdMemberInfo[] = [
  { id: 'anna', display_name: 'Anna Muster', role: 'admin' },
  { id: 'ben', display_name: 'Ben', role: 'member' },
  { id: 'carla', display_name: 'Carla', role: 'member' },
  { id: 'dora', display_name: 'Dora', role: 'member' },
  { id: 'emil', display_name: 'Emil', role: 'member' },
]

const todo = (o: Partial<TodoItem> = {}): TodoItem => ({
  id: 't1', household_id: 'h', title: 'X', description: null, assignee_ids: [], done_by_user_id: null,
  due_date: null, is_done: false, created_by_user_id: 'anna', created_at: '', done_at: null, tags: [],
  updated_at: '', version: 1, reminders: [], ...o,
})

describe('toggleAssignee', () => {
  it('fügt hinzu und entfernt, Reihenfolge bleibt', () => {
    expect(toggleAssignee([], 'ben')).toEqual(['ben'])
    expect(toggleAssignee(['ben'], 'anna')).toEqual(['ben', 'anna'])
    expect(toggleAssignee(['ben', 'anna'], 'ben')).toEqual(['anna'])
  })

  it('verändert das Original nicht', () => {
    const ids = ['ben']
    toggleAssignee(ids, 'anna')
    expect(ids).toEqual(['ben'])
  })
})

describe('sameAssignees', () => {
  it('vergleicht als Menge', () => {
    expect(sameAssignees(['a', 'b'], ['b', 'a'])).toBe(true)
    expect(sameAssignees(['a'], ['a', 'b'])).toBe(false)
    expect(sameAssignees([], [])).toBe(true)
  })
})

describe('activeAssignees / isAssignedTo', () => {
  it('Ex-Mitglieder zählen nicht, Mitglieder in Haushalts-Reihenfolge', () => {
    const t = todo({ assignee_ids: ['carla', 'gone', 'anna'] })
    expect(activeAssignees(t, members).map(m => m.id)).toEqual(['anna', 'carla'])
    expect(isAssignedTo(t, 'carla')).toBe(true)
    expect(isAssignedTo(t, 'ben')).toBe(false)
  })
})

describe('assigneeStack', () => {
  it('höchstens 3 Avatare, Rest als +n', () => {
    const t = todo({ assignee_ids: ['emil', 'dora', 'carla', 'ben', 'anna'] })
    const stack = assigneeStack(t, members)
    expect(stack.shown.map(m => m.id)).toEqual(['anna', 'ben', 'carla'])
    expect(stack.overflow).toBe(2)
    expect(stack.label).toBe('Anna Muster, Ben, Carla, Dora, Emil')
  })

  it('genau 3 → kein +n; ohne Mitglieder leer', () => {
    expect(assigneeStack(todo({ assignee_ids: ['anna', 'ben', 'carla'] }), members).overflow).toBe(0)
    expect(assigneeStack(todo({ assignee_ids: ['gone'] }), members)).toEqual({ shown: [], overflow: 0, label: '' })
  })
})

describe('claimAction', () => {
  it('niemand (oder nur Ex-Mitglieder) zuständig → übernehmen', () => {
    expect(claimAction(todo(), 'anna', members)).toBe('claim')
    expect(claimAction(todo({ assignee_ids: ['gone'] }), 'anna', members)).toBe('claim')
  })

  it('andere zuständig → mithelfen', () => {
    expect(claimAction(todo({ assignee_ids: ['ben'] }), 'anna', members)).toBe('join')
  })

  it('schon zuständig oder erledigt → nichts', () => {
    expect(claimAction(todo({ assignee_ids: ['anna', 'ben'] }), 'anna', members)).toBeNull()
    expect(claimAction(todo({ is_done: true }), 'anna', members)).toBeNull()
    expect(claimAction(todo(), undefined, members)).toBeNull()
  })
})

describe('openCountFor', () => {
  it('zählt offene Aufgaben, bei denen die Person zuständig ist', () => {
    const items = [
      todo({ id: '1', assignee_ids: ['anna', 'ben'] }),
      todo({ id: '2', assignee_ids: ['ben'] }),
      todo({ id: '3', assignee_ids: [] }),
      todo({ id: '4', assignee_ids: ['ben'], is_done: true }),
    ]
    expect(openCountFor(items, 'ben')).toBe(2)
    expect(openCountFor(items, 'anna')).toBe(1)
    expect(openCountFor(items, 'carla')).toBe(0)
  })
})

describe('nextQuickAddAssignees (Personen-Filter)', () => {
  it('Auswahl folgt dem Filter, solange sie leer ist oder nur die alte Filter-Person enthält', () => {
    expect(nextQuickAddAssignees([], 'ben', undefined)).toEqual(['ben'])
    expect(nextQuickAddAssignees(['ben'], 'carla', 'ben')).toEqual(['carla'])
    expect(nextQuickAddAssignees(['ben'], undefined, 'ben')).toEqual([])
  })

  it('eigene Auswahl bleibt; fehlt die Filter-Person, kommt sie dazu', () => {
    expect(nextQuickAddAssignees(['anna', 'ben'], undefined, 'ben')).toEqual(['anna', 'ben'])
    expect(nextQuickAddAssignees(['anna'], 'carla', undefined)).toEqual(['anna', 'carla'])
    expect(nextQuickAddAssignees(['anna', 'carla'], 'carla', 'ben')).toEqual(['anna', 'carla'])
  })
})

describe('isUnassigned / openUnassignedCount (Tab "Offen")', () => {
  it('ohne Zuständige oder nur mit Ex-Mitgliedern gilt eine Aufgabe als offen für alle', () => {
    expect(isUnassigned(todo({ assignee_ids: [] }), members)).toBe(true)
    expect(isUnassigned(todo({ assignee_ids: ['weg'] }), members)).toBe(true)
    expect(isUnassigned(todo({ assignee_ids: ['weg', 'ben'] }), members)).toBe(false)
  })

  it('zählt nur offene, nicht erledigte Aufgaben ohne Zuständige', () => {
    const items = [
      todo({ id: '1', assignee_ids: [] }),
      todo({ id: '2', assignee_ids: ['weg'] }),
      todo({ id: '3', assignee_ids: ['ben'] }),
      todo({ id: '4', assignee_ids: [], is_done: true }),
    ]
    expect(openUnassignedCount(items, members)).toBe(2)
  })
})
