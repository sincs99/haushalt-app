import type { Recipe, RecipeCreatePayload, RecipeUpdatePayload } from '../types'
import { parseAmountToRappen } from './money'

/**
 * Formular „Rezept erstellen/bearbeiten“ (P3) ↔ API-Payload.
 * Zutaten und Schritte: eine pro Zeile; Tags: durch Komma getrennt.
 * Grenzen wie im Backend (app/routers/food.py RecipeCreate).
 */
export interface RecipeForm {
  name: string
  servings: string
  cost: string
  duration: string
  ingredients: string
  steps: string
  tags: string
}

export const RECIPE_LIMITS = {
  name: 150, ingredient: 200, ingredients: 100, step: 1000, steps: 30, tag: 30, tags: 10,
} as const

export type RecipeFormError = 'name' | 'servings' | 'cost' | 'duration' | 'ingredients' | 'steps' | 'tags'

export function emptyRecipeForm(): RecipeForm {
  return { name: '', servings: '2', cost: '', duration: '', ingredients: '', steps: '', tags: '' }
}

export function recipeToForm(recipe: Recipe): RecipeForm {
  return {
    name: recipe.name,
    servings: String(recipe.servings),
    cost: recipe.cost_rappen != null ? (recipe.cost_rappen / 100).toFixed(2) : '',
    duration: recipe.duration_min != null ? String(recipe.duration_min) : '',
    ingredients: recipe.ingredients.join('\n'),
    steps: (recipe.steps ?? []).join('\n'),
    tags: (recipe.tags ?? []).join(', '),
  }
}

function lines(text: string): string[] {
  return text.split('\n').map(l => l.trim()).filter(Boolean)
}

function positiveInt(text: string): number | null | undefined {
  const trimmed = text.trim()
  if (!trimmed) return undefined
  if (!/^\d+$/.test(trimmed)) return null
  const n = parseInt(trimmed, 10)
  return n >= 1 ? n : null
}

/** Formular → Create-Payload; bei ungültigen Feldern die Liste der Fehlerfelder. */
export function formToPayload(form: RecipeForm): { payload: RecipeCreatePayload } | { errors: RecipeFormError[] } {
  const errors: RecipeFormError[] = []
  const name = form.name.trim()
  if (!name || name.length > RECIPE_LIMITS.name) errors.push('name')

  const servings = positiveInt(form.servings)
  if (servings == null) errors.push('servings')

  let cost: number | null = null
  if (form.cost.trim()) {
    cost = parseAmountToRappen(form.cost)
    if (cost == null) errors.push('cost')
  }

  const duration = positiveInt(form.duration)
  if (duration === null) errors.push('duration')

  const ingredients = lines(form.ingredients)
  if (ingredients.length > RECIPE_LIMITS.ingredients || ingredients.some(i => i.length > RECIPE_LIMITS.ingredient)) {
    errors.push('ingredients')
  }
  const steps = lines(form.steps)
  if (steps.length > RECIPE_LIMITS.steps || steps.some(s => s.length > RECIPE_LIMITS.step)) errors.push('steps')

  const tags = [...new Set(form.tags.split(',').map(t => t.trim()).filter(Boolean))]
  if (tags.length > RECIPE_LIMITS.tags || tags.some(t => t.length > RECIPE_LIMITS.tag)) errors.push('tags')

  if (errors.length) return { errors }
  return {
    payload: {
      name,
      servings: servings as number,
      cost_rappen: cost,
      duration_min: duration ?? null,
      ingredients,
      steps,
      tags,
    },
  }
}

/** Nur geänderte Felder fürs PATCH (wie beim Einkaufs-Item, CASA-09). */
export function changedRecipeFields(original: Recipe, payload: RecipeCreatePayload): RecipeUpdatePayload {
  const changes: RecipeUpdatePayload = {}
  const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
  if (!same(original.name, payload.name)) changes.name = payload.name
  if (!same(original.servings, payload.servings)) changes.servings = payload.servings
  if (!same(original.cost_rappen, payload.cost_rappen)) changes.cost_rappen = payload.cost_rappen ?? null
  if (!same(original.duration_min, payload.duration_min)) changes.duration_min = payload.duration_min ?? null
  if (!same(original.ingredients, payload.ingredients)) changes.ingredients = payload.ingredients
  if (!same(original.steps ?? [], payload.steps)) changes.steps = payload.steps
  if (!same(original.tags ?? [], payload.tags)) changes.tags = payload.tags
  return changes
}
