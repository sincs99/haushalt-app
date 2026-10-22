/**
 * Haushaltswechsel: resetHouseholdScopedStores() leert alle haushaltsbezogenen Stores —
 * auch die der Ansichten, die ihre Daten nur beim Öffnen laden (Logik-Review L-07).
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { HOUSEHOLD_ID, deferred } from './helpers'

const { auth, api } = vi.hoisted(() => ({
  auth: { currentHouseholdId: 'hh-1' as string | null, user: { id: 'user-1' } },
  api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}))

// Kein echter API-Client: Die Stores werden hier nur befüllt und geleert
vi.mock('../../api/client', () => ({
  default: api,
  API_BASE: '',
  authRequestConfig: () => ({}),
}))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { resetHouseholdScopedStores } from '../householdScope'
import { usePetsStore } from '../pets'
import { usePlantsStore } from '../plants'
import { useNotesStore } from '../notes'
import { useFoodStore } from '../food'
import { useCalendarStore } from '../calendar'
import { useShoppingStore } from '../shopping'
import { useTodosStore } from '../todos'
import { useChoresStore } from '../chores'
import { useExpensesStore } from '../expenses'
import { usePollsStore } from '../polls'
import { useAiStore } from '../ai'
import { useDocumentsStore } from '../documents'
import { useTagsStore } from '../tags'
import { useFinanceStore } from '../finance'
import { useSettlementsStore } from '../settlements'
import { useDashboardStore } from '../dashboard'

beforeEach(() => {
  setActivePinia(createPinia())
  auth.currentHouseholdId = HOUSEHOLD_ID
})

test.each([
  ['notes', () => useNotesStore().fetchNotes()],
  ['shopping', () => useShoppingStore().fetchItems()],
  ['todos', () => useTodosStore().fetchTodos()],
  ['chores', () => useChoresStore().fetchChores()],
  ['expenses', () => useExpensesStore().fetchExpenses()],
  ['deleted expenses', () => useExpensesStore().fetchDeleted()],
  ['expense pagination', () => { const s = useExpensesStore(); s.hasMore = true; return s.loadMore() }],
  ['settlements', () => useSettlementsStore().fetchAll()],
  ['deleted settlements', () => useSettlementsStore().fetchDeleted()],
  ['settlement pagination', () => { const s = useSettlementsStore(); s.hasMore = true; return s.loadMore() }],
  ['finance', () => useFinanceStore().fetchSummary()],
  ['dashboard', () => useDashboardStore().fetchDashboard()],
  ['polls', () => usePollsStore().fetchPolls()],
  ['calendar', () => useCalendarStore().fetchEvents()],
  ['pets', () => usePetsStore().fetchPets()],
  ['plants', () => usePlantsStore().fetchPlants()],
  ['food', () => useFoodStore().fetchRecipes()],
  ['documents', () => useDocumentsStore().fetchDocuments()],
  ['tags', () => useTagsStore().fetchTags()],
  ['ai', () => useAiStore().fetchSettings()],
] as const)('%s rejects a pending result across an account/household boundary', async (_name, fetch) => {
  const pending = deferred<any>()
  api.get.mockReturnValueOnce(pending.promise)
  const request = fetch()
  const rejected = expect(request).rejects.toMatchObject({ code: 'ERR_CANCELED' })
  resetHouseholdScopedStores()
  auth.user = { id: 'user-2' }
  auth.currentHouseholdId = 'household-2'
  pending.resolve({ data: [] })
  await rejected
  expect(useNotesStore().items).toEqual([])
  expect(useAiStore().settings).toBeNull()
  expect(useDocumentsStore().items).toEqual([])
})

test('a failed old delete cannot restore a private note into the next account', async () => {
  const pending = deferred<void>()
  api.delete.mockReturnValueOnce(pending.promise)
  const notes = useNotesStore()
  notes.items = [{ id: 'private-A', household_id: HOUSEHOLD_ID, body: 'A secret' } as any]
  const request = notes.deleteNote('private-A')
  const rejected = expect(request).rejects.toMatchObject({ code: 'ERR_CANCELED' })
  resetHouseholdScopedStores()
  auth.user = { id: 'user-2' }
  pending.reject(new Error('late network failure'))
  await rejected
  expect(notes.items).toEqual([])
})

test('an old expense edit conflict cannot install private server state in the next account', async () => {
  const pending = deferred<any>()
  api.patch.mockReturnValueOnce(pending.promise)
  const expenses = useExpensesStore()
  const editing = expenses.editExpense('expense-A', { description: 'private edit' })
  const rejected = expect(editing).rejects.toMatchObject({ code: 'ERR_CANCELED' })
  resetHouseholdScopedStores()
  auth.user = { id: 'user-2' }
  pending.reject({ response: { data: { detail: { code: 'EXPENSE_VERSION_CONFLICT', current: { id: 'expense-A', description: 'private server data' } } } } })
  await rejected
  expect(expenses.expenses).toEqual([])
  expect(expenses.error).toBeNull()
})

test('a late assignee edit cannot roll back the same household todo in another session', async () => {
  const pending = deferred<any>()
  api.patch.mockReturnValueOnce(pending.promise)
  const todos = useTodosStore()
  todos.items = [{ id: 'todo-1', title: 'A private draft', assignee_ids: ['user-1'] } as any]
  const editing = todos.updateTodo('todo-1', { title: 'A optimistic draft' })
  const rejected = expect(editing).rejects.toMatchObject({ code: 'ERR_CANCELED' })
  resetHouseholdScopedStores()
  auth.user = { id: 'user-2' }
  todos.items = [{ id: 'todo-1', title: 'B current title', assignee_ids: ['user-2'] } as any]
  pending.reject(new Error('late failure'))
  await rejected
  expect(todos.items[0].title).toBe('B current title')
  expect(todos.items[0].assignee_ids).toEqual(['user-2'])
})

test('synchronously clears AI results, documents and NFC tag tokens as well', () => {
  useAiStore().plantAdvice = { care_notes: 'A private result' } as any
  useAiStore().recipeLoading = true
  useDocumentsStore().items = [{ title: 'A private document' } as any]
  useDocumentsStore().query = 'A private search'
  useTagsStore().items = [{ token: 'A-private-token' } as any]
  resetHouseholdScopedStores()
  expect(useAiStore().plantAdvice).toBeNull()
  expect(useAiStore().recipeLoading).toBe(false)
  expect(useDocumentsStore().items).toEqual([])
  expect(useDocumentsStore().query).toBe('')
  expect(useTagsStore().items).toEqual([])
})

test('leert Haustiere, Pflanzen, Notizen, Essen, Aufgaben und Kalender', () => {
  const pets = usePetsStore()
  pets.pets = [{ id: 'p1', name: 'Bello' } as any]
  pets.feedingStatus = [{ pet_id: 'p1' } as any]
  pets.careTasks = [{ id: 't1' } as any]
  const plants = usePlantsStore()
  plants.plants = [{ id: 'pl1', name: 'Monstera' } as any]
  plants.careStatus = [{ plant_id: 'pl1', tasks: [] } as any]
  plants.careLog = [{ id: 'l1' } as any]
  const notes = useNotesStore()
  notes.items = [{ id: 'n1', title: 'Einkauf' } as any]
  const food = useFoodStore()
  food.recipes = [{ id: 'r1', name: 'Risotto' } as any]
  food.weekPlan = [{ id: 'm1', date: '2026-10-05' } as any]
  const calendar = useCalendarStore()
  calendar.events = [{ id: 'e1', title: 'Zahnarzt' } as any]
  calendar.calendars = [{ id: 'c1', name: 'Allgemein' } as any]

  resetHouseholdScopedStores()

  expect(pets.pets).toEqual([])
  expect(pets.feedingStatus).toEqual([])
  expect(pets.careTasks).toEqual([])
  expect(plants.plants).toEqual([])
  expect(plants.careStatus).toEqual([])
  expect(plants.careLog).toEqual([])
  expect(notes.items).toEqual([])
  expect(food.recipes).toEqual([])
  expect(food.weekPlan).toEqual([])
  expect(calendar.events).toEqual([])
  expect(calendar.calendars).toEqual([])
})

test('leert weiterhin Einkauf, Todos, Ämtli, Finanzen und Abstimmungen', () => {
  const shopping = useShoppingStore()
  shopping.items = [{ id: 'i1' } as any]
  shopping.lists = [{ id: 'l1' } as any]
  shopping.activeListId = 'l1'
  shopping.stores = ['Coop']
  shopping.activeStoreFilter = 'Coop'
  const todos = useTodosStore()
  todos.items = [{ id: 't1' } as any]
  const chores = useChoresStore()
  chores.chores = [{ id: 'c1' } as any]
  chores.assignments = [{ id: 'a1' } as any]
  const expenses = useExpensesStore()
  expenses.expenses = [{ id: 'x1' } as any]
  expenses.balances = { balances: [], settlements: [], unassigned_rappen: 0 }
  const polls = usePollsStore()
  polls.polls = [{ id: 'po1' } as any]

  resetHouseholdScopedStores()

  expect(shopping.items).toEqual([])
  expect(shopping.lists).toEqual([])
  expect(shopping.activeListId).toBeNull()
  expect(shopping.stores).toEqual([])
  expect(shopping.activeStoreFilter).toBeNull()
  expect(todos.items).toEqual([])
  expect(chores.chores).toEqual([])
  expect(chores.assignments).toEqual([])
  expect(expenses.expenses).toEqual([])
  expect(expenses.balances).toBeNull()
  expect(polls.polls).toEqual([])
})
