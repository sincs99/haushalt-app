/**
 * Auth-Store in der nativen App (Capacitor): Refresh-Token kommt im Body und wird im
 * Geräte-Speicher abgelegt (hier: localStorage-Fallback ohne Capacitor-Plugin).
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryStorage, deferred } from './helpers'

const { axiosPost, api, router } = vi.hoisted(() => ({
  axiosPost: vi.fn(),
  api: { get: vi.fn(), post: vi.fn() },
  router: { push: vi.fn(), replace: vi.fn(), currentRoute: { value: { fullPath: '/' } } },
}))

vi.mock('axios', () => ({ default: { post: axiosPost } }))
vi.mock('../../services/platform', () => ({ isNativeApp: () => true, platformName: () => 'ios' }))
vi.mock('../../api/client', () => ({
  default: api,
  API_BASE: 'http://api.test',
  CSRF_HEADER_NAME: 'X-Requested-With',
  CSRF_HEADER_VALUE: 'casa',
  // Wie api/client.ts im nativen Modus: kein CSRF-Header, keine Cookies
  authRequestConfig: (extra: Record<string, string> = {}) => ({ headers: { ...extra } }),
}))
vi.mock('../../composables/useToast', () => ({ clearToasts: vi.fn(), useToast: () => ({ showToast: vi.fn() }) }))
vi.mock('../../i18n', () => ({ default: { global: { t: (key: string) => key } } }))
vi.mock('../../router', () => ({ default: router }))
vi.mock('../../services/pushService', () => ({ disablePush: vi.fn() }))
vi.mock('../../composables/useSocket', () => ({ useSocket: () => ({ disconnect: vi.fn() }) }))

import { useAuthStore } from '../auth'
import { nativeRefreshToken } from '../../services/tokenStorage'

const NATIVE_KEY = 'haushalt_native_refresh'
const me = { data: { id: 'u1', email: 'a@example.com', display_name: 'Anna', households: [] } }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.stubGlobal('localStorage', createMemoryStorage())
  vi.stubGlobal('window', { addEventListener: vi.fn() })
  axiosPost.mockReset()
  api.get.mockReset()
  api.post.mockReset()
})

describe('Auth-Store (native App)', () => {
  it('serializes a delayed native token write before logout revocation and removal', async () => {
    const writing = deferred<void>()
    let saved: string | null = null
    const storage = {
      get: vi.fn(async () => ({ value: saved })),
      set: vi.fn(async ({ value }: { value: string }) => { await writing.promise; saved = value }),
      remove: vi.fn(async () => { saved = null }),
    }
    vi.stubGlobal('window', { addEventListener: vi.fn(), Capacitor: { Plugins: { SecureStorage: storage } } })
    axiosPost.mockResolvedValueOnce({ data: { access_token: 'acc', refresh_token: 'rt-late', expires_in: 900 } })
    axiosPost.mockResolvedValueOnce({})
    const store = useAuthStore()
    const login = store.login('a@example.com', 'secret')
    const cancelled = expect(login).rejects.toMatchObject({ code: 'ERR_CANCELED' })
    await vi.waitFor(() => expect(storage.set).toHaveBeenCalled())
    const logout = store.logout({ reason: 'user' })
    expect(store.isAuthenticated).toBe(false)
    writing.resolve()
    await cancelled
    await logout
    expect(axiosPost).toHaveBeenLastCalledWith('http://api.test/api/auth/logout', { refresh_token: 'rt-late' }, { headers: {} })
    expect(saved).toBeNull()
    expect(store.token).toBeNull()
    expect(api.get).not.toHaveBeenCalled()
  })

  it('speichert den Refresh-Token aus dem Login-Body im Geräte-Speicher', async () => {
    axiosPost.mockResolvedValue({ data: { access_token: 'acc', refresh_token: 'rt-1', expires_in: 900 } })
    api.get.mockResolvedValue(me)
    const store = useAuthStore()
    await store.login('a@example.com', 'secret')

    expect(store.token).toBe('acc')
    expect(localStorage.getItem(NATIVE_KEY)).toBe('rt-1')
    expect(await nativeRefreshToken.get()).toBe('rt-1')
  })

  it('schickt den gespeicherten Token beim Start im Body und übernimmt den rotierten', async () => {
    localStorage.setItem(NATIVE_KEY, 'rt-old')
    axiosPost.mockResolvedValue({ data: { access_token: 'acc-2', refresh_token: 'rt-new', expires_in: 900 } })
    api.get.mockResolvedValue(me)
    const store = useAuthStore()
    await store.initialize()

    expect(axiosPost).toHaveBeenCalledWith('http://api.test/api/auth/refresh', { refresh_token: 'rt-old' }, { headers: {} })
    expect(store.isAuthenticated).toBe(true)
    expect(localStorage.getItem(NATIVE_KEY)).toBe('rt-new')
  })

  it('löscht den Token beim Logout und schickt ihn zum Widerrufen mit', async () => {
    localStorage.setItem(NATIVE_KEY, 'rt-1')
    axiosPost.mockResolvedValue({ data: { access_token: 'acc', refresh_token: 'rt-1', expires_in: 900 } })
    api.get.mockResolvedValue(me)
    const store = useAuthStore()
    await store.initialize()
    axiosPost.mockResolvedValue({})

    await store.logout({ reason: 'user' })

    expect(axiosPost).toHaveBeenLastCalledWith('http://api.test/api/auth/logout', { refresh_token: 'rt-1' }, { headers: {} })
    expect(localStorage.getItem(NATIVE_KEY)).toBeNull()
    expect(store.isAuthenticated).toBe(false)
  })
})
