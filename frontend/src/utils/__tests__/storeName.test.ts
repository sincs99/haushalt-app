import { describe, it, expect } from 'vitest'
import { normalizeStoreName, storeKey, storesEqual, findCanonicalStore } from '../storeName'

describe('normalizeStoreName', () => {
  it('trims and collapses whitespace', () => {
    expect(normalizeStoreName('  Coop   City  ')).toBe('Coop City')
  })

  it('maps blank values to null', () => {
    expect(normalizeStoreName('   ')).toBeNull()
    expect(normalizeStoreName('')).toBeNull()
    expect(normalizeStoreName(null)).toBeNull()
    expect(normalizeStoreName(undefined)).toBeNull()
  })
})

describe('storeKey / storesEqual', () => {
  it('compares case-insensitively and ignores surrounding whitespace', () => {
    expect(storeKey(' COOP ')).toBe('coop')
    expect(storesEqual('Coop', 'coop ')).toBe(true)
    expect(storesEqual('Coop', 'Migros')).toBe(false)
  })

  it('treats empty values as equal to each other but not to a store', () => {
    expect(storesEqual(null, '')).toBe(true)
    expect(storesEqual(null, 'Coop')).toBe(false)
  })
})

describe('findCanonicalStore', () => {
  const stores = ['Aldi', 'Coop', 'Migros']

  it('returns the existing spelling for a case-insensitive match', () => {
    expect(findCanonicalStore(stores, 'coop')).toBe('Coop')
    expect(findCanonicalStore(stores, ' MIGROS ')).toBe('Migros')
  })

  it('returns null when nothing matches or the value is blank', () => {
    expect(findCanonicalStore(stores, 'Lidl')).toBeNull()
    expect(findCanonicalStore(stores, '  ')).toBeNull()
    expect(findCanonicalStore(stores, null)).toBeNull()
  })
})
