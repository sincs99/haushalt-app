/**
 * Haushaltswechsel: resetHouseholdScopedStores() leert alle haushaltsbezogenen Stores —
 * auch die der Ansichten, die ihre Daten nur beim Öffnen laden (Logik-Review L-07).
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { HOUSEHOLD_ID } from './helpers'

const { auth } = vi.hoisted(() => ({
  auth: { currentHouseholdId: 'hh-1' as string | null, user: { id: 'user-1' } },
}))

// Kein echter API-Client: Die Stores werden hier nur befüllt und geleert
vi.mock('../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  API_BASE: '',
  authRequestConfig: () => ({}),
}))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { resetHouseholdScopedStores } from '../householdScope'
import { usePetsStore } from '../pets'
import { usePlantsStore } from '../plants'
import { useNotesStore } from '../notes'
import { useFoodStore } from '../food'
import { useTasksStore } from '../tasks'
import { useCalendarStore } from '../calendar'
import { useShoppingStore } from '../shopping'
import { useTodosStore } from '../todos'
import { useChoresStore } from '../chores'
import { useExpensesStore } from '../expenses'
import { usePollsStore } from '../polls'

beforeEach(() => {
  setActivePinia(createPinia())
  auth.currentHouseholdId = HOUSEHOLD_ID
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
  const tasks = useTasksStore()
  tasks.items = [{ id: 'u1', type: 'todo' } as any]
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
  expect(tasks.items).toEqual([])
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
