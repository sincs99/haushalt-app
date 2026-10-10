/**
 * CASA-12: Frontend-State pro Haushalt und pro Sitzung isolieren.
 *
 * Für jeden Fetch eines haushaltsbezogenen Stores: Eine Antwort, die nach einem
 * Haushaltswechsel (A → B, A → B → A) oder nach Logout + Login eines anderen Users
 * ankommt, darf den Store nicht mehr überschreiben (Stil wie
 * docs/qa/audit-evidence/households/staleSwitch.test.ts und
 * frontend_realtime_ux/races.test.ts R1–R3).
 *
 * Der API-Client ist durch einen Fake ersetzt, dessen GETs erst auf Zuruf antworten.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { auth, pending } = vi.hoisted(() => ({
  auth: {
    currentHouseholdId: 'hh-A' as string | null,
    user: { id: 'u1' } as { id: string } | null,
    households: [] as Array<{ id: string; ai_enabled?: boolean }>,
  },
  pending: [] as Array<{ url: string; resolve: (data: unknown) => void }>,
}))

vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn((url: string) => new Promise((resolve) => {
      pending.push({ url, resolve: (data) => resolve({ data }) })
    })),
    post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn(),
  },
  API_BASE: '',
  authRequestConfig: () => ({}),
}))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { resetHouseholdScopedStores } from '../householdScope'
import { useShoppingStore } from '../shopping'
import { useTodosStore } from '../todos'
import { useExpensesStore } from '../expenses'
import { useSettlementsStore } from '../settlements'
import { useChoresStore } from '../chores'
import { useFinanceStore } from '../finance'
import { useDashboardStore } from '../dashboard'
import { usePollsStore } from '../polls'
import { useCalendarStore } from '../calendar'
import { useNotesStore } from '../notes'
import { useFoodStore } from '../food'
import { useTasksStore } from '../tasks'
import { useTagsStore } from '../tags'
import { useDocumentsStore } from '../documents'
import { useAiStore } from '../ai'
import { usePetsStore } from '../pets'
import { usePlantsStore } from '../plants'

beforeEach(() => {
  setActivePinia(createPinia())
  pending.length = 0
  auth.currentHouseholdId = 'hh-A'
  auth.user = { id: 'u1' }
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

/** Antwort für den n-ten offenen GET (Reihenfolge des Starts) */
function respond(index: number, data: unknown) {
  const entry = pending[index]
  if (!entry) throw new Error(`kein offener Request #${index}`)
  entry.resolve(data)
}

const flush = () => new Promise((r) => setTimeout(r, 0))

/** Liste mit einem Eintrag, dessen Herkunft am Haushalt erkennbar ist */
const list = (hh: string) => [{ id: `${hh}-1`, household_id: hh, name: hh, title: hh, version: 1 }]
const obj = (hh: string) => ({ household: hh, available: true, ai_enabled: true })

interface Case {
  name: string
  fetch: () => Promise<unknown> | void
  read: () => unknown
  data: (hh: string) => unknown
}

const cases: Array<[string, () => Case]> = [
  ['shopping.fetchItems', () => { const s = useShoppingStore(); return { name: 'items', fetch: () => s.fetchItems(), read: () => s.items, data: list } }],
  ['shopping.fetchLists', () => { const s = useShoppingStore(); return { name: 'lists', fetch: () => s.fetchLists(), read: () => [s.lists, s.activeListId], data: list } }],
  ['shopping.fetchStores', () => { const s = useShoppingStore(); return { name: 'stores', fetch: () => s.fetchStores(), read: () => s.stores, data: (hh) => [hh] } }],
  ['todos.fetchTodos', () => { const s = useTodosStore(); return { name: 'todos', fetch: () => s.fetchTodos(), read: () => s.items, data: list } }],
  ['todos.fetchMembers', () => { const s = useTodosStore(); return { name: 'members', fetch: () => s.fetchMembers(), read: () => s.members, data: list } }],
  ['expenses.fetchExpenses', () => { const s = useExpensesStore(); return { name: 'expenses', fetch: () => s.fetchExpenses(), read: () => s.expenses, data: list } }],
  ['expenses.fetchBalances', () => { const s = useExpensesStore(); return { name: 'balances', fetch: () => s.fetchBalances(), read: () => s.balances, data: obj } }],
  ['expenses.fetchMembers', () => { const s = useExpensesStore(); return { name: 'members', fetch: () => s.fetchMembers(), read: () => s.members, data: list } }],
  ['settlements.fetchAll', () => { const s = useSettlementsStore(); return { name: 'settlements', fetch: () => s.fetchAll(), read: () => s.settlements, data: list } }],
  ['chores.fetchChores', () => { const s = useChoresStore(); return { name: 'chores', fetch: () => s.fetchChores(), read: () => s.chores, data: list } }],
  ['chores.fetchAssignments', () => { const s = useChoresStore(); return { name: 'assignments', fetch: () => s.fetchAssignments(), read: () => s.assignments, data: list } }],
  ['chores.fetchMembers', () => { const s = useChoresStore(); return { name: 'members', fetch: () => s.fetchMembers(), read: () => s.members, data: list } }],
  ['finance.fetchSummary', () => { const s = useFinanceStore(); return { name: 'summary', fetch: () => s.fetchSummary(), read: () => s.summary, data: obj } }],
  ['finance.fetchBudget', () => { const s = useFinanceStore(); return { name: 'budget', fetch: () => s.fetchBudget(), read: () => s.budget, data: obj } }],
  ['finance.fetchBills', () => { const s = useFinanceStore(); return { name: 'bills', fetch: () => s.fetchBills(), read: () => s.bills, data: list } }],
  ['dashboard.fetchDashboard', () => { const s = useDashboardStore(); return { name: 'dashboard', fetch: () => s.fetchDashboard(), read: () => s.data, data: obj } }],
  ['polls.fetchPolls', () => { const s = usePollsStore(); return { name: 'polls', fetch: () => s.fetchPolls('offen'), read: () => s.polls, data: list } }],
  ['calendar.fetchEvents', () => { const s = useCalendarStore(); return { name: 'events', fetch: () => s.fetchEvents(), read: () => s.events, data: list } }],
  ['calendar.fetchCalendars', () => { const s = useCalendarStore(); return { name: 'calendars', fetch: () => s.fetchCalendars(), read: () => s.calendars, data: list } }],
  ['calendar.fetchMembers', () => { const s = useCalendarStore(); return { name: 'members', fetch: () => s.fetchMembers(), read: () => s.members, data: list } }],
  ['notes.fetchNotes', () => { const s = useNotesStore(); return { name: 'notes', fetch: () => s.fetchNotes(), read: () => s.items, data: list } }],
  ['notes.fetchMembers', () => { const s = useNotesStore(); return { name: 'members', fetch: () => s.fetchMembers(), read: () => s.members, data: list } }],
  ['food.fetchRecipes', () => { const s = useFoodStore(); return { name: 'recipes', fetch: () => s.fetchRecipes(), read: () => s.recipes, data: list } }],
  ['food.fetchWeekPlan', () => { const s = useFoodStore(); return { name: 'weekPlan', fetch: () => s.fetchWeekPlan('2026-10-05'), read: () => s.weekPlan, data: list } }],
  ['tasks.fetchTasks', () => { const s = useTasksStore(); return { name: 'tasks', fetch: () => s.fetchTasks(), read: () => s.items, data: list } }],
  ['tasks.fetchMembers', () => { const s = useTasksStore(); return { name: 'members', fetch: () => s.fetchMembers(), read: () => s.members, data: list } }],
  ['tags.fetchTags', () => { const s = useTagsStore(); return { name: 'tags', fetch: () => s.fetchTags(), read: () => s.items, data: list } }],
  ['tags.fetchTargets', () => { const s = useTagsStore(); return { name: 'targets', fetch: () => s.fetchTargets(), read: () => s.targets, data: list } }],
  ['documents.fetchDocuments', () => { const s = useDocumentsStore(); return { name: 'documents', fetch: () => s.fetchDocuments(), read: () => s.items, data: (hh) => ({ items: list(hh), total: 1 }) } }],
  ['documents.fetchStorage', () => { const s = useDocumentsStore(); return { name: 'storage', fetch: () => s.fetchStorage(), read: () => s.storage, data: obj } }],
  ['ai.fetchSettings', () => { const s = useAiStore(); return { name: 'settings', fetch: () => s.fetchSettings(), read: () => s.settings, data: obj } }],
  ['pets.fetchPets', () => { const s = usePetsStore(); return { name: 'pets', fetch: () => s.fetchPets(), read: () => s.pets, data: list } }],
  ['plants.fetchPlants', () => { const s = usePlantsStore(); return { name: 'plants', fetch: () => s.fetchPlants(), read: () => s.plants, data: list } }],
]

/** Erwarteter Store-Inhalt, wenn nur die Antwort für `hh` übernommen wurde */
async function expectedFor(make: () => Case, hh: string): Promise<unknown> {
  setActivePinia(createPinia())
  const before = pending.length
  const c = make()
  const p = c.fetch()
  respond(before, c.data(hh))
  await p
  const result = JSON.parse(JSON.stringify(c.read()))
  return result
}

/** Leerer Store-Inhalt nach Reset */
function emptyState(make: () => Case): unknown {
  setActivePinia(createPinia())
  return JSON.parse(JSON.stringify(make().read()))
}

const snap = (v: unknown) => JSON.parse(JSON.stringify(v))

describe.each(cases)('%s', (_label, make) => {
  test('verspätete Antwort von Haushalt A landet nicht im Store von Haushalt B', async () => {
    const expectedB = await expectedFor(make, 'hh-B')
    setActivePinia(createPinia())
    pending.length = 0
    auth.currentHouseholdId = 'hh-A'

    const c = make()
    const pA = c.fetch()
    expect(pending[0].url).toContain('hh-A')
    auth.currentHouseholdId = 'hh-B'
    resetHouseholdScopedStores()
    const pB = c.fetch()
    expect(pending[1].url).toContain('hh-B')

    respond(1, c.data('hh-B'))
    await pB
    respond(0, c.data('hh-A'))
    await pA
    await flush()
    expect(snap(c.read())).toEqual(expectedB)
  })

  test('Wechsel A → B → A: Antwort aus der ersten A-Phase wird verworfen', async () => {
    const empty = emptyState(make)
    pending.length = 0
    auth.currentHouseholdId = 'hh-A'

    const c = make()
    const pOld = c.fetch()
    auth.currentHouseholdId = 'hh-B'
    resetHouseholdScopedStores()
    auth.currentHouseholdId = 'hh-A'
    resetHouseholdScopedStores()

    // Die neue A-Phase hat noch nichts geladen → die alte Antwort darf nicht auftauchen
    respond(0, c.data('hh-A'))
    await pOld
    await flush()
    expect(snap(c.read())).toEqual(empty)
  })

  test('Logout + Login eines anderen Users im selben Haushalt: alte Antwort wird verworfen', async () => {
    const empty = emptyState(make)
    pending.length = 0
    auth.currentHouseholdId = 'hh-A'

    const c = make()
    const pOld = c.fetch()
    // _clearState: Haushalt null + Reset; dann meldet sich User 2 im selben Haushalt an
    auth.currentHouseholdId = null
    auth.user = null
    resetHouseholdScopedStores()
    auth.user = { id: 'u2' }
    auth.currentHouseholdId = 'hh-A'

    respond(0, c.data('hh-A'))
    await pOld
    await flush()
    expect(snap(c.read())).toEqual(empty)
  })
})

test('Ladeflag bleibt nach Wechsel ohne neuen Fetch nicht hängen', async () => {
  const todos = useTodosStore()
  const p = todos.fetchTodos()
  expect(todos.loading).toBe(true)
  auth.currentHouseholdId = 'hh-B'
  resetHouseholdScopedStores()
  respond(0, list('hh-A'))
  await p
  expect(todos.items).toEqual([])
  expect(todos.loading).toBe(false)
})

test('älterer Fetch im selben Haushalt überschreibt einen neueren nicht', async () => {
  const s = useShoppingStore()
  const p1 = s.fetchItems()
  const p2 = s.fetchItems()
  respond(1, [{ id: 'neu', household_id: 'hh-A', name: 'neu', version: 2 }])
  await p2
  respond(0, [{ id: 'alt', household_id: 'hh-A', name: 'alt', version: 1 }])
  await p1
  expect(s.items.map((i) => i.id)).toEqual(['neu'])
})

test('resetHouseholdScopedStores leert auch KI, Dokumente und Tags', () => {
  const ai = useAiStore()
  ai.settings = { available: true, ai_enabled: true } as any
  ai.recipeSuggestion = { recipe: { name: 'Risotto' } } as any
  const docs = useDocumentsStore()
  docs.items = [{ id: 'd1' } as any]
  docs.total = 1
  const tags = useTagsStore()
  tags.items = [{ id: 't1' } as any]

  resetHouseholdScopedStores()

  expect(ai.settings).toBeNull()
  expect(ai.recipeSuggestion).toBeNull()
  expect(docs.items).toEqual([])
  expect(docs.total).toBe(0)
  expect(tags.items).toEqual([])
})
