import { scopeRepository, isScopeChanged, currentDataGeneration, assertDataGeneration } from '../services/sessionScope'
import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { useAuthStore } from './auth'
import { useFoodStore } from './food'
import { useShoppingStore } from './shopping'
import { createOnlineAiRepository } from '../repositories/aiRepository'
import i18n from '../i18n'
import type {
  AiLocale, AiPlantCareAdvice, AiRecipePreference, AiRecipeSuggestion, AiSettings, AiShoppingSuggestion,
  Recipe,
} from '../types'

/** Maschinenlesbarer Fehlercode aus einer Axios-Antwort (z. B. AI_REFUSED). */
function errorCode(error: unknown): string {
  const detail = (error as any)?.response?.data?.detail
  if (detail && typeof detail === 'object' && typeof detail.code === 'string') return detail.code
  if (!(error as any)?.response) return 'network'
  return 'unknown'
}

function currentLocale(): AiLocale {
  const locale = String(i18n.global.locale.value ?? i18n.global.locale)
  return locale === 'en' ? 'en' : 'de'
}

export interface RecipeSuggestionInput {
  ingredients: string[]
  servings: number
  preferences: AiRecipePreference[]
  note?: string
}

export const useAiStore = defineStore('ai', () => {
  const repo = scopeRepository(createOnlineAiRepository())

  // ── State ──
  /** Schlüssel auf dem Server gesetzt? null = noch nicht geladen */
  const available = ref<boolean | null>(null)
  const settings = ref<AiSettings | null>(null)
  /** Status konnte nicht geladen werden (offline/Netz-/Serverfehler) – nicht dasselbe wie „nicht eingerichtet“. */
  const statusError = ref(false)

  const recipeSuggestion = ref<AiRecipeSuggestion | null>(null)
  const recipeLoading = ref(false)
  const recipeError = ref<string | null>(null)

  const plantAdvice = ref<AiPlantCareAdvice | null>(null)
  const plantLoading = ref(false)
  const plantError = ref<string | null>(null)

  // ── Getters ──
  /** KI-Buttons nur zeigen, wenn Server-Schlüssel UND Opt-in des aktuellen Haushalts */
  const enabledForHousehold = computed(() => {
    if (!available.value) return false
    return useAuthStore().currentHousehold?.ai_enabled === true
  })

  // ── Status & Einstellungen ──

  let statusPromise: Promise<void> | null = null

  /**
   * Einmal pro Sitzung laden. Bei einem Fehler bleibt `available` unbekannt (null),
   * `statusError` wird gesetzt und ein späterer Aufruf versucht es erneut.
   */
  function fetchStatus(force = false): Promise<void> {
    const generation = currentDataGeneration()
    if (statusPromise && !force) return statusPromise
    statusError.value = false
    statusPromise = repo.fetchStatus()
      .then((status) => { assertDataGeneration(generation); available.value = status.enabled })
      .catch((error) => {
        if (isScopeChanged(error) || generation !== currentDataGeneration()) return
        statusError.value = true
        statusPromise = null
      })
    return statusPromise
  }

  function applyHouseholdFlag(householdId: string, aiEnabled: boolean) {
    const household = useAuthStore().households.find(h => h.id === householdId)
    if (household) household.ai_enabled = aiEnabled
  }

  async function fetchSettings() {
    const generation = currentDataGeneration()
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return
    const result = await repo.fetchSettings(householdId)
    assertDataGeneration(generation)
    settings.value = result
    available.value = settings.value.available
    statusError.value = false
    applyHouseholdFlag(householdId, settings.value.ai_enabled)
  }

  async function setEnabled(aiEnabled: boolean) {
    const generation = currentDataGeneration()
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return
    const result = await repo.updateSettings(householdId, aiEnabled)
    assertDataGeneration(generation)
    settings.value = result
    applyHouseholdFlag(householdId, settings.value.ai_enabled)
  }

  // ── Rezept ──

  async function suggestRecipe(input: RecipeSuggestionInput): Promise<AiRecipeSuggestion | null> {
    const generation = currentDataGeneration()
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId || recipeLoading.value) return null

    recipeLoading.value = true
    recipeError.value = null
    recipeSuggestion.value = null
    try {
      const note = input.note?.trim()
      const result = await repo.suggestRecipe(householdId, {
        ingredients: input.ingredients.map(i => i.trim()).filter(Boolean),
        servings: input.servings,
        preferences: input.preferences,
        note: note || null,
        locale: currentLocale(),
      })
      assertDataGeneration(generation)
      recipeSuggestion.value = result
      return recipeSuggestion.value
    } catch (error) {
      assertDataGeneration(generation)
      if (isScopeChanged(error)) throw error
      recipeError.value = errorCode(error)
      return null
    } finally {
      assertDataGeneration(generation)
      if (generation === currentDataGeneration()) recipeLoading.value = false
    }
  }

  /** Vorschlag über den bestehenden Rezept-Endpunkt speichern. */
  async function saveSuggestedRecipe(): Promise<Recipe | undefined> {
    const suggestion = recipeSuggestion.value?.recipe
    if (!suggestion) return
    return useFoodStore().createRecipe({
      name: suggestion.name,
      servings: suggestion.servings,
      duration_min: suggestion.duration_min ?? undefined,
      ingredients: suggestion.ingredients,
      steps: suggestion.steps,
      tags: suggestion.tags,
    })
  }

  /**
   * Fehlende Zutaten über den bestehenden Shopping-Endpunkt auf die aktive
   * Einkaufsliste setzen (gibt es keine, wird eine angelegt).
   * Liefert die Anzahl hinzugefügter Einträge.
   */
  async function addMissingToShopping(items: AiShoppingSuggestion[]): Promise<number> {
    const generation = currentDataGeneration()
    if (items.length === 0) return 0
    const shopping = useShoppingStore()
    if (!shopping.activeListId) await shopping.fetchLists()
    assertDataGeneration(generation)
    if (!shopping.activeListId) {
      await shopping.createList(i18n.global.t('ai.recipe.defaultListName'))
      assertDataGeneration(generation)
      await shopping.fetchLists()
      assertDataGeneration(generation)
    }
    if (!shopping.activeListId) return 0

    let added = 0
    for (const item of items) {
      await shopping.addItem(item.name, item.quantity ?? undefined)
      assertDataGeneration(generation)
      added++
    }
    return added
  }

  function clearRecipe() {
    recipeSuggestion.value = null
    recipeError.value = null
  }

  // ── Pflanzenpflege ──

  async function fetchPlantCare(plant: string, location?: string): Promise<AiPlantCareAdvice | null> {
    const generation = currentDataGeneration()
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId || plantLoading.value || !plant.trim()) return null

    plantLoading.value = true
    plantError.value = null
    plantAdvice.value = null
    try {
      const result = await repo.plantCare(householdId, {
        plant: plant.trim(),
        location: location?.trim() || null,
        locale: currentLocale(),
      })
      assertDataGeneration(generation)
      plantAdvice.value = result
      return plantAdvice.value
    } catch (error) {
      assertDataGeneration(generation)
      if (isScopeChanged(error)) throw error
      plantError.value = errorCode(error)
      return null
    } finally {
      assertDataGeneration(generation)
      if (generation === currentDataGeneration()) plantLoading.value = false
    }
  }

  function clearPlant() {
    plantAdvice.value = null
    plantError.value = null
  }

  /** Haushaltswechsel / Logout: Ergebnisse gehören zum alten Haushalt. */
  function reset() {
    statusPromise = null
    available.value = null
    statusError.value = false
    recipeLoading.value = false
    plantLoading.value = false
    settings.value = null
    clearRecipe()
    clearPlant()
  }

  watch(() => useAuthStore().currentHouseholdId, () => reset(), { flush: 'sync' })

  return {
    // State
    available,
    statusError,
    settings,
    recipeSuggestion,
    recipeLoading,
    recipeError,
    plantAdvice,
    plantLoading,
    plantError,
    // Getters
    enabledForHousehold,
    // Actions
    fetchStatus,
    fetchSettings,
    setEnabled,
    suggestRecipe,
    saveSuggestedRecipe,
    addMissingToShopping,
    clearRecipe,
    fetchPlantCare,
    clearPlant,
    reset,
  }
})
