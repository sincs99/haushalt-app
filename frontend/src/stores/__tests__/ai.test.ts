import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick, reactive } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import type { AiPlantCareAdvice, AiRecipeSuggestion, HouseholdInfo } from '../../types'

const mocks = vi.hoisted(() => ({
  repo: {
    fetchStatus: vi.fn(),
    fetchSettings: vi.fn(),
    updateSettings: vi.fn(),
    suggestRecipe: vi.fn(),
    plantCare: vi.fn(),
  },
  auth: null as unknown as {
    currentHouseholdId: string | null
    households: HouseholdInfo[]
    readonly currentHousehold: HouseholdInfo | null
  },
  food: { createRecipe: vi.fn() },
  shopping: {
    activeListId: null as string | null,
    fetchLists: vi.fn(),
    createList: vi.fn(),
    addItem: vi.fn(),
  },
}))

vi.mock('../auth', () => ({ useAuthStore: () => mocks.auth }))
const { repo, food, shopping } = mocks
vi.mock('../food', () => ({ useFoodStore: () => mocks.food }))
vi.mock('../shopping', () => ({ useShoppingStore: () => mocks.shopping }))
vi.mock('../../repositories/aiRepository', () => ({
  createOnlineAiRepository: () => mocks.repo,
}))

import i18n from '../../i18n'
import { useAiStore } from '../ai'

function household(over: Partial<HouseholdInfo> = {}): HouseholdInfo {
  return { id: 'h1', name: 'Home', role: 'admin', currency: 'CHF', ai_enabled: false, ...over }
}

function suggestion(): AiRecipeSuggestion {
  return {
    recipe: {
      name: 'Risotto',
      servings: 4,
      cost_rappen: null,
      duration_min: 35,
      ingredients: ['300 g Reis'],
      steps: ['Kochen.'],
      tags: ['vegetarisch'],
      is_favorite: false,
    },
    missing_ingredients: [{ name: 'Parmesan', quantity: '50 g' }, { name: 'Zitrone', quantity: null }],
    tip: null,
  }
}

function advice(): AiPlantCareAdvice {
  return {
    plant_name: 'Monstera',
    botanical_name: 'Monstera deliciosa',
    watering_interval_days: 7,
    fertilizing_interval_days: 14,
    repotting_interval_months: 24,
    light: 'bright_indirect',
    location_tip: 'Hell.',
    care_notes: 'Antrocknen lassen.',
    pet_toxicity: 'toxic',
    pet_toxicity_note: null,
  }
}

function apiError(code: string) {
  return { response: { status: 422, data: { detail: { code, message: code } } } }
}

describe('ai store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(repo).forEach(fn => fn.mockReset())
    food.createRecipe.mockReset()
    shopping.fetchLists.mockReset()
    shopping.createList.mockReset()
    shopping.addItem.mockReset()
    shopping.activeListId = null
    const state = reactive({
      currentHouseholdId: 'h1' as string | null,
      households: [household()],
      get currentHousehold(): HouseholdInfo | null {
        return state.households.find(h => h.id === state.currentHouseholdId) ?? null
      },
    })
    mocks.auth = state
    i18n.global.locale.value = 'de'
  })

  // ── Status / Sichtbarkeit ──

  it('fetchStatus sets availability and is cached', async () => {
    repo.fetchStatus.mockResolvedValue({ enabled: true, daily_limit: 50 })
    const store = useAiStore()
    expect(store.available).toBeNull()

    await store.fetchStatus()
    await store.fetchStatus()

    expect(store.available).toBe(true)
    expect(repo.fetchStatus).toHaveBeenCalledTimes(1)
  })

  it('fetchStatus failure hides AI and allows a retry', async () => {
    repo.fetchStatus.mockRejectedValueOnce(new Error('offline'))
    repo.fetchStatus.mockResolvedValueOnce({ enabled: true, daily_limit: 50 })
    const store = useAiStore()

    await store.fetchStatus()
    expect(store.available).toBe(false)

    await store.fetchStatus()
    expect(store.available).toBe(true)
  })

  it('enabledForHousehold needs server key AND household opt-in', async () => {
    const store = useAiStore()
    repo.fetchStatus.mockResolvedValue({ enabled: false, daily_limit: 50 })
    mocks.auth.households[0].ai_enabled = true
    await store.fetchStatus()
    expect(store.enabledForHousehold).toBe(false) // kein Schlüssel → alles ausgeblendet

    await store.fetchStatus(true)
    store.available = true
    mocks.auth.households[0].ai_enabled = false
    expect(store.enabledForHousehold).toBe(false) // kein Opt-in

    mocks.auth.households[0].ai_enabled = true
    expect(store.enabledForHousehold).toBe(true)
  })

  it('fetchSettings and setEnabled update the household flag', async () => {
    repo.fetchSettings.mockResolvedValue({ ai_enabled: false, available: true, calls_today: 3, daily_limit: 50 })
    repo.updateSettings.mockResolvedValue({ ai_enabled: true, available: true, calls_today: 3, daily_limit: 50 })
    const store = useAiStore()

    await store.fetchSettings()
    expect(store.available).toBe(true)
    expect(store.settings?.calls_today).toBe(3)
    expect(mocks.auth.households[0].ai_enabled).toBe(false)

    await store.setEnabled(true)
    expect(repo.updateSettings).toHaveBeenCalledWith('h1', true)
    expect(mocks.auth.households[0].ai_enabled).toBe(true)
    expect(store.enabledForHousehold).toBe(true)
  })

  it('settings actions do nothing without a household', async () => {
    mocks.auth.currentHouseholdId = null
    const store = useAiStore()
    await store.fetchSettings()
    await store.setEnabled(true)
    expect(repo.fetchSettings).not.toHaveBeenCalled()
    expect(repo.updateSettings).not.toHaveBeenCalled()
  })

  // ── Rezept ──

  it('suggestRecipe sends cleaned input with the UI locale', async () => {
    repo.suggestRecipe.mockResolvedValue(suggestion())
    i18n.global.locale.value = 'en'
    const store = useAiStore()

    const result = await store.suggestRecipe({
      ingredients: [' Reis ', '', 'Zucchetti'],
      servings: 4,
      preferences: ['vegetarian'],
      note: '   ',
    })

    expect(repo.suggestRecipe).toHaveBeenCalledWith('h1', {
      ingredients: ['Reis', 'Zucchetti'],
      servings: 4,
      preferences: ['vegetarian'],
      note: null,
      locale: 'en',
    })
    expect(result?.recipe.name).toBe('Risotto')
    expect(store.recipeSuggestion?.recipe.name).toBe('Risotto')
    expect(store.recipeLoading).toBe(false)
    expect(store.recipeError).toBeNull()
  })

  it('suggestRecipe stores the backend error code (refusal → 422)', async () => {
    repo.suggestRecipe.mockRejectedValue(apiError('AI_REFUSED'))
    const store = useAiStore()

    const result = await store.suggestRecipe({ ingredients: ['Reis'], servings: 2, preferences: [] })

    expect(result).toBeNull()
    expect(store.recipeError).toBe('AI_REFUSED')
    expect(store.recipeSuggestion).toBeNull()
    expect(store.recipeLoading).toBe(false)
  })

  it('suggestRecipe maps network and unknown errors', async () => {
    const store = useAiStore()
    repo.suggestRecipe.mockRejectedValueOnce(new Error('Network Error'))
    await store.suggestRecipe({ ingredients: ['Reis'], servings: 2, preferences: [] })
    expect(store.recipeError).toBe('network')

    repo.suggestRecipe.mockRejectedValueOnce({ response: { status: 500, data: 'oops' } })
    await store.suggestRecipe({ ingredients: ['Reis'], servings: 2, preferences: [] })
    expect(store.recipeError).toBe('unknown')
  })

  it('suggestRecipe ignores a second call while one is running', async () => {
    let resolve!: (v: AiRecipeSuggestion) => void
    repo.suggestRecipe.mockReturnValue(new Promise(r => { resolve = r }))
    const store = useAiStore()

    const first = store.suggestRecipe({ ingredients: ['Reis'], servings: 2, preferences: [] })
    expect(store.recipeLoading).toBe(true)
    expect(await store.suggestRecipe({ ingredients: ['Reis'], servings: 2, preferences: [] })).toBeNull()
    resolve(suggestion())
    await first
    expect(repo.suggestRecipe).toHaveBeenCalledTimes(1)
  })

  it('saveSuggestedRecipe uses the existing recipe endpoint via the food store', async () => {
    repo.suggestRecipe.mockResolvedValue(suggestion())
    food.createRecipe.mockResolvedValue({ id: 'r1' })
    const store = useAiStore()
    expect(await store.saveSuggestedRecipe()).toBeUndefined()

    await store.suggestRecipe({ ingredients: ['Reis'], servings: 4, preferences: [] })
    await store.saveSuggestedRecipe()

    expect(food.createRecipe).toHaveBeenCalledWith({
      name: 'Risotto',
      servings: 4,
      duration_min: 35,
      ingredients: ['300 g Reis'],
      steps: ['Kochen.'],
      tags: ['vegetarisch'],
    })
  })

  it('addMissingToShopping adds items to the active list', async () => {
    shopping.fetchLists.mockImplementation(async () => { shopping.activeListId = 'l1' })
    const store = useAiStore()

    const added = await store.addMissingToShopping(suggestion().missing_ingredients)

    expect(added).toBe(2)
    expect(shopping.createList).not.toHaveBeenCalled()
    expect(shopping.addItem).toHaveBeenNthCalledWith(1, 'Parmesan', '50 g')
    expect(shopping.addItem).toHaveBeenNthCalledWith(2, 'Zitrone', undefined)
  })

  it('addMissingToShopping creates a list when the household has none', async () => {
    let lists = 0
    shopping.createList.mockImplementation(async () => { lists++ })
    shopping.fetchLists.mockImplementation(async () => { if (lists) shopping.activeListId = 'new' })
    const store = useAiStore()

    expect(await store.addMissingToShopping([{ name: 'Milch', quantity: null }])).toBe(1)
    expect(shopping.createList).toHaveBeenCalledWith('Einkaufsliste')
    expect(await store.addMissingToShopping([])).toBe(0)
  })

  // ── Pflanzenpflege ──

  it('fetchPlantCare sends trimmed input and stores the advice', async () => {
    repo.plantCare.mockResolvedValue(advice())
    const store = useAiStore()

    await store.fetchPlantCare('  Monstera ', '  ')

    expect(repo.plantCare).toHaveBeenCalledWith('h1', { plant: 'Monstera', location: null, locale: 'de' })
    expect(store.plantAdvice?.light).toBe('bright_indirect')
    expect(store.plantLoading).toBe(false)
  })

  it('fetchPlantCare skips blank input and stores error codes', async () => {
    const store = useAiStore()
    expect(await store.fetchPlantCare('   ')).toBeNull()
    expect(repo.plantCare).not.toHaveBeenCalled()

    repo.plantCare.mockRejectedValue(apiError('AI_PLANT_NOT_RECOGNIZED'))
    await store.fetchPlantCare('Toaster', 'Küche')
    expect(repo.plantCare).toHaveBeenCalledWith('h1', { plant: 'Toaster', location: 'Küche', locale: 'de' })
    expect(store.plantError).toBe('AI_PLANT_NOT_RECOGNIZED')

    store.clearPlant()
    expect(store.plantError).toBeNull()
  })

  it('switching the household clears results of the previous one', async () => {
    repo.suggestRecipe.mockResolvedValue(suggestion())
    repo.plantCare.mockResolvedValue(advice())
    mocks.auth.households.push(household({ id: 'h2' }))
    const store = useAiStore()
    await store.suggestRecipe({ ingredients: ['Reis'], servings: 2, preferences: [] })
    await store.fetchPlantCare('Monstera')

    mocks.auth.currentHouseholdId = 'h2'
    await nextTick()

    expect(store.recipeSuggestion).toBeNull()
    expect(store.plantAdvice).toBeNull()
  })
})
