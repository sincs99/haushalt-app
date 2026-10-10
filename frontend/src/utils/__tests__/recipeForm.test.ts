import { describe, it, expect } from 'vitest'
import type { Recipe } from '../../types'
import { changedRecipeFields, emptyRecipeForm, formToPayload, recipeToForm } from '../recipeForm'

const recipe = (o: Partial<Recipe> = {}): Recipe => ({
  id: 'r1', household_id: 'h1', name: 'Zopf', servings: 4, cost_rappen: 850, duration_min: 90,
  ingredients: ['500 g Mehl', '1 Ei'], steps: ['Kneten', 'Backen'], tags: ['Sonntag'],
  is_favorite: false, created_at: '2026-01-01T00:00:00Z', ...o,
})

describe('recipeForm', () => {
  it('Formular → Payload: Zeilen, Tags, CHF → Rappen', () => {
    const result = formToPayload({
      name: '  Zopf ', servings: '4', cost: '8.50', duration: '90',
      ingredients: '500 g Mehl\n\n 1 Ei \n', steps: 'Kneten\nBacken', tags: 'Sonntag, schnell, Sonntag',
    })
    expect(result).toEqual({
      payload: {
        name: 'Zopf', servings: 4, cost_rappen: 850, duration_min: 90,
        ingredients: ['500 g Mehl', '1 Ei'], steps: ['Kneten', 'Backen'], tags: ['Sonntag', 'schnell'],
      },
    })
  })

  it('leere optionale Felder → null', () => {
    const result = formToPayload({ ...emptyRecipeForm(), name: 'Salat' })
    expect(result).toEqual({
      payload: { name: 'Salat', servings: 2, cost_rappen: null, duration_min: null, ingredients: [], steps: [], tags: [] },
    })
  })

  it('ungültige Felder werden gemeldet', () => {
    const result = formToPayload({
      ...emptyRecipeForm(), name: ' ', servings: '0', cost: 'abc', duration: '-5',
      tags: Array.from({ length: 11 }, (_, i) => `t${i}`).join(','),
    })
    expect(result).toEqual({ errors: ['name', 'servings', 'cost', 'duration', 'tags'] })
  })

  it('Rundreise Rezept → Formular → Payload ohne Änderung ergibt leeres PATCH', () => {
    const r = recipe()
    const result = formToPayload(recipeToForm(r))
    if (!('payload' in result)) throw new Error('invalid')
    expect(changedRecipeFields(r, result.payload)).toEqual({})
  })

  it('PATCH enthält nur Geändertes', () => {
    const r = recipe()
    const result = formToPayload({ ...recipeToForm(r), servings: '6', cost: '' })
    if (!('payload' in result)) throw new Error('invalid')
    expect(changedRecipeFields(r, result.payload)).toEqual({ servings: 6, cost_rappen: null })
  })
})
