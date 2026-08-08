import api from '../api/client'
import type {
  Recipe, RecipeCreatePayload, RecipeUpdatePayload,
  MealPlanEntry, MealPlanAssignPayload, AddToShoppingResponse,
} from '../types'

export interface FoodRepository {
  // Recipes
  fetchRecipes(householdId: string): Promise<Recipe[]>
  fetchRecipe(householdId: string, recipeId: string): Promise<Recipe>
  createRecipe(householdId: string, data: RecipeCreatePayload): Promise<Recipe>
  updateRecipe(householdId: string, recipeId: string, data: RecipeUpdatePayload): Promise<Recipe>
  deleteRecipe(householdId: string, recipeId: string): Promise<void>
  // Meal Plan
  fetchWeekPlan(householdId: string, week: string): Promise<MealPlanEntry[]>
  assignMeal(householdId: string, date: string, data: MealPlanAssignPayload): Promise<MealPlanEntry>
  removeMeal(householdId: string, date: string): Promise<void>
  addMissingToShopping(householdId: string, entryId: string): Promise<AddToShoppingResponse>
}

export function createOnlineFoodRepository(): FoodRepository {
  return {
    // ── Recipes ──

    async fetchRecipes(householdId) {
      const { data } = await api.get<Recipe[]>(
        `/api/households/${householdId}/recipes/`,
      )
      return data
    },

    async fetchRecipe(householdId, recipeId) {
      const { data } = await api.get<Recipe>(
        `/api/households/${householdId}/recipes/${recipeId}`,
      )
      return data
    },

    async createRecipe(householdId, payload) {
      const { data } = await api.post<Recipe>(
        `/api/households/${householdId}/recipes/`,
        payload,
      )
      return data
    },

    async updateRecipe(householdId, recipeId, payload) {
      const { data } = await api.patch<Recipe>(
        `/api/households/${householdId}/recipes/${recipeId}`,
        payload,
      )
      return data
    },

    async deleteRecipe(householdId, recipeId) {
      await api.delete(
        `/api/households/${householdId}/recipes/${recipeId}`,
      )
    },

    // ── Meal Plan ──

    async fetchWeekPlan(householdId, week) {
      const { data } = await api.get<MealPlanEntry[]>(
        `/api/households/${householdId}/meal-plan/`,
        { params: { week } },
      )
      return data
    },

    async assignMeal(householdId, date, payload) {
      const { data } = await api.put<MealPlanEntry>(
        `/api/households/${householdId}/meal-plan/${date}`,
        payload,
      )
      return data
    },

    async removeMeal(householdId, date) {
      await api.delete(
        `/api/households/${householdId}/meal-plan/${date}`,
      )
    },

    async addMissingToShopping(householdId, entryId) {
      const { data } = await api.post<AddToShoppingResponse>(
        `/api/households/${householdId}/meal-plan/${entryId}/add-missing-to-shopping`,
      )
      return data
    },
  }
}
