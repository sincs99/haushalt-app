/**
 * Teil-Updates für Notizen und Aufgaben (CASA-09, PD-F7): Bearbeiten sendet nur Felder,
 * die tatsächlich geändert wurden. Ein voller Schnappschuss würde eine zwischenzeitliche
 * Änderung von jemand anderem an anderen Feldern still zurücksetzen.
 */
import type { NoteItem, TodoItem } from '../types'
import { todoDueDay } from './dates'
import { sameAssignees } from './todoAssignees'

export interface NoteEdit {
  title: string
  body: string
  tag: string | null
  pinned: boolean
}

export interface TodoEdit {
  title: string
  description: string | null
  /** "YYYY-MM-DD" oder null */
  due_date: string | null
  /** Zuständige Personen (Menge; Reihenfolge egal) */
  assignee_ids: string[]
}

export function changedNoteFields(original: NoteItem, edit: NoteEdit): Partial<NoteEdit> {
  const changes: Partial<NoteEdit> = {}
  if (edit.title !== original.title) changes.title = edit.title
  if (edit.body !== original.body) changes.body = edit.body
  if ((edit.tag ?? null) !== (original.tag ?? null)) changes.tag = edit.tag ?? null
  if (edit.pinned !== original.pinned) changes.pinned = edit.pinned
  return changes
}

export function changedTodoFields(original: TodoItem, edit: TodoEdit): Partial<TodoEdit> {
  const changes: Partial<TodoEdit> = {}
  if (edit.title !== original.title) changes.title = edit.title
  if ((edit.description ?? null) !== (original.description ?? null)) changes.description = edit.description ?? null
  // Fälligkeit als Kalendertag vergleichen (API liefert 00:00 UTC)
  if ((edit.due_date ?? null) !== todoDueDay(original.due_date)) changes.due_date = edit.due_date ?? null
  // Zuständige als Menge vergleichen; geändert → ganze neue Menge senden
  if (!sameAssignees(edit.assignee_ids, original.assignee_ids ?? [])) {
    changes.assignee_ids = [...edit.assignee_ids]
  }
  return changes
}
