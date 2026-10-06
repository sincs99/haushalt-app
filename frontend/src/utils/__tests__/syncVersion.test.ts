/**
 * Unit-Tests für isStale und upsertVersioned (Offline-Sync M0).
 */
import type {} from 'vitest'
import { isStale, upsertVersioned } from '../syncVersion'

interface Item {
  id: string
  version: number
  name: string
}

const item = (id: string, version: number, name = id): Item => ({ id, version, name })

describe('isStale', () => {
  test('unbekannte Entität ist nie veraltet', () => {
    expect(isStale(undefined, { version: 1 })).toBe(false)
  })

  test('niedrigere Version ist veraltet', () => {
    expect(isStale({ version: 3 }, { version: 2 })).toBe(true)
  })

  test('gleiche Version ist nicht veraltet (Echo)', () => {
    expect(isStale({ version: 2 }, { version: 2 })).toBe(false)
  })

  test('höhere Version ist nicht veraltet', () => {
    expect(isStale({ version: 2 }, { version: 5 })).toBe(false)
  })
})

describe('upsertVersioned', () => {
  test('ersetzt bestehende Entität durch neuere Version', () => {
    const list = [item('a', 1, 'alt')]
    expect(upsertVersioned(list, item('a', 2, 'neu'), false)).toBe(true)
    expect(list).toEqual([item('a', 2, 'neu')])
  })

  test('verwirft veraltete Version', () => {
    const list = [item('a', 3, 'aktuell')]
    expect(upsertVersioned(list, item('a', 2, 'alt'), true)).toBe(false)
    expect(list).toEqual([item('a', 3, 'aktuell')])
  })

  test('optimistischer Eintrag (version 0) wird durch Server-Stand ersetzt', () => {
    const list = [item('a', 0, 'lokal')]
    expect(upsertVersioned(list, item('a', 1, 'server'), false)).toBe(true)
    expect(list[0].name).toBe('server')
  })

  test('fügt fehlende Entität nur bei insertIfMissing an', () => {
    const list: Item[] = []
    expect(upsertVersioned(list, item('a', 1), false)).toBe(false)
    expect(list).toHaveLength(0)
    expect(upsertVersioned(list, item('a', 1), true)).toBe(true)
    expect(list).toHaveLength(1)
  })

  test('erzeugt keine Duplikate bei wiederholtem Insert', () => {
    const list = [item('a', 1)]
    upsertVersioned(list, item('a', 1), true)
    expect(list).toHaveLength(1)
  })
})
