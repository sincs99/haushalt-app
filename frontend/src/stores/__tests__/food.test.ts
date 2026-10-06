/**
 * Unit-Tests für den Food-Store: Rezepte, Wochenplan, Wochennavigation, Socket-Handler.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { deferred, HOUSEHOLD_ID } from './helpers'

const { repo, auth } = vi.hoisted(() => ({
  repo: {
    fetchRecipes: vi.fn(), createRecipe: vi.fn(), updateRecipe: vi.fn(), deleteRecipe: vi.fn(),
    fetchWeekPlan: vi.fn(), assignMeal: vi.fn(), removeMeal: vi.fn(), addMissingToShopping: vi.fn(),
  },
  auth: { currentHouseholdId: null as string | null },
}))

vi.mock('../../repositories/foodRepository', () => ({ createOnlineFoodRepository: () => repo }))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { useFoodStore } from '../food'

const recipe = (id = 'r1', o: Record<string, unknown> = {}) => ({ id, title: 'Pasta', is_favorite: false, ...o }) as any
const entry = (date: string, o: Record<string, unknown> = {}) => ({ id: `e-${date}`, date, recipe_id: 'r1', recipe: recipe(), ...o }) as any

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  auth.currentHouseholdId = HOUSEHOLD_ID
})

describe('Rezepte', () => {
  test('fetchRecipes lädt; createRecipe dedupliziert gegen schnelleren Socket', async () => {
    const store = useFoodStore()
    repo.fetchRecipes.mockResolvedValue([recipe('a')])
    await store.fetchRecipes()
    expect(store.recipes).toHaveLength(1)

    repo.createRecipe.mockResolvedValue(recipe('b'))
    store.handleRecipeCreated(recipe('b')) // Socket zuerst
    const created = await store.createRecipe({ title: 'Pasta' } as any)
    expect(created?.id).toBe('b')
    expect(store.recipes.map(r => r.id)).toEqual(['a', 'b'])
  })

  test('createRecipe-Fehler lässt die Liste unverändert', async () => {
    const store = useFoodStore()
    repo.createRecipe.mockRejectedValue(new Error('x'))
    await expect(store.createRecipe({} as any)).rejects.toThrow('x')
    expect(store.recipes).toEqual([])
  })

  test('updateRecipe aktualisiert Liste und eingebettete Rezepte im Wochenplan', async () => {
    const store = useFoodStore()
    store.recipes = [recipe()]
    store.weekPlan = [entry('2026-03-02'), entry('2026-03-03', { recipe_id: 'other', recipe: recipe('other') })]
    repo.updateRecipe.mockResolvedValue(recipe('r1', { title: 'Neu' }))
    await store.updateRecipe('r1', { title: 'Neu' })
    expect(store.recipes[0].title).toBe('Neu')
    expect(store.weekPlan[0].recipe!.title).toBe('Neu')
    expect(store.weekPlan[1].recipe!.title).toBe('Pasta')
  })

  test('toggleFavorite kippt das Flag; unbekanntes Rezept ist No-Op', async () => {
    const store = useFoodStore()
    store.recipes = [recipe()]
    repo.updateRecipe.mockResolvedValue(recipe('r1', { is_favorite: true }))
    await store.toggleFavorite('r1')
    expect(repo.updateRecipe).toHaveBeenCalledWith(HOUSEHOLD_ID, 'r1', { is_favorite: true })
    expect(store.recipes[0].is_favorite).toBe(true)
    expect(await store.toggleFavorite('nope')).toBeUndefined()
  })

  test('deleteRecipe entfernt erst nach Erfolg', async () => {
    const store = useFoodStore()
    store.recipes = [recipe()]
    repo.deleteRecipe.mockRejectedValue(new Error('x'))
    await expect(store.deleteRecipe('r1')).rejects.toThrow('x')
    expect(store.recipes).toHaveLength(1)
    repo.deleteRecipe.mockResolvedValue(undefined)
    await store.deleteRecipe('r1')
    expect(store.recipes).toEqual([])
  })
})

describe('Wochenplan', () => {
  test('fetchWeekPlan nutzt currentWeekStart und setzt loading zurück', async () => {
    const store = useFoodStore()
    store.currentWeekStart = '2026-03-02'
    const pending = deferred<any[]>()
    repo.fetchWeekPlan.mockReturnValue(pending.promise)
    const p = store.fetchWeekPlan()
    expect(store.loading).toBe(true)
    pending.resolve([entry('2026-03-02')])
    await p
    expect(repo.fetchWeekPlan).toHaveBeenCalledWith(HOUSEHOLD_ID, '2026-03-02')
    expect(store.loading).toBe(false)
    repo.fetchWeekPlan.mockRejectedValue(new Error('x'))
    await expect(store.fetchWeekPlan('2026-03-09')).rejects.toThrow('x')
    expect(store.loading).toBe(false)
  })

  test('assignMeal ersetzt einen bestehenden Tag oder fügt neu ein; removeMeal entfernt', async () => {
    const store = useFoodStore()
    repo.assignMeal.mockResolvedValueOnce(entry('2026-03-02')).mockResolvedValueOnce(entry('2026-03-02', { recipe_id: 'r2' }))
    await store.assignMeal('2026-03-02', { recipe_id: 'r1' } as any)
    await store.assignMeal('2026-03-02', { recipe_id: 'r2' } as any)
    expect(store.weekPlan).toHaveLength(1)
    expect(store.weekPlan[0].recipe_id).toBe('r2')
    repo.removeMeal.mockResolvedValue(undefined)
    await store.removeMeal('2026-03-02')
    expect(store.weekPlan).toEqual([])
  })

  test('addMissingToShopping reicht die Antwort durch', async () => {
    const store = useFoodStore()
    repo.addMissingToShopping.mockResolvedValue({ added: 2 })
    expect(await store.addMissingToShopping('e1')).toEqual({ added: 2 })
  })

  test('navigateWeek verschiebt um 7 Tage und lädt neu', () => {
    const store = useFoodStore()
    store.currentWeekStart = '2026-03-02'
    repo.fetchWeekPlan.mockResolvedValue([])
    store.navigateWeek(1)
    expect(store.currentWeekStart).toBe('2026-03-09')
    store.navigateWeek(-1); store.navigateWeek(-1)
    expect(store.currentWeekStart).toBe('2026-02-23')
    expect(repo.fetchWeekPlan).toHaveBeenLastCalledWith(HOUSEHOLD_ID, '2026-02-23')
  })

  test('ohne Haushalt: No-Ops', async () => {
    auth.currentHouseholdId = null
    const store = useFoodStore()
    await store.fetchRecipes(); await store.fetchWeekPlan()
    expect(await store.createRecipe({} as any)).toBeUndefined()
    expect(await store.updateRecipe('r', {})).toBeUndefined()
    await store.deleteRecipe('r')
    expect(await store.assignMeal('d', {} as any)).toBeUndefined()
    await store.removeMeal('d')
    expect(await store.addMissingToShopping('e')).toBeUndefined()
    for (const fn of Object.values(repo)) expect(fn).not.toHaveBeenCalled()
  })
})

describe('Socket-Handler', () => {
  test('Recipe created/updated/deleted', () => {
    const store = useFoodStore()
    store.handleRecipeCreated(recipe())
    store.handleRecipeCreated(recipe('r1', { title: 'B' }))
    expect(store.recipes).toHaveLength(1)
    store.weekPlan = [entry('2026-03-02')]
    store.handleRecipeUpdated(recipe('r1', { title: 'C' }))
    store.handleRecipeUpdated(recipe('unknown'))
    expect(store.recipes.map(r => r.title)).toEqual(['C'])
    expect(store.weekPlan[0].recipe!.title).toBe('C')
    store.handleRecipeDeleted({ id: 'r1' })
    expect(store.recipes).toEqual([])
  })

  test('MealPlan updated upsertet pro Datum, deleted entfernt', () => {
    const store = useFoodStore()
    store.handleMealPlanUpdated(entry('2026-03-02'))
    store.handleMealPlanUpdated(entry('2026-03-02', { recipe_id: 'r2' }))
    store.handleMealPlanUpdated(entry('2026-03-03'))
    expect(store.weekPlan).toHaveLength(2)
    expect(store.weekPlan[0].recipe_id).toBe('r2')
    store.handleMealPlanDeleted({ date: '2026-03-02' })
    expect(store.weekPlan.map(e => e.date)).toEqual(['2026-03-03'])
  })
})
