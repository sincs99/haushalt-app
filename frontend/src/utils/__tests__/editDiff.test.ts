import { describe, it, expect } from 'vitest'
import type { NoteItem, TodoItem } from '../../types'
import { changedNoteFields, changedTodoFields } from '../editDiff'

const note = (o: Partial<NoteItem> = {}): NoteItem => ({
  id: 'n1', household_id: 'h', title: 'WLAN', body: 'Passwort: abc', tag: null, pinned: false,
  created_by_user_id: 'u1', created_at: '', updated_at: '', ...o,
})

const todo = (o: Partial<TodoItem> = {}): TodoItem => ({
  id: 't1', household_id: 'h', title: 'Velo flicken', description: null, assigned_to_user_id: null,
  due_date: '2026-10-07T00:00:00Z', is_done: false, created_by_user_id: 'u1', created_at: '',
  done_at: null, tags: [], updated_at: '', version: 2, reminders: [], ...o,
})

describe('changedNoteFields (CASA-09)', () => {
  it('unverändert → leer', () => {
    expect(changedNoteFields(note(), { title: 'WLAN', body: 'Passwort: abc', tag: null, pinned: false })).toEqual({})
  })

  it('nur geänderte Felder; Tag leeren → null', () => {
    expect(changedNoteFields(note({ tag: 'Haus' }), { title: 'WLAN', body: 'Passwort: xyz', tag: null, pinned: false }))
      .toEqual({ body: 'Passwort: xyz', tag: null })
    expect(changedNoteFields(note(), { title: 'WLAN', body: 'Passwort: abc', tag: null, pinned: true }))
      .toEqual({ pinned: true })
  })
})

describe('changedTodoFields (CASA-09)', () => {
  const unchanged = { title: 'Velo flicken', description: null, due_date: '2026-10-07', assigned_to_user_id: null }

  it('Fälligkeit als Tag verglichen (API liefert 00:00 UTC) → unverändert leer', () => {
    expect(changedTodoFields(todo(), unchanged)).toEqual({})
  })

  it('nur geänderte Felder; Fälligkeit entfernen → null', () => {
    expect(changedTodoFields(todo(), { ...unchanged, assigned_to_user_id: 'u2' })).toEqual({ assigned_to_user_id: 'u2' })
    expect(changedTodoFields(todo(), { ...unchanged, due_date: null })).toEqual({ due_date: null })
    expect(changedTodoFields(todo({ description: 'Schlauch' }), { ...unchanged, description: null }))
      .toEqual({ description: null })
  })
})
