/**
 * Unit-Tests für die Zahl am App-Icon (Badging API): Laden, Setzen/Entfernen,
 * Entprellen und Verhalten ohne Browser-Unterstützung.
 */
import type {} from 'vitest'

const { api } = vi.hoisted(() => ({ api: { get: vi.fn() } }))
vi.mock('../../api/client', () => ({ default: api }))

const HOUSEHOLD = 'h1'

async function load() {
  vi.resetModules()
  return await import('../useAppBadge')
}

let setAppBadge: ReturnType<typeof vi.fn>
let clearAppBadge: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.resetAllMocks()
  setAppBadge = vi.fn().mockResolvedValue(undefined)
  clearAppBadge = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { setAppBadge, clearAppBadge })
  vi.stubGlobal('document', { visibilityState: 'visible', addEventListener: vi.fn() })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

test('sets the count for the current household', async () => {
  api.get.mockResolvedValue({ data: { count: 3 } })
  const badge = await load()
  badge.setAppBadgeHousehold(HOUSEHOLD)
  await vi.waitFor(() => expect(setAppBadge).toHaveBeenCalledWith(3))
  expect(api.get).toHaveBeenCalledWith(`/api/households/${HOUSEHOLD}/dashboard/badge`)
})

test('clears the badge at zero and on logout', async () => {
  api.get.mockResolvedValue({ data: { count: 0 } })
  const badge = await load()
  badge.setAppBadgeHousehold(HOUSEHOLD)
  await vi.waitFor(() => expect(clearAppBadge).toHaveBeenCalledTimes(1))

  badge.setAppBadgeHousehold(null)
  await vi.waitFor(() => expect(clearAppBadge).toHaveBeenCalledTimes(2))
  expect(setAppBadge).not.toHaveBeenCalled()
})

test('debounces bursts of changes into one request', async () => {
  vi.useFakeTimers()
  api.get.mockResolvedValue({ data: { count: 1 } })
  const badge = await load()
  badge.setAppBadgeHousehold(HOUSEHOLD)
  api.get.mockClear()

  badge.refreshAppBadgeSoon()
  badge.refreshAppBadgeSoon()
  badge.refreshAppBadgeSoon()
  await vi.advanceTimersByTimeAsync(2000)
  expect(api.get).toHaveBeenCalledTimes(1)
})

test('keeps the old count when the request fails', async () => {
  api.get.mockRejectedValue(new Error('offline'))
  const badge = await load()
  badge.setAppBadgeHousehold(HOUSEHOLD)
  await badge.refreshAppBadge()
  expect(setAppBadge).not.toHaveBeenCalled()
  expect(clearAppBadge).not.toHaveBeenCalled()
})

test('does nothing without Badging API support', async () => {
  vi.stubGlobal('navigator', {})
  const badge = await load()
  expect(badge.isAppBadgeSupported()).toBe(false)
  badge.setAppBadgeHousehold(HOUSEHOLD)
  badge.refreshAppBadgeSoon()
  await badge.refreshAppBadge()
  expect(api.get).not.toHaveBeenCalled()
})

test('tells the service worker the current household (CASA-40)', async () => {
  const postMessage = vi.fn()
  vi.stubGlobal('navigator', {
    setAppBadge,
    clearAppBadge,
    serviceWorker: { ready: Promise.resolve({ active: { postMessage } }) },
  })
  api.get.mockResolvedValue({ data: { count: 1 } })
  const badge = await load()

  badge.setAppBadgeHousehold(HOUSEHOLD)
  await vi.waitFor(() => expect(postMessage).toHaveBeenCalledWith({ type: 'casa:current-household', householdId: HOUSEHOLD }))
  badge.setAppBadgeHousehold(HOUSEHOLD) // unverändert → keine weitere Nachricht
  badge.setAppBadgeHousehold(null)
  await vi.waitFor(() => expect(postMessage).toHaveBeenLastCalledWith({ type: 'casa:current-household', householdId: null }))
  expect(postMessage).toHaveBeenCalledTimes(2)
})

test('refreshes after pet deletion and removed chore assignments (CASA-43)', async () => {
  const badge = await load()
  expect(badge.BADGE_EVENTS).toContain('pet_deleted')
  expect(badge.BADGE_EVENTS).toContain('chore_assignments_deleted')
})
