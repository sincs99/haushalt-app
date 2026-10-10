import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineFoodRepository } from '../repositories/foodRepository'
import type {
  Recipe, RecipeCreatePayload, RecipeUpdatePayload,
  MealPlanEntry, MealPlanAssignPayload, AddToShoppingResponse,
} from '../types'

/**
 * Gibt den ISO-Datums-String des Montags der aktuellen Woche zurück.
 */
function getMonday(d: Date = new Date()): string {
  const dt = new Date(d)
  const day = dt.getDay()
  // getDay(): 0=So, 1=Mo ... 6=Sa → Offset zu Montag
  const diff = day === 0 ? -6 : 1 - day
  dt.setDate(dt.getDate() + diff)
  return toISODate(dt)
}

function toISODate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export const useFoodStore = defineStore('food', () => {
  const repo = createOnlineFoodRepository()

  // ── State ──
  const recipes = ref<Recipe[]>([])
  const weekPlan = ref<MealPlanEntry[]>([])
  const currentWeekStart = ref(getMonday())
  const loading = ref(false)

  // ── Recipe Actions ──

  async function fetchRecipes() {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    recipes.value = await repo.fetchRecipes(householdId)
  }

  async function createRecipe(payload: RecipeCreatePayload): Promise<Recipe | undefined> {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    const created = await repo.createRecipe(householdId, payload)
    // Optimistic: sofort einfügen (Socket-Handler dedupliziert)
    const idx = recipes.value.findIndex(r => r.id === created.id)
    if (idx === -1) {
      recipes.value.push(created)
    }
    return created
  }

  async function updateRecipe(id: string, payload: RecipeUpdatePayload): Promise<Recipe | undefined> {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    const updated = await repo.updateRecipe(householdId, id, payload)
    const idx = recipes.value.findIndex(r => r.id === id)
    if (idx !== -1) {
      recipes.value[idx] = updated
    }
    // Auch im Wochenplan aktualisieren
    for (const entry of weekPlan.value) {
      if (entry.recipe_id === id) {
        entry.recipe = updated
      }
    }
    return updated
  }

  async function deleteRecipe(id: string) {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    await repo.deleteRecipe(householdId, id)
    removeRecipeLocally(id)
  }

  /**
   * Rezept entfernen; geplante Mahlzeiten behalten den Namen als Freitext — wie der
   * Server beim Löschen (PD-M3, CASA-52).
   */
  function removeRecipeLocally(id: string) {
    const name = recipes.value.find(r => r.id === id)?.name
    recipes.value = recipes.value.filter(r => r.id !== id)
    weekPlan.value = weekPlan.value.map(e => (e.recipe_id === id
      ? { ...e, recipe_id: null, recipe: null, free_text: e.recipe?.name ?? name ?? e.free_text }
      : e))
  }

  /** Favorit optimistisch umschalten (Liste und eingebettete Rezepte im Wochenplan), Rollback bei Fehler. */
  async function toggleFavorite(id: string) {
    const recipe = recipes.value.find(r => r.id === id)
      ?? weekPlan.value.find(e => e.recipe_id === id)?.recipe
    if (!recipe) return
    const previous = recipe.is_favorite
    setFavoriteLocally(id, !previous)
    try {
      return await updateRecipe(id, { is_favorite: !previous })
    } catch (error) {
      setFavoriteLocally(id, previous)
      throw error
    }
  }

  function setFavoriteLocally(id: string, value: boolean) {
    const recipe = recipes.value.find(r => r.id === id)
    if (recipe) recipe.is_favorite = value
    for (const entry of weekPlan.value) {
      if (entry.recipe_id === id && entry.recipe) entry.recipe.is_favorite = value
    }
  }

  // ── Meal Plan Actions ──

  // Laufende Nummer der letzten Wochenplan-Anfrage: beim schnellen Wochenwechsel
  // darf eine ältere Antwort die aktuelle Woche nicht überschreiben.
  let weekRequestId = 0

  async function fetchWeekPlan(weekDate?: string) {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    const week = weekDate ?? currentWeekStart.value
    const requestId = ++weekRequestId
    loading.value = true
    try {
      const plan = await repo.fetchWeekPlan(householdId, week)
      // Veraltete Antwort verwerfen
      if (requestId !== weekRequestId) return
      weekPlan.value = plan
    } catch (error) {
      // Fehler einer überholten Anfrage interessiert nicht mehr
      if (requestId !== weekRequestId) return
      throw error
    } finally {
      if (requestId === weekRequestId) loading.value = false
    }
  }

  async function assignMeal(date: string, payload: MealPlanAssignPayload): Promise<MealPlanEntry | undefined> {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    const entry = await repo.assignMeal(householdId, date, payload)
    const idx = weekPlan.value.findIndex(e => e.date === date)
    if (idx !== -1) {
      weekPlan.value[idx] = entry
    } else {
      weekPlan.value.push(entry)
    }
    return entry
  }

  /** Entfernt das Essen eines Tages; liefert den entfernten Eintrag (für Rückgängig). */
  async function removeMeal(date: string): Promise<MealPlanEntry | undefined> {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    const removed = weekPlan.value.find(e => e.date === date)
    await repo.removeMeal(householdId, date)
    weekPlan.value = weekPlan.value.filter(e => e.date !== date)
    return removed
  }

  /** Rückgängig für removeMeal: denselben Tag wieder mit Rezept bzw. Freitext belegen. */
  async function restoreMeal(entry: MealPlanEntry) {
    return assignMeal(entry.date, { recipe_id: entry.recipe_id ?? null, free_text: entry.free_text ?? null })
  }

  /** Fehlende Zutaten auf die Liste `listId` (aktive Liste) setzen; Dedupe macht der Server (PD-M2). */
  async function addMissingToShopping(entryId: string, listId?: string | null): Promise<AddToShoppingResponse | undefined> {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    return repo.addMissingToShopping(householdId, entryId, listId ?? undefined)
  }

  function navigateWeek(direction: -1 | 1) {
    const d = new Date(currentWeekStart.value + 'T00:00:00')
    d.setDate(d.getDate() + direction * 7)
    currentWeekStart.value = toISODate(d)
    return fetchWeekPlan()
  }

  // ── Socket-Handlers ──

  function handleRecipeCreated(data: Recipe) {
    const idx = recipes.value.findIndex(r => r.id === data.id)
    if (idx !== -1) {
      recipes.value[idx] = data
    } else {
      recipes.value.push(data)
    }
  }

  function handleRecipeUpdated(data: Recipe) {
    const idx = recipes.value.findIndex(r => r.id === data.id)
    if (idx !== -1) {
      recipes.value[idx] = data
    }
    // Auch im Wochenplan aktualisieren
    for (const entry of weekPlan.value) {
      if (entry.recipe_id === data.id) {
        entry.recipe = data
      }
    }
  }

  function handleRecipeDeleted(data: { id: string }) {
    removeRecipeLocally(data.id)
  }

  function handleMealPlanUpdated(data: MealPlanEntry) {
    // Unvollständige Payload (ältere Server senden nach einem Abstimmungs-Entscheid
    // nur {date}) nicht übernehmen — der Tag erschiene sonst leer (CASA-19): neu laden
    if (!data?.id) {
      fetchWeekPlan().catch(() => {})
      return
    }
    const idx = weekPlan.value.findIndex(e => e.date === data.date)
    if (idx !== -1) {
      weekPlan.value[idx] = data
    } else {
      weekPlan.value.push(data)
    }
  }

  function handleMealPlanDeleted(data: { date: string }) {
    weekPlan.value = weekPlan.value.filter(e => e.date !== data.date)
  }

  /** Haushaltswechsel: Daten gehören zum alten Haushalt. */
  function reset() {
    recipes.value = []
    weekPlan.value = []
  }

  return {
    reset,
    // State
    recipes,
    weekPlan,
    currentWeekStart,
    loading,
    // Recipe Actions
    fetchRecipes,
    createRecipe,
    updateRecipe,
    deleteRecipe,
    toggleFavorite,
    // Meal Plan Actions
    fetchWeekPlan,
    assignMeal,
    removeMeal,
    restoreMeal,
    addMissingToShopping,
    navigateWeek,
    // Socket-Handlers
    handleRecipeCreated,
    handleRecipeUpdated,
    handleRecipeDeleted,
    handleMealPlanUpdated,
    handleMealPlanDeleted,
  }
})
