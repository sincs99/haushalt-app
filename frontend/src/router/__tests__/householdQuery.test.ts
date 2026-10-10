/**
 * CASA-40: Push-Links mit `?hh=<id>` wechseln vor dem Öffnen in den Haushalt der
 * Benachrichtigung; der Parameter verschwindet danach aus der URL.
 */
import type {} from 'vitest'
import { applyHouseholdQuery, type HouseholdSwitcher } from '../householdQuery'

function auth(current: string | null = 'hh-A') {
  return {
    households: [{ id: 'hh-A' }, { id: 'hh-B' }],
    currentHouseholdId: current,
    switchHousehold: vi.fn<(householdId: string) => void>(),
  } satisfies HouseholdSwitcher
}

test('ohne hh: nichts zu tun', () => {
  const a = auth()
  expect(applyHouseholdQuery({ path: '/todos', query: {}, hash: '' }, a)).toBeNull()
  expect(a.switchHousehold).not.toHaveBeenCalled()
})

test('hh eines anderen eigenen Haushalts: wechseln, Parameter entfernen', () => {
  const a = auth('hh-A')
  const target = applyHouseholdQuery({ path: '/pets/p1', query: { hh: 'hh-B', tab: 'meds' }, hash: '' }, a)
  expect(a.switchHousehold).toHaveBeenCalledWith('hh-B')
  expect(target).toEqual({ path: '/pets/p1', query: { tab: 'meds' }, hash: '', replace: true })
})

test('hh des aktuellen Haushalts: kein Wechsel', () => {
  const a = auth('hh-B')
  applyHouseholdQuery({ path: '/todos', query: { hh: 'hh-B' }, hash: '' }, a)
  expect(a.switchHousehold).not.toHaveBeenCalled()
})

test('unbekannter Haushalt (nicht mehr Mitglied): kein Wechsel, Parameter trotzdem weg', () => {
  const a = auth('hh-A')
  const target = applyHouseholdQuery({ path: '/todos', query: { hh: 'hh-X' }, hash: '' }, a)
  expect(a.switchHousehold).not.toHaveBeenCalled()
  expect(target).toEqual({ path: '/todos', query: {}, hash: '', replace: true })
})
