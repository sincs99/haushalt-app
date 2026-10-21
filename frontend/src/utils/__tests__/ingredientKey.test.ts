import { describe, it, expect } from 'vitest'
import { ingredientKey } from '../ingredientKey'

// Gleiche Fälle wie backend/tests/test_shopping_bulk_add.py::test_ingredient_key
describe('ingredientKey', () => {
  it.each([
    ['Mehl', 'mehl'],
    ['500 g Mehl', 'mehl'],
    ['500g Mehl', 'mehl'],
    ['2 EL Olivenöl', 'olivenöl'],
    ['1/2 Zitrone', 'zitrone'],
    ['1,5 l Milch', 'milch'],
    ['ca. 200 ml Rahm', 'rahm'],
    ['3 Eier', 'eier'],
    ['  Salz  ', 'salz'],
    ['1 Prise Salz', 'salz'],
    ['Gewürze', 'gewürze'],
    ['7Up', '7up'],
  ])('%s → %s', (raw, key) => {
    expect(ingredientKey(raw)).toBe(key)
  })
})
