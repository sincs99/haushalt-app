import { describe, it, expect } from 'vitest'
import type { ShoppingItem } from '../../types'
import { changedItemFields } from '../shoppingEdit'

const item = (o: Partial<ShoppingItem> = {}) => ({
  id: 'i1', name: 'Milch', quantity: '1 l', store: 'Coop', category: null, ...o,
}) as ShoppingItem

describe('changedItemFields (CASA-09)', () => {
  it('liefert nur geänderte Felder', () => {
    expect(changedItemFields(item(), { name: 'Milch', quantity: '2 l', store: 'Coop', category: null }))
      .toEqual({ quantity: '2 l' })
  })

  it('unverändert → leer (kein Request nötig)', () => {
    expect(changedItemFields(item(), { name: 'Milch', quantity: '1 l', store: 'Coop', category: null })).toEqual({})
  })

  it('Leeren eines Felds wird als null gesendet', () => {
    expect(changedItemFields(item(), { name: 'Milch', quantity: null, store: null, category: 'Milchprodukte' }))
      .toEqual({ quantity: null, store: null, category: 'Milchprodukte' })
  })
})
