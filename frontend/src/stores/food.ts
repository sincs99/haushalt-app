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
    recipes.value = recipes.value.filter(r => r.id !== id)
  }

  async function toggleFavorite(id: string) {
    const recipe = recipes.value.find(r => r.id === id)
    if (!recipe) return
    return updateRecipe(id, { is_favorite: !recipe.is_favorite })
  }

  // ── Meal Plan Actions ──

  async function fetchWeekPlan(weekDate?: string) {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    const week = weekDate ?? currentWeekStart.value
    loading.value = true
    try {
      weekPlan.value = await repo.fetchWeekPlan(householdId, week)
    } finally {
      loading.value = false
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

  async function removeMeal(date: string) {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    await repo.removeMeal(householdId, date)
    weekPlan.value = weekPlan.value.filter(e => e.date !== date)
  }

  async function addMissingToShopping(entryId: string): Promise<AddToShoppingResponse | undefined> {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    return repo.addMissingToShopping(householdId, entryId)
  }

  function navigateWeek(direction: -1 | 1) {
    const d = new Date(currentWeekStart.value + 'T00:00:00')
    d.setDate(d.getDate() + direction * 7)
    currentWeekStart.value = toISODate(d)
    fetchWeekPlan()
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
    recipes.value = recipes.value.filter(r => r.id !== data.id)
  }

  function handleMealPlanUpdated(data: MealPlanEntry) {
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

  return {
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
