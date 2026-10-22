import axios, { type AxiosRequestConfig } from 'axios'
import { useAuthStore } from '../stores/auth'
import { isNativeApp } from '../services/platform'
import i18n from '../i18n'
import {
  assertDataGeneration, assertSessionGeneration, currentDataGeneration,
  currentScopeSignal, currentSessionGeneration, ScopeChangedError,
} from '../services/sessionScope'

declare module 'axios' {
  interface AxiosRequestConfig<D = any, P = any> {
    _sessionGeneration?: number
    _dataGeneration?: number
    _retried?: boolean
  }
}

export const API_BASE = import.meta.env.VITE_API_URL || ''

const api = axios.create({
  baseURL: API_BASE,
})

/**
 * Kennzeichnet Auth-Requests als Aufruf des Web-Clients. Das Backend liefert den
 * Refresh-Token dann als HttpOnly-Cookie statt im Body und verlangt den Header als
 * CSRF-Schutz für /refresh und /logout (siehe backend/app/routers/auth.py).
 */
export const CSRF_HEADER_NAME = 'X-Requested-With'
export const CSRF_HEADER_VALUE = 'casa'

/**
 * Request-Optionen für die Cookie-basierten Auth-Endpunkte (login, register, refresh,
 * logout): Cookie mitsenden/annehmen (withCredentials — relevant, wenn die API im
 * Dev-Setup auf einem anderen Origin läuft) plus CSRF-Header.
 */
export function authRequestConfig(extraHeaders: Record<string, string> = {}): AxiosRequestConfig {
  const headers = { 'Accept-Language': i18n.global.locale.value, ...extraHeaders }
  if (isNativeApp()) {
    // Native App: kein Cookie-Jar → ohne den Header liefert das Backend den
    // Refresh-Token im Body (services/tokenStorage.ts, nativeRefreshToken)
    return { timeout: 15_000, headers }
  }
  return {
    timeout: 15_000,
    withCredentials: true,
    headers: { [CSRF_HEADER_NAME]: CSRF_HEADER_VALUE, ...headers },
  }
}

// URLs die NICHT refresht werden sollen (kein Retry bei 401)
const AUTH_URLS = ['/api/auth/login', '/api/auth/register', '/api/auth/refresh', '/api/auth/logout']

// Request-Interceptor: JWT als Bearer-Token
api.interceptors.request.use((config) => {
  config._sessionGeneration ??= currentSessionGeneration()
  config._dataGeneration ??= currentDataGeneration()
  assertSessionGeneration(config._sessionGeneration)
  assertDataGeneration(config._dataGeneration)
  const authStore = useAuthStore()
  // All ordinary requests are canceled at the authority boundary. Auth cookie
  // operations use a separate, serialized transport in the auth store.
  config.signal ??= currentScopeSignal()
  if (authStore.token) {
    config.headers.Authorization = `Bearer ${authStore.token}`
  } else {
    config.headers.delete('Authorization')
  }
  try {
    config.headers['Accept-Language'] = i18n.global.locale.value
  } catch {
    // i18n nicht verfügbar (Tests) — Header weglassen
  }
  return config
}, (error) => { throw error }, { synchronous: true })

function assertRequestScope(config: AxiosRequestConfig | undefined): void {
  if (!config || config._sessionGeneration === undefined || config._dataGeneration === undefined) {
    throw new ScopeChangedError()
  }
  assertSessionGeneration(config._sessionGeneration)
  assertDataGeneration(config._dataGeneration)
}

// Response-Interceptor: Bei 401 → Refresh + Retry
api.interceptors.response.use(
  (response) => {
    assertRequestScope(response.config)
    return response
  },
  async (error) => {
    const originalRequest = error.config
    assertRequestScope(originalRequest)

    // Nur bei 401, nicht bei auth-URLs, und nur einmal retrien
    if (
      error.response?.status === 401 &&
      !AUTH_URLS.some(url => originalRequest.url?.includes(url)) &&
      !originalRequest._retried
    ) {
      originalRequest._retried = true

      try {
        const authStore = useAuthStore()
        if (!authStore.isAuthenticated) return Promise.reject(error)
        await authStore.refresh()
        assertRequestScope(originalRequest)

        // Original-Request mit neuem Token wiederholen
        originalRequest.headers.Authorization = `Bearer ${authStore.token}`
        return api(originalRequest)
      } catch (refreshErr: any) {
        assertRequestScope(originalRequest)
        // Refresh fehlgeschlagen → Logout NUR bei Auth-Rejection
        if (refreshErr?.response?.status === 401) {
          const authStore = useAuthStore()
          await authStore.logout({ reason: 'expired' })
        }
        // Bei Netzwerkfehler: KEIN Logout, Error durchreichen
      }
    }

    // 403 wird NICHT als Auth-Fehler behandelt — durchreichen! Ausnahme: "kein Mitglied"
    // für den AKTUELLEN Haushalt heisst, die Entfernung wurde verpasst (z.B. offline):
    // /me neu laden und den Haushalt als verlassen behandeln (CASA-49).
    if (
      error.response?.status === 403 &&
      error.response?.data?.detail?.code === 'NOT_HOUSEHOLD_MEMBER'
    ) {
      const authStore = useAuthStore()
      const householdId = authStore.currentHouseholdId
      if (householdId && originalRequest?.url?.includes(`/api/households/${householdId}`)) {
        void authStore.revalidateMembership()
      }
    }

    return Promise.reject(error)
  },
)

export default api
