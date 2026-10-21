/**
 * CASA-45: Rollback-Geister und doppelte Creates (races.test.ts R4/R9).
 *
 * - Eigenes DELETE bekommt 404, weil ein anderes Mitglied schneller war → Erfolg,
 *   kein Wiedereinfügen eines nicht mehr löschbaren Eintrags.
 * - Create-Antwort geht verloren, das Socket-Echo mit gleicher ID ist aber da →
 *   Eintrag bleibt (Server hat ihn angelegt), kein Rollback.
 * - Manueller Retry nach Netzwerkfehler nutzt dieselbe Client-ID.
 *
 * Echte Repositories, nur der API-Client ist gemockt.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { deferred } from './helpers'

const { auth, api } = vi.hoisted(() => ({
  auth: { currentHouseholdId: 'hh-A' as string | null, user: { id: 'u1' } },
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

vi.mock('../../api/client', () => ({ default: api, API_BASE: '', authRequestConfig: () => ({}) }))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { useShoppingStore } from '../shopping'
import { useTodosStore } from '../todos'
import { deleteIdempotent } from '../../repositories/http'

const notFound = () => Object.assign(new Error('Not Found'), { response: { status: 404 } })
const serverError = () => Object.assign(new Error('Server Error'), { response: { status: 500 } })
const networkError = () => Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK' })

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  auth.currentHouseholdId = 'hh-A'
})

describe('deleteIdempotent', () => {
  test('404 gilt als Erfolg', async () => {
    api.delete.mockRejectedValue(notFound())
    await expect(deleteIdempotent('/x')).resolves.toBeUndefined()
  })

  test('andere Fehler werden weitergereicht', async () => {
    api.delete.mockRejectedValue(serverError())
    await expect(deleteIdempotent('/x')).rejects.toThrow('Server Error')
  })
})

test('R4 shopping.deleteItem: Fremdlöschung + eigenes 404 → kein Geist', async () => {
  const s = useShoppingStore()
  s.items = [{ id: 'i1', household_id: 'hh-A', list_id: 'l1', name: 'Milch', version: 1 } as any]
  const d = deferred<void>()
  api.delete.mockReturnValueOnce(d.promise)

  const p = s.deleteItem('i1')
  s.handleItemDeleted({ id: 'i1' }) // anderes Mitglied hat gelöscht
  d.reject(notFound())

  await expect(p).resolves.toBeUndefined()
  expect(s.items).toEqual([])
})

test('todos.deleteTodo: 404 → Eintrag bleibt weg', async () => {
  const t = useTodosStore()
  t.items = [{ id: 't1', household_id: 'hh-A', title: 'Bad', version: 1 } as any]
  api.delete.mockRejectedValueOnce(notFound())
  await t.deleteTodo('t1')
  expect(t.items).toEqual([])
})

test('R9 shopping.addItem: Antwort verloren, Socket-Echo da → Artikel bleibt', async () => {
  const s = useShoppingStore()
  s.activeListId = 'l1'
  api.post.mockImplementationOnce((_url: string, payload: any) => {
    // Server hat angelegt, Echo kommt an, dann reisst die Verbindung ab
    s.handleItemCreated({ id: payload.id, household_id: 'hh-A', list_id: 'l1', name: 'Milch', version: 1 } as any)
    return Promise.reject(networkError())
  })

  const id = await s.addItem('Milch')

  expect(s.items.map(i => i.id)).toEqual([id])
  expect(s.items[0].version).toBe(1)
})

test('R9 shopping.addItem: Retry nach Netzwerkfehler nutzt dieselbe Client-ID', async () => {
  const s = useShoppingStore()
  s.activeListId = 'l1'
  const ids: string[] = []
  api.post.mockImplementation((_url: string, payload: any) => {
    ids.push(payload.id)
    return ids.length === 1
      ? Promise.reject(networkError())
      : Promise.resolve({ data: { id: payload.id, household_id: 'hh-A', list_id: 'l1', name: 'Milch', version: 1 } })
  })

  await expect(s.addItem('Milch')).rejects.toThrow()
  expect(s.items).toEqual([]) // ohne Echo: Rollback wie bisher
  await s.addItem('Milch')

  expect(ids[1]).toBe(ids[0])
  expect(s.items.map(i => i.id)).toEqual([ids[0]])

  // Danach ist die ID verbraucht: ein neuer Artikel bekommt eine neue
  await s.addItem('Milch')
  expect(ids[2]).not.toBe(ids[0])
})

test('shopping.addItem: Validierungsfehler (4xx) → nächster Versuch mit neuer ID', async () => {
  const s = useShoppingStore()
  s.activeListId = 'l1'
  const ids: string[] = []
  api.post.mockImplementation((_url: string, payload: any) => {
    ids.push(payload.id)
    return Promise.reject(Object.assign(new Error('422'), { response: { status: 422 } }))
  })
  await expect(s.addItem('Milch')).rejects.toThrow()
  await expect(s.addItem('Milch')).rejects.toThrow()
  expect(ids[1]).not.toBe(ids[0])
})

test('todos.addTodo: Echo vor verlorener Antwort → bleibt; Retry nutzt dieselbe ID', async () => {
  const t = useTodosStore()
  api.post.mockImplementationOnce((_url: string, payload: any) => {
    t.handleTodoCreated({ id: payload.id, household_id: 'hh-A', title: 'Bad', version: 1, reminders: [] } as any)
    return Promise.reject(networkError())
  })
  const id = await t.addTodo('Bad')
  expect(t.items.map(i => i.id)).toEqual([id])

  const ids: string[] = []
  api.post.mockImplementation((_url: string, payload: any) => {
    ids.push(payload.id)
    return Promise.reject(networkError())
  })
  await expect(t.addTodo('Küche')).rejects.toThrow()
  await expect(t.addTodo('Küche')).rejects.toThrow()
  expect(ids[1]).toBe(ids[0])
})
