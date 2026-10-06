/**
 * Unit-Tests für den Auth-Store: initialize() mit Cookie-Refresh, Migration alter
 * localStorage-Tokens, Single-Flight-Refresh, Offline-Verhalten, Haushalts-Auswahl,
 * Logout, Cross-Tab-Sync über den Sitzungs-Marker und Token-Erneuerung für den Socket.
 *
 * axios, API-Client, Router, Toast und i18n sind gemockt. tokenStorage läuft echt
 * gegen einen In-Memory-localStorage, damit Marker und Migration mitgetestet werden.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { MeResponse } from '../../types'
import { createMemoryStorage, deferred } from './helpers'

const { axiosPost, api, router, showToast, disablePush, socketDisconnect } = vi.hoisted(() => ({
  axiosPost: vi.fn(),
  api: { get: vi.fn(), post: vi.fn() },
  router: { push: vi.fn(), replace: vi.fn(), currentRoute: { value: { fullPath: '/' } } },
  showToast: vi.fn(),
  disablePush: vi.fn(),
  socketDisconnect: vi.fn(),
}))

vi.mock('axios', () => ({ default: { post: axiosPost } }))
vi.mock('../../api/client', () => ({
  default: api,
  API_BASE: 'http://api.test',
  CSRF_HEADER_NAME: 'X-Requested-With',
  CSRF_HEADER_VALUE: 'casa',
  authRequestConfig: (extra: Record<string, string> = {}) => ({
    withCredentials: true,
    headers: { 'X-Requested-With': 'casa', ...extra },
  }),
}))
vi.mock('../../composables/useToast', () => ({ useToast: () => ({ showToast }) }))
vi.mock('../../i18n', () => ({ default: { global: { t: (key: string) => key } } }))
vi.mock('../../router', () => ({ default: router }))
vi.mock('../../services/pushService', () => ({ disablePush }))
vi.mock('../../composables/useSocket', () => ({ useSocket: () => ({ disconnect: socketDisconnect }) }))

import { useAuthStore } from '../auth'
import { SESSION_MARKER_KEY } from '../../services/tokenStorage'

const HOUSEHOLD_KEY = 'haushalt_household_id'
const LEGACY_TOKEN_KEY = 'haushalt_tokens'
const REFRESH_URL = 'http://api.test/api/auth/refresh'
const LOGOUT_URL = 'http://api.test/api/auth/logout'

/** Erwartete Optionen der Cookie-Endpunkte: Cookie mitsenden + CSRF-Header. */
const cookieRequest = expect.objectContaining({
  withCredentials: true,
  headers: expect.objectContaining({ 'X-Requested-With': 'casa' }),
})

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

/** Antwort der Cookie-Endpunkte: Access-Token im Body, Refresh-Token nur als Cookie. */
const tokenResponse = {
  data: { access_token: 'new-access', refresh_token: null, token_type: 'bearer', expires_in: 900 },
}

function markSession() {
  localStorage.setItem(SESSION_MARKER_KEY, '1')
}

/** Holt den registrierten storage-Listener (Cross-Tab-Sync). */
function storageListener(): (event: Partial<StorageEvent>) => void {
  const call = (window.addEventListener as ReturnType<typeof vi.fn>).mock.calls.find(c => c[0] === 'storage')
  expect(call).toBeDefined()
  return call![1]
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  vi.stubGlobal('localStorage', createMemoryStorage())
  vi.stubGlobal('window', { addEventListener: vi.fn() })
  router.currentRoute.value.fullPath = '/'
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('initialize', () => {
  test('ohne Sitzungs-Marker: kein Request, nicht eingeloggt, authReady löst auf', async () => {
    const store = useAuthStore()

    await store.initialize()

    await expect(store.authReady).resolves.toBeUndefined()
    expect(store.isInitialized).toBe(true)
    expect(store.isAuthenticated).toBe(false)
    expect(axiosPost).not.toHaveBeenCalled()
    expect(api.get).not.toHaveBeenCalled()
  })

  test('mit Sitzungs-Marker: Refresh über den Cookie, dann fetchMe, gespeicherter Haushalt bleibt', async () => {
    markSession()
    localStorage.setItem(HOUSEHOLD_KEY, 'hh-2')
    axiosPost.mockResolvedValue(tokenResponse)
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()

    await store.initialize()

    // Leerer Body: Der Refresh-Token kommt aus dem HttpOnly-Cookie
    expect(axiosPost).toHaveBeenCalledWith(REFRESH_URL, {}, cookieRequest)
    expect(store.token).toBe('new-access')
    expect(store.isAuthenticated).toBe(true)
    expect(store.user).toEqual({ id: 'user-1', email: 'a@example.com', display_name: 'Anna' })
    expect(store.currentHouseholdId).toBe('hh-2')
    expect(store.currentHousehold?.name).toBe('Ferienhaus')
  })

  test('Migration: alter localStorage-Token wird einmalig per Body getauscht und gelöscht', async () => {
    localStorage.setItem(
      LEGACY_TOKEN_KEY,
      JSON.stringify({ accessToken: 'old-access', refreshToken: 'legacy-refresh', accessExpiresAt: 0 }),
    )
    axiosPost.mockResolvedValue(tokenResponse)
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()

    await store.initialize()

    expect(axiosPost).toHaveBeenCalledWith(REFRESH_URL, { refresh_token: 'legacy-refresh' }, cookieRequest)
    expect(localStorage.getItem(LEGACY_TOKEN_KEY)).toBeNull()
    expect(localStorage.getItem(SESSION_MARKER_KEY)).toBe('1')
    expect(store.isAuthenticated).toBe(true)
  })

  test('unlesbarer Legacy-Eintrag wird gelöscht und löst keinen Request aus', async () => {
    localStorage.setItem(LEGACY_TOKEN_KEY, '{not json')
    const store = useAuthStore()

    await store.initialize()

    expect(localStorage.getItem(LEGACY_TOKEN_KEY)).toBeNull()
    expect(axiosPost).not.toHaveBeenCalled()
    expect(store.isAuthenticated).toBe(false)
  })

  test('Refresh abgelehnt (401): State und Sitzungs-Marker werden geleert', async () => {
    markSession()
    localStorage.setItem(HOUSEHOLD_KEY, 'hh-1')
    axiosPost.mockRejectedValue(httpError(401))
    const store = useAuthStore()

    await store.initialize()

    expect(store.isAuthenticated).toBe(false)
    expect(store.currentHouseholdId).toBeNull()
    expect(localStorage.getItem(SESSION_MARKER_KEY)).toBeNull()
    expect(localStorage.getItem(HOUSEHOLD_KEY)).toBeNull()
    expect(api.get).not.toHaveBeenCalled()
    expect(store.isInitialized).toBe(true)
  })

  test('Netzwerkfehler beim Refresh: "offline eingeloggt", Marker bleibt, kein Access-Token', async () => {
    markSession()
    axiosPost.mockRejectedValue(networkError())
    const store = useAuthStore()

    await store.initialize()

    expect(store.isAuthenticated).toBe(true)
    expect(store.hasOfflineSession).toBe(true)
    expect(store.token).toBeNull()
    expect(localStorage.getItem(SESSION_MARKER_KEY)).toBe('1')
    expect(api.get).not.toHaveBeenCalled()
  })

  test('Netzwerkfehler bei fetchMe nach erfolgreichem Refresh: Token bleibt, user ist null', async () => {
    markSession()
    axiosPost.mockResolvedValue(tokenResponse)
    api.get.mockRejectedValue(networkError())
    const store = useAuthStore()

    await store.initialize()

    expect(store.isAuthenticated).toBe(true)
    expect(store.hasOfflineSession).toBe(false)
    expect(store.token).toBe('new-access')
    expect(store.user).toBeNull()
    expect(store.isInitialized).toBe(true)
  })

  test('fetchMe mit 401 nach erfolgreichem Refresh: ausgeloggt', async () => {
    markSession()
    axiosPost.mockResolvedValue(tokenResponse)
    api.get.mockRejectedValue(httpError(401))
    const store = useAuthStore()

    await store.initialize()

    expect(store.isAuthenticated).toBe(false)
    expect(localStorage.getItem(SESSION_MARKER_KEY)).toBeNull()
  })
})

describe('refresh', () => {
  test('Single-Flight: parallele Aufrufe teilen sich einen Request', async () => {
    const pending = deferred<typeof tokenResponse>()
    axiosPost.mockReturnValue(pending.promise)
    const store = useAuthStore()

    const a = store.refresh()
    const b = store.refresh()
    const c = store.refresh()
    await vi.waitFor(() => expect(axiosPost).toHaveBeenCalled())
    pending.resolve(tokenResponse)
    await Promise.all([a, b, c])

    expect(axiosPost).toHaveBeenCalledTimes(1)
    expect(store.token).toBe('new-access')
  })

  test('erfolgreicher Refresh beendet die Offline-Sitzung und setzt den Marker', async () => {
    const store = useAuthStore()
    store.hasOfflineSession = true
    axiosPost.mockResolvedValue(tokenResponse)

    await store.refresh()

    expect(store.hasOfflineSession).toBe(false)
    expect(store.token).toBe('new-access')
    expect(localStorage.getItem(SESSION_MARKER_KEY)).toBe('1')
  })

  test('Fehler wird durchgereicht und gibt das Single-Flight-Promise wieder frei', async () => {
    axiosPost.mockRejectedValueOnce(httpError(401))
    const store = useAuthStore()

    await expect(store.refresh()).rejects.toMatchObject({ response: { status: 401 } })

    axiosPost.mockResolvedValue(tokenResponse)
    await store.refresh()
    expect(store.token).toBe('new-access')
    expect(axiosPost).toHaveBeenCalledTimes(2)
  })
})

describe('login / register', () => {
  test('login sendet Formulardaten mit Cookie-Optionen und übernimmt nur den Access-Token', async () => {
    api.post.mockResolvedValue(tokenResponse)
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()

    await store.login('a@example.com', 'secret')

    expect(api.post).toHaveBeenCalledWith(
      '/api/auth/login',
      expect.any(URLSearchParams),
      expect.objectContaining({
        withCredentials: true,
        headers: expect.objectContaining({
          'X-Requested-With': 'casa',
          'Content-Type': 'application/x-www-form-urlencoded',
        }),
      }),
    )
    expect(store.token).toBe('new-access')
    expect(store.isAuthenticated).toBe(true)
    expect(localStorage.getItem(SESSION_MARKER_KEY)).toBe('1')
    expect(localStorage.getItem(LEGACY_TOKEN_KEY)).toBeNull()
    expect(store.user?.id).toBe('user-1')
  })

  test('register mit Einladungscode sendet Cookie-Optionen', async () => {
    api.post.mockResolvedValue(tokenResponse)
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()

    await store.register('a@example.com', 'secret', 'Anna', { inviteCode: 'ALPHA123' })

    expect(api.post).toHaveBeenCalledWith(
      '/api/auth/register',
      { email: 'a@example.com', password: 'secret', display_name: 'Anna', invite_code: 'ALPHA123' },
      cookieRequest,
    )
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

  test('member_removed für andere User wechselt den Haushalt nicht', async () => {
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()
    await store.fetchMe()

    store.handleMemberRemoved({ household_id: 'hh-1', user_id: 'user-2' })
    await Promise.resolve()

    expect(store.households).toHaveLength(2)
    expect(store.currentHouseholdId).toBe('hh-1')
    expect(showToast).not.toHaveBeenCalled()
  })

  test('member_left einer anderen Person lädt /me neu — die eigene Rolle kann sich geändert haben', async () => {
    // Anna ist Mitglied; der einzige Admin verlässt den Haushalt → Server befördert Anna
    api.get.mockResolvedValueOnce(meResponse({
      households: [{ id: 'hh-1', name: 'WG', role: 'member', currency: 'CHF' }],
    }))
    const store = useAuthStore()
    await store.fetchMe()
    expect(store.currentHousehold?.role).toBe('member')
    api.get.mockResolvedValueOnce(meResponse({
      households: [{ id: 'hh-1', name: 'WG', role: 'admin', currency: 'CHF' }],
    }))

    store.handleMemberLeft({ household_id: 'hh-1', user_id: 'user-2' })
    await vi.waitFor(() => expect(store.currentHousehold?.role).toBe('admin'))

    expect(api.get).toHaveBeenCalledTimes(2)
    expect(store.currentHouseholdId).toBe('hh-1')
    expect(showToast).not.toHaveBeenCalled()
  })

  test('member_left in einem fremden Haushalt löst kein /me aus', async () => {
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()
    await store.fetchMe()

    store.handleMemberLeft({ household_id: 'hh-other', user_id: 'user-2' })
    await Promise.resolve()

    expect(api.get).toHaveBeenCalledTimes(1)
  })

  test('household_updated übernimmt Name und KI-Opt-in', async () => {
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()
    await store.fetchMe()

    store.handleHouseholdUpdated({ id: 'hh-1', name: 'WG neu', ai_enabled: true })
    expect(store.currentHousehold?.name).toBe('WG neu')
    expect(store.currentHousehold?.ai_enabled).toBe(true)

    // Umbenennen ohne Feld lässt das Opt-in unverändert
    store.handleHouseholdUpdated({ id: 'hh-1', name: 'WG' })
    expect(store.currentHousehold?.ai_enabled).toBe(true)
  })
})

describe('logout', () => {
  test('abgelaufene Session: Backend-Logout per Cookie, State und Marker leeren, redirect auf /login', async () => {
    const store = useAuthStore()
    store.token = 'access'
    markSession()
    router.currentRoute.value.fullPath = '/shopping'
    axiosPost.mockResolvedValue({ data: {} })

    await store.logout({ reason: 'expired' })

    expect(disablePush).toHaveBeenCalledWith({ notifyBackend: false })
    expect(axiosPost).toHaveBeenCalledWith(LOGOUT_URL, {}, cookieRequest)
    expect(store.isAuthenticated).toBe(false)
    expect(localStorage.getItem(SESSION_MARKER_KEY)).toBeNull()
    expect(router.push).toHaveBeenCalledWith({ path: '/login', query: { redirect: '/shopping' } })
  })

  test('manueller Logout räumt auch auf, wenn der Backend-Call fehlschlägt', async () => {
    const store = useAuthStore()
    store.token = 'access'
    markSession()
    axiosPost.mockRejectedValue(networkError())

    await store.logout({ reason: 'user' })

    expect(disablePush).toHaveBeenCalledWith({ notifyBackend: true })
    expect(store.isAuthenticated).toBe(false)
    expect(localStorage.getItem(SESSION_MARKER_KEY)).toBeNull()
    expect(router.push).toHaveBeenCalledWith('/login')
  })

  test('Single-Flight: parallele Logouts rufen das Backend nur einmal', async () => {
    const store = useAuthStore()
    store.token = 'access'
    axiosPost.mockResolvedValue({ data: {} })

    await Promise.all([store.logout({ reason: 'user' }), store.logout({ reason: 'user' })])

    expect(axiosPost).toHaveBeenCalledTimes(1)
  })
})

describe('Cross-Tab-Sync über den Sitzungs-Marker', () => {
  test('Logout in anderem Tab: lokalen Zustand verwerfen und zu /login, ohne Backend-Call', async () => {
    markSession()
    axiosPost.mockResolvedValue(tokenResponse)
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()
    await store.initialize()
    axiosPost.mockClear()

    storageListener()({ key: SESSION_MARKER_KEY, newValue: null })
    await vi.waitFor(() => expect(router.push).toHaveBeenCalledWith('/login'))

    expect(store.isAuthenticated).toBe(false)
    expect(store.user).toBeNull()
    expect(axiosPost).not.toHaveBeenCalled()
  })

  test('Login in anderem Tab: Sitzung über den gemeinsamen Cookie übernehmen', async () => {
    const store = useAuthStore()
    await store.initialize() // nicht eingeloggt
    axiosPost.mockResolvedValue(tokenResponse)
    api.get.mockResolvedValue(meResponse())

    storageListener()({ key: SESSION_MARKER_KEY, newValue: '1' })
    await vi.waitFor(() => expect(store.user?.id).toBe('user-1'))

    expect(axiosPost).toHaveBeenCalledWith(REFRESH_URL, {}, cookieRequest)
    expect(store.token).toBe('new-access')
  })

  test('fremde localStorage-Schlüssel werden ignoriert', async () => {
    markSession()
    axiosPost.mockResolvedValue(tokenResponse)
    api.get.mockResolvedValue(meResponse())
    const store = useAuthStore()
    await store.initialize()

    storageListener()({ key: 'something_else', newValue: null })

    expect(store.isAuthenticated).toBe(true)
    expect(router.push).not.toHaveBeenCalled()
  })
})

describe('logout und Socket', () => {
  test('trennt den Socket, bevor das Backend den Logout erhält', async () => {
    const store = useAuthStore()
    store.token = 'access'
    axiosPost.mockResolvedValue({ data: {} })

    await store.logout({ reason: 'user' })

    expect(socketDisconnect).toHaveBeenCalledTimes(1)
    expect(socketDisconnect.mock.invocationCallOrder[0]).toBeLessThan(axiosPost.mock.invocationCallOrder[0])
  })
})

describe('refreshForSocket', () => {
  test('liefert nach erfolgreichem Refresh das neue Access-Token', async () => {
    markSession()
    axiosPost.mockResolvedValue(tokenResponse)
    const store = useAuthStore()
    store.token = 'old-access'

    await expect(store.refreshForSocket()).resolves.toBe('new-access')
    expect(axiosPost).toHaveBeenCalledWith(REFRESH_URL, {}, cookieRequest)
  })

  test('ohne Login: kein Refresh, null', async () => {
    const store = useAuthStore()

    await expect(store.refreshForSocket()).resolves.toBeNull()
    expect(axiosPost).not.toHaveBeenCalled()
  })

  test('Refresh abgelehnt (401): null und Logout mit Grund "expired"', async () => {
    markSession()
    axiosPost.mockRejectedValueOnce(httpError(401)).mockResolvedValue({ data: {} })
    router.currentRoute.value.fullPath = '/todos'
    const store = useAuthStore()
    store.token = 'old-access'

    await expect(store.refreshForSocket()).resolves.toBeNull()
    expect(store.isAuthenticated).toBe(false)
    expect(localStorage.getItem(SESSION_MARKER_KEY)).toBeNull()
    expect(router.push).toHaveBeenCalledWith({ path: '/login', query: { redirect: '/todos' } })
  })

  test('Netzwerkfehler: null, bleibt eingeloggt', async () => {
    markSession()
    axiosPost.mockRejectedValue(networkError())
    const store = useAuthStore()
    store.token = 'old-access'

    await expect(store.refreshForSocket()).resolves.toBeNull()
    expect(store.isAuthenticated).toBe(true)
    expect(localStorage.getItem(SESSION_MARKER_KEY)).toBe('1')
  })

  test('während eines Logouts: kein Refresh (Refresh-Token ist gerade widerrufen)', async () => {
    const logoutCall = deferred<{ data: object }>()
    axiosPost.mockReturnValueOnce(logoutCall.promise)
    const store = useAuthStore()
    store.token = 'access'

    const loggingOut = store.logout({ reason: 'user' })
    await vi.waitFor(() => expect(axiosPost).toHaveBeenCalledTimes(1))

    await expect(store.refreshForSocket()).resolves.toBeNull()
    expect(axiosPost).toHaveBeenCalledTimes(1)

    logoutCall.resolve({ data: {} })
    await loggingOut
  })
})
