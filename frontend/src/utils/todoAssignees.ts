/**
 * Mehrere zuständige Personen pro Aufgabe (``assignee_ids``).
 *
 * Regeln (wie im Backend, services/attention.py):
 * - keine Zuständigen = offen für alle
 * - Ex-Mitglieder zählen nicht (Aufgabe mit nur Ex-Mitgliedern = offen für alle)
 * - erledigt ist eine Aufgabe für alle, sobald eine Person abhakt (``done_by_user_id``)
 */
import type { HouseholdMemberInfo, TodoItem } from '../types'

/** Avatare in der Zeile, danach "+n" */
export const MAX_STACK = 3

/** Person an-/abwählen (neues Array, Reihenfolge der Auswahl bleibt) */
export function toggleAssignee(ids: readonly string[], userId: string): string[] {
  return ids.includes(userId) ? ids.filter(id => id !== userId) : [...ids, userId]
}

/** Gleiche Personen, unabhängig von der Reihenfolge */
export function sameAssignees(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false
  const set = new Set(a)
  return b.every(id => set.has(id))
}

export function isAssignedTo(todo: TodoItem, userId: string | undefined): boolean {
  return !!userId && (todo.assignee_ids ?? []).includes(userId)
}

/** Zuständige, die (noch) Mitglied sind — in der Reihenfolge der Mitgliederliste */
export function activeAssignees(todo: TodoItem, members: readonly HouseholdMemberInfo[]): HouseholdMemberInfo[] {
  const ids = new Set(todo.assignee_ids ?? [])
  return members.filter(m => ids.has(m.id))
}

export interface AssigneeStack {
  shown: HouseholdMemberInfo[]
  /** Weitere Personen, die nicht als Avatar erscheinen ("+n") */
  overflow: number
  /** Alle Namen, für Screenreader/Tooltip */
  label: string
}

export function assigneeStack(
  todo: TodoItem,
  members: readonly HouseholdMemberInfo[],
  max = MAX_STACK,
): AssigneeStack {
  const active = activeAssignees(todo, members)
  return {
    shown: active.slice(0, max),
    overflow: Math.max(0, active.length - max),
    label: active.map(m => m.display_name).join(', '),
  }
}

/**
 * Welcher "Ich übernehme"-Knopf passt: ``claim`` (noch niemand zuständig),
 * ``join`` (andere sind zuständig → "Ich helfe mit") oder ``null`` (schon dabei / erledigt).
 */
export function claimAction(
  todo: TodoItem,
  myId: string | undefined,
  members: readonly HouseholdMemberInfo[],
): 'claim' | 'join' | null {
  if (!myId || todo.is_done || isAssignedTo(todo, myId)) return null
  return activeAssignees(todo, members).length > 0 ? 'join' : 'claim'
}

/** Niemand (mehr) zuständig → offen für alle (Tab "Offen"); Ex-Mitglieder zählen nicht */
export function isUnassigned(todo: TodoItem, members: readonly HouseholdMemberInfo[]): boolean {
  return activeAssignees(todo, members).length === 0
}

/** Offene Aufgaben ohne Zuständige (Zahl im Tab "Offen") */
export function openUnassignedCount(items: readonly TodoItem[], members: readonly HouseholdMemberInfo[]): number {
  return items.filter(t => !t.is_done && isUnassigned(t, members)).length
}

/** Offene Aufgaben, bei denen die Person (mit-)zuständig ist (Zahl im Personen-Filter) */
export function openCountFor(items: readonly TodoItem[], userId: string): number {
  return items.filter(t => !t.is_done && isAssignedTo(t, userId)).length
}

/**
 * Vorauswahl im Schnell-Erfassen, wenn der Personen-Filter wechselt: Eine leere
 * oder nur aus der bisherigen Filter-Person bestehende Auswahl folgt dem Filter.
 * Eine eigene Auswahl bleibt, bekommt aber die neue Filter-Person dazu — sonst
 * verschwände die neue Aufgabe sofort aus der gefilterten Ansicht.
 */
export function nextQuickAddAssignees(
  current: readonly string[],
  filterUserId: string | undefined,
  previousFilterUserId: string | undefined,
): string[] {
  const followsFilter = current.length === 0
    || (current.length === 1 && current[0] === previousFilterUserId)
  if (followsFilter) return filterUserId ? [filterUserId] : []
  if (filterUserId && !current.includes(filterUserId)) return [...current, filterUserId]
  return [...current]
}
