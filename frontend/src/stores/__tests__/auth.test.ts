/**
 * Unit-Tests für den Auth-Store: initialize() mit Token-Refresh-Pfad,
 * Single-Flight-Refresh, Offline-Verhalten, Haushalts-Auswahl und Logout.
 *
 * axios, API-Client, tokenStorage, Router, Toast und i18n sind gemockt.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { MeResponse } from '../../types'
import type { Tokens } from '../../services/tokenStorage'
import { createMemoryStorage, deferred } from './helpers'

const { axiosPost, api, tokenStorage, router, showToast, disablePush } = vi.hoisted(() => ({
  axiosPost: vi.fn(),
  api: { get: vi.fn(), post: vi.fn() },
  tokenStorage: { get: vi.fn(), set: vi.fn(), clear: vi.fn() },
  router: { push: vi.fn(), replace: vi.fn(), currentRoute: { value: { fullPath: '/' } } },
  showToast: vi.fn(),
  disablePush: vi.fn(),
}))

vi.mock('axios', () => ({ default: { post: axiosPost } }))
vi.mock('../../api/client', () => ({ default: api, API_BASE: 'http://api.test' }))
vi.mock('../../services/tokenStorage', () => ({ tokenStorage, TOKEN_STORAGE_KEY: 'haushalt_tokens' }))
vi.mock('../../composables/useToast', () => ({ useToast: () => ({ showToast }) }))
vi.mock('../../i18n', () => ({ default: { global: { t: (key: string) => key } } }))
vi.mock('../../router', () => ({ default: router }))
vi.mock('../../services/pushService', () => ({ disablePush }))

import { useAuthStore } from '../auth'

const HOUSEHOLD_KEY = 'haushalt_household_id'

const savedTokens: Tokens = {
  accessToken: 'old-access',
  refreshToken: 'old-refresh',
  accessExpiresAt: 0,
}

function meResponse(overrides: Partial<MeResponse> = {}): { data: MeResponse } {
  return {
    data: {
      id: 'user-1',
      email: 'a@example.com',
      display_name: 'Anna',
      households: [
        { id: 'hh-1', name: 'WG', role: 'owner', currency: 'CHF' },
        { id: 'hh-2', name: 'Ferienhaus', role: 'member', currency: 'CHF' },
      ],
      ...overrides,
    },
  }
}

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } })
}

function networkError() {
  return new Error('Network Error') // kein response-Feld
}

const refreshResponse = {
  data: { access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 900 },
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  vi.stubGlobal('localStorage', createMemoryStorage())
  vi.stubGlobal('window', { addEventListener: vi.fn() })
  router.currentRoute.value.fullPath = '/'
  tokenStorage.set.mockResolvedValue(undefined)
  tokenStorage.clear.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('initialize', () => {
  test('ohne gespeicherte Tokens: initialisiert, nicht eingeloggt, authReady löst auf', async () => {
    tokenStorage.get.mockResolvedValue(null)
    const store = useAuthStore()

    await store.initialize()

    await expect(store.authReady).resolves.toBeUndefined()
    expect(store.isInitialized).toBe(true)
    expect(store.isAuthenticated).toBe(false)
    expect(api.get).not.toHaveBeenCalled()
  })

  test('mit gültigem Token: lädt User und behält den gespeicherten Haushalt', async () => {
    tokenStorage.get.mockResolvedValue(savedTokens)
    localStorage.setItem(HOUSEHOLD_KEY, 'hh-2')
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()

    await store.initialize()

    expect(store.isAuthenticated).toBe(true)
    expect(store.user).toEqual({ id: 'user-1', email: 'a@example.com', display_name: 'Anna' })
    expect(store.currentHouseholdId).toBe('hh-2')
    expect(store.currentHousehold?.name).toBe('Ferienhaus')
    expect(axiosPost).not.toHaveBeenCalled()
  })

  test('abgelaufener Access-Token (401): Refresh, neue Tokens persistieren, fetchMe wiederholen', async () => {
    tokenStorage.get.mockResolvedValue(savedTokens)
    api.get.mockRejectedValueOnce(httpError(401)).mockResolvedValueOnce(meResponse())
    axiosPost.mockResolvedValue(refreshResponse)
    const store = useAuthStore()

    await store.initialize()

    expect(axiosPost).toHaveBeenCalledWith('http://api.test/api/auth/refresh', { refresh_token: 'old-refresh' })
    expect(store.token).toBe('new-access')
    expect(store.refreshToken).toBe('new-refresh')
    expect(tokenStorage.set).toHaveBeenCalledWith(expect.objectContaining({
      accessToken: 'new-access',
      refreshToken: 'new-refresh',
    }))
    expect(api.get).toHaveBeenCalledTimes(2)
    expect(store.user?.id).toBe('user-1')
  })

  test('Refresh abgelehnt (401): State und Token-Storage werden geleert', async () => {
    tokenStorage.get.mockResolvedValue(savedTokens)
    localStorage.setItem(HOUSEHOLD_KEY, 'hh-1')
    api.get.mockRejectedValue(httpError(401))
    axiosPost.mockRejectedValue(httpError(401))
    const store = useAuthStore()

    await store.initialize()

    expect(store.isAuthenticated).toBe(false)
    expect(store.currentHouseholdId).toBeNull()
    expect(tokenStorage.clear).toHaveBeenCalled()
    expect(localStorage.getItem(HOUSEHOLD_KEY)).toBeNull()
    expect(store.isInitialized).toBe(true)
  })

  test('Netzwerkfehler beim Refresh: Tokens bleiben erhalten ("offline eingeloggt")', async () => {
    tokenStorage.get.mockResolvedValue(savedTokens)
    api.get.mockRejectedValue(httpError(401))
    axiosPost.mockRejectedValue(networkError())
    const store = useAuthStore()

    await store.initialize()

    expect(store.isAuthenticated).toBe(true)
    expect(store.refreshToken).toBe('old-refresh')
    expect(tokenStorage.clear).not.toHaveBeenCalled()
  })

  test('Netzwerkfehler bei fetchMe: kein Refresh-Versuch, Tokens bleiben', async () => {
    tokenStorage.get.mockResolvedValue(savedTokens)
    api.get.mockRejectedValue(networkError())
    const store = useAuthStore()

    await store.initialize()

    expect(axiosPost).not.toHaveBeenCalled()
    expect(store.isAuthenticated).toBe(true)
    expect(store.user).toBeNull()
    expect(store.isInitialized).toBe(true)
  })
})

describe('refresh', () => {
  test('Single-Flight: parallele Aufrufe teilen sich einen Request', async () => {
    tokenStorage.get.mockResolvedValue(savedTokens)
    const pending = deferred<typeof refreshResponse>()
    axiosPost.mockReturnValue(pending.promise)
    const store = useAuthStore()

    const a = store.refresh()
    const b = store.refresh()
    const c = store.refresh()
    await vi.waitFor(() => expect(axiosPost).toHaveBeenCalled())
    pending.resolve(refreshResponse)
    await Promise.all([a, b, c])

    expect(axiosPost).toHaveBeenCalledTimes(1)
    expect(store.token).toBe('new-access')
  })

  test('verwendet den neuesten Refresh-Token aus dem Storage (anderer Tab hat rotiert)', async () => {
    const store = useAuthStore()
    store.refreshToken = 'stale-refresh'
    tokenStorage.get.mockResolvedValue({ ...savedTokens, refreshToken: 'rotated-refresh' })
    axiosPost.mockResolvedValue(refreshResponse)

    await store.refresh()

    expect(axiosPost).toHaveBeenCalledWith(expect.any(String), { refresh_token: 'rotated-refresh' })
  })

  test('wirft ohne Refresh-Token und gibt das Single-Flight-Promise wieder frei', async () => {
    tokenStorage.get.mockResolvedValue(null)
    const store = useAuthStore()

    await expect(store.refresh()).rejects.toThrow('No refresh token')
    expect(axiosPost).not.toHaveBeenCalled()

    tokenStorage.get.mockResolvedValue(savedTokens)
    axiosPost.mockResolvedValue(refreshResponse)
    await store.refresh()
    expect(store.token).toBe('new-access')
  })
})

describe('Haushalte', () => {
  test('fetchMe wählt den ersten Haushalt, wenn der gespeicherte nicht mehr gültig ist', async () => {
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()
    store.currentHouseholdId = 'removed-hh'

    await store.fetchMe()

    expect(store.currentHouseholdId).toBe('hh-1')
    expect(localStorage.getItem(HOUSEHOLD_KEY)).toBe('hh-1')
  })

  test('member_removed für den eigenen User wechselt auf den nächsten Haushalt', async () => {
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()
    await store.fetchMe()

    store.handleMemberRemoved({ household_id: 'hh-1', user_id: 'user-1' })

    expect(store.households.map(h => h.id)).toEqual(['hh-2'])
    expect(store.currentHouseholdId).toBe('hh-2')
    expect(showToast).toHaveBeenCalledWith('household.switchedTo', 'info')
  })

  test('member_removed für andere User ändert nichts', async () => {
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()
    await store.fetchMe()

    store.handleMemberRemoved({ household_id: 'hh-1', user_id: 'user-2' })

    expect(store.households).toHaveLength(2)
    expect(store.currentHouseholdId).toBe('hh-1')
    expect(showToast).not.toHaveBeenCalled()
  })
})

describe('logout', () => {
  test('abgelaufene Session: State leeren und mit redirect auf /login', async () => {
    const store = useAuthStore()
    store.token = 'access'
    store.refreshToken = 'refresh'
    router.currentRoute.value.fullPath = '/shopping'
    axiosPost.mockResolvedValue({ data: {} })

    await store.logout({ reason: 'expired' })

    expect(disablePush).toHaveBeenCalledWith({ notifyBackend: false })
    expect(axiosPost).toHaveBeenCalledWith('http://api.test/api/auth/logout', { refresh_token: 'refresh' })
    expect(store.isAuthenticated).toBe(false)
    expect(tokenStorage.clear).toHaveBeenCalled()
    expect(router.push).toHaveBeenCalledWith({ path: '/login', query: { redirect: '/shopping' } })
  })

  test('manueller Logout räumt auch auf, wenn der Backend-Call fehlschlägt', async () => {
    const store = useAuthStore()
    store.token = 'access'
    store.refreshToken = 'refresh'
    axiosPost.mockRejectedValue(networkError())

    await store.logout({ reason: 'user' })

    expect(disablePush).toHaveBeenCalledWith({ notifyBackend: true })
    expect(store.isAuthenticated).toBe(false)
    expect(router.push).toHaveBeenCalledWith('/login')
  })
})
