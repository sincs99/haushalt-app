/**
 * Unit-Tests für den Notes-Store: Laden, Optimistic CRUD mit Rollback, Pin-Toggle,
 * Sortierung (computed) und Socket-Handler.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { NoteItem } from '../../types'
import { deferred, HOUSEHOLD_ID, USER_ID } from './helpers'

const { repo, householdRepo, auth } = vi.hoisted(() => ({
  repo: { fetchAll: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
  householdRepo: { fetchMembers: vi.fn() },
  auth: { currentHouseholdId: null as string | null, user: null as { id: string } | null },
}))

vi.mock('../../repositories/notesRepository', () => ({ createOnlineNotesRepository: () => repo }))
vi.mock('../../repositories/householdsRepository', () => ({ createOnlineHouseholdsRepository: () => householdRepo }))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { useNotesStore } from '../notes'

const note = (o: Partial<NoteItem> = {}): NoteItem => ({
  id: 'n1', household_id: HOUSEHOLD_ID, title: 'Titel', body: '', tag: null, pinned: false,
  created_by_user_id: USER_ID, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', ...o,
})

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  auth.currentHouseholdId = HOUSEHOLD_ID
  auth.user = { id: USER_ID }
})

describe('Laden & Computed', () => {
  test('fetchNotes füllt items, loading wird auch bei Fehler zurückgesetzt', async () => {
    const store = useNotesStore()
    repo.fetchAll.mockResolvedValue([note()])
    await store.fetchNotes()
    expect(store.items).toHaveLength(1)
    repo.fetchAll.mockRejectedValue(new Error('x'))
    await expect(store.fetchNotes()).rejects.toThrow('x')
    expect(store.loading).toBe(false)
  })

  test('fetchMembers lädt Mitglieder', async () => {
    const store = useNotesStore()
    householdRepo.fetchMembers.mockResolvedValue([{ user_id: 'a' }])
    await store.fetchMembers()
    expect(store.members).toHaveLength(1)
  })

  test('pinned/unpinned sind getrennt und neueste zuerst sortiert', () => {
    const store = useNotesStore()
    store.items = [
      note({ id: 'a', created_at: '2026-01-01T00:00:00Z' }),
      note({ id: 'b', created_at: '2026-03-01T00:00:00Z' }),
      note({ id: 'c', pinned: true, created_at: '2026-02-01T00:00:00Z' }),
      note({ id: 'd', pinned: true, created_at: '2026-04-01T00:00:00Z' }),
    ]
    expect(store.pinnedNotes.map(n => n.id)).toEqual(['d', 'c'])
    expect(store.unpinnedNotes.map(n => n.id)).toEqual(['b', 'a'])
  })

  test('ohne Haushalt: No-Ops', async () => {
    auth.currentHouseholdId = null
    const store = useNotesStore()
    await store.fetchNotes(); await store.fetchMembers(); await store.addNote('x')
    await store.updateNote('n1', {}); await store.togglePin('n1'); await store.deleteNote('n1')
    for (const fn of [...Object.values(repo), householdRepo.fetchMembers]) expect(fn).not.toHaveBeenCalled()
  })
})

describe('addNote', () => {
  test('Temp-Eintrag sofort sichtbar, danach durch Server-Notiz ersetzt', async () => {
    const store = useNotesStore()
    const pending = deferred<NoteItem>()
    repo.create.mockReturnValue(pending.promise)
    const p = store.addNote('Einkauf', 'Milch', 'todo')
    expect(store.items[0]).toMatchObject({ title: 'Einkauf', body: 'Milch', tag: 'todo', pinned: false, created_by_user_id: USER_ID })
    expect(repo.create).toHaveBeenCalledWith(HOUSEHOLD_ID, { title: 'Einkauf', body: 'Milch', tag: 'todo' })
    const server = note({ id: 'srv', title: 'Einkauf' })
    pending.resolve(server)
    await p
    expect(store.items).toEqual([server])
  })

  test('Rollback bei Fehler', async () => {
    const store = useNotesStore()
    store.items = [note()]
    repo.create.mockRejectedValue(new Error('500'))
    await expect(store.addNote('x')).rejects.toThrow('500')
    expect(store.items).toEqual([note()])
  })

  test('kein Duplikat bei schnellerem Socket; fremde Notiz geht nicht verloren', async () => {
    const store = useNotesStore()
    const pending = deferred<NoteItem>()
    repo.create.mockReturnValue(pending.promise)
    const server = note({ id: 'srv' })
    const p = store.addNote('x')
    store.handleNoteCreated(note({ id: 'other' }))
    store.handleNoteCreated(server)
    pending.resolve(server)
    await p
    expect(store.items.map(i => i.id).sort()).toEqual(['other', 'srv'])
  })
})

describe('update / pin / delete', () => {
  test('updateNote: optimistisch, Rollback bei Fehler', async () => {
    const store = useNotesStore()
    store.items = [note()]
    repo.update.mockRejectedValue(new Error('x'))
    const p = store.updateNote('n1', { title: 'Neu' })
    expect(store.items[0].title).toBe('Neu')
    await expect(p).rejects.toThrow('x')
    expect(store.items[0].title).toBe('Titel')
    await store.updateNote('missing', { title: 'x' })
    expect(repo.update).toHaveBeenCalledTimes(1)
  })

  test('togglePin schaltet um und rollt bei Fehler zurück', async () => {
    const store = useNotesStore()
    store.items = [note()]
    repo.update.mockResolvedValue(undefined)
    await store.togglePin('n1')
    expect(store.items[0].pinned).toBe(true)
    expect(repo.update).toHaveBeenCalledWith(HOUSEHOLD_ID, 'n1', { pinned: true })
    repo.update.mockRejectedValue(new Error('x'))
    await expect(store.togglePin('n1')).rejects.toThrow('x')
    expect(store.items[0].pinned).toBe(true)
    await store.togglePin('missing')
  })

  test('togglePin-Rollback greift auch, wenn ein Socket-Update das Objekt ersetzt hat', async () => {
    const store = useNotesStore()
    store.items = [note()]
    const pending = deferred<void>()
    repo.update.mockReturnValue(pending.promise)
    const p = store.togglePin('n1')
    store.handleNoteUpdated(note({ pinned: true, title: 'vom Server' }))
    pending.reject(new Error('x'))
    await expect(p).rejects.toThrow('x')
    expect(store.items[0].pinned).toBe(false)
  })

  test('deleteNote: optimistisch, Rollback an alter Position', async () => {
    const store = useNotesStore()
    store.items = [note({ id: 'a' }), note({ id: 'b' }), note({ id: 'c' })]
    repo.remove.mockRejectedValue(new Error('x'))
    const p = store.deleteNote('b')
    expect(store.items.map(i => i.id)).toEqual(['a', 'c'])
    await expect(p).rejects.toThrow('x')
    expect(store.items.map(i => i.id)).toEqual(['a', 'b', 'c'])
    repo.remove.mockResolvedValue(undefined)
    await store.deleteNote('b')
    await store.deleteNote('missing')
    expect(store.items.map(i => i.id)).toEqual(['a', 'c'])
  })
})

test('Socket-Handler: created idempotent, updated nur für bekannte, deleted entfernt', () => {
  const store = useNotesStore()
  store.handleNoteCreated(note())
  store.handleNoteCreated(note({ title: 'B' }))
  expect(store.items).toHaveLength(1)
  store.handleNoteUpdated(note({ title: 'C' }))
  store.handleNoteUpdated(note({ id: 'unknown' }))
  expect(store.items.map(i => i.title)).toEqual(['C'])
  store.handleNoteDeleted({ id: 'n1' })
  expect(store.items).toEqual([])
})
