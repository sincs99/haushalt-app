import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import api, { API_BASE, authRequestConfig } from '../api/client'
import type { UserInfo, HouseholdInfo, MeResponse } from '../types'
import { sessionMarker, SESSION_MARKER_KEY, takeLegacyRefreshToken } from '../services/tokenStorage'
import { useToast } from '../composables/useToast'
import i18n from '../i18n'

const HOUSEHOLD_KEY = 'haushalt_household_id'

/** Mindestlänge Passwort, wie Backend (RegisterRequest.password min_length) */
export const PASSWORD_MIN_LENGTH = 8

/** Grobe E-Mail-Prüfung für Inline-Fehler; die genaue Prüfung macht das Backend. */
export function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())
}

/** True nur wenn der Server explizit 401 zurückgegeben hat (Auth-Rejection). */
function isAuthRejection(err: any): boolean {
  return err?.response?.status === 401
}

interface TokenPayload {
  access_token: string
  expires_in: number
}

export const useAuthStore = defineStore('auth', () => {
  // State
  // Access-Token nur im Speicher. Der Refresh-Token ist ein HttpOnly-Cookie (casa_rt),
  // den nur das Backend liest — siehe services/tokenStorage.ts.
  const token = ref<string | null>(null)
  /**
   * Beim Start konnte der Refresh wegen eines Netzwerkfehlers nicht laufen, obwohl eine
   * Sitzung existiert (Marker gesetzt): Shell anzeigen, der nächste 401 holt den Token nach.
   */
  const hasOfflineSession = ref(false)
  const user = ref<UserInfo | null>(null)
  const currentHouseholdId = ref<string | null>(null)
  const households = ref<HouseholdInfo[]>([])
  const isInitialized = ref(false)
  /**
   * Letzter Logout war automatisch (Sitzung abgelaufen): LoginView zeigt dann einen Hinweis.
   * Wird bei erfolgreicher Anmeldung und bei manuellem Logout zurückgesetzt.
   */
  const sessionExpired = ref(false)

  // Internes Promise-Setup für authReady
  let _authReadyResolve: () => void
  const authReady = new Promise<void>((resolve) => {
    _authReadyResolve = resolve
  })

  // Getters
  const isAuthenticated = computed(() => !!token.value || hasOfflineSession.value)

  const currentHousehold = computed<HouseholdInfo | null>(() => {
    if (!currentHouseholdId.value || households.value.length === 0) return null
    return households.value.find(h => h.id === currentHouseholdId.value) ?? null
  })

  // ── Actions ──

  async function initialize() {
    if (isInitialized.value) return

    // HouseholdId aus localStorage wiederherstellen
    const savedHouseholdId = localStorage.getItem(HOUSEHOLD_KEY)
    if (savedHouseholdId) {
      currentHouseholdId.value = savedHouseholdId
    }

    // Alte localStorage-Tokens (vor H-01) einmalig gegen den Cookie tauschen
    const legacyRefreshToken = takeLegacyRefreshToken()

    if (legacyRefreshToken || sessionMarker.isSet()) {
      try {
        // Access-Token wird nie persistiert → immer über den Cookie neu holen
        await _refreshWith(legacyRefreshToken)
        await fetchMe()
      } catch (err: any) {
        if (isAuthRejection(err)) {
          // Cookie fehlt/abgelaufen/revoked (Backend hat ihn gelöscht) → ausgeloggt
          await _clearState()
          sessionExpired.value = true
        } else if (!token.value) {
          // Netzwerkfehler beim Refresh → Sitzung vermutlich noch gültig, "offline eingeloggt"
          hasOfflineSession.value = true
        }
        // Netzwerkfehler bei fetchMe nach erfolgreichem Refresh: Token behalten,
        // user/households bleiben null, isAuthenticated bleibt true
      }
    }

    // Cross-Tab storage event Listener registrieren
    _registerStorageListener()

    isInitialized.value = true
    _authReadyResolve()
  }

  // ── Refresh — Single-Flight ──

  let _refreshPromise: Promise<void> | null = null

  async function refresh(): Promise<void> {
    return _refreshWith(null)
  }

  async function _refreshWith(legacyRefreshToken: string | null): Promise<void> {
    // Single-flight: concurrent callers teilen sich dasselbe Promise
    if (_refreshPromise) return _refreshPromise

    _refreshPromise = _doRefresh(legacyRefreshToken)
    try {
      await _refreshPromise
    } finally {
      _refreshPromise = null
    }
  }

  async function _doRefresh(legacyRefreshToken: string | null): Promise<void> {
    // Direkter axios call OHNE Interceptor (um Endlos-Loop zu vermeiden).
    // Der Refresh-Token kommt aus dem HttpOnly-Cookie (withCredentials); nur bei der
    // einmaligen Migration steht der alte localStorage-Token im Body.
    const body = legacyRefreshToken ? { refresh_token: legacyRefreshToken } : {}
    const response = await axios.post(`${API_BASE}/api/auth/refresh`, body, authRequestConfig())
    _applyTokens(response.data)
  }

  /** Übernimmt den Access-Token einer Login-/Register-/Refresh-Antwort (Cookie setzt der Browser). */
  function _applyTokens(data: TokenPayload) {
    token.value = data.access_token
    hasOfflineSession.value = false
    sessionExpired.value = false
    sessionMarker.set()
  }

  /**
   * Frisches Access-Token für den Socket, nachdem der Server ihn wegen Ablauf getrennt hat.
   * null, wenn ausgeloggt (oder Logout läuft) oder der Refresh nicht klappt; lehnt der
   * Server den Refresh-Token ab, wird wie beim API-Interceptor ausgeloggt.
   */
  async function refreshForSocket(): Promise<string | null> {
    if (_logoutPromise || !token.value) return null
    try {
      await refresh()
      return token.value
    } catch (err: any) {
      if (isAuthRejection(err)) await logout({ reason: 'expired' })
      return null
    }
  }

  // ── Login ──

  async function login(email: string, password: string) {
    const response = await api.post(
      '/api/auth/login',
      new URLSearchParams({ username: email, password }),
      authRequestConfig({ 'Content-Type': 'application/x-www-form-urlencoded' }),
    )
    _applyTokens(response.data)

    await fetchMe()
  }

  // ── Register ──

  async function register(
    email: string,
    password: string,
    displayName: string,
    options: { householdName: string } | { inviteCode: string },
  ) {
    const payload: Record<string, string> = {
      email,
      password,
      display_name: displayName,
    }
    if ('householdName' in options) {
      payload.household_name = options.householdName
    } else {
      payload.invite_code = options.inviteCode
    }
    const response = await api.post('/api/auth/register', payload, authRequestConfig())
    _applyTokens(response.data)

    await fetchMe()
  }

  // ── Fetch Me ──

  async function fetchMe() {
    const response = await api.get<MeResponse>('/api/auth/me')
    const data = response.data
    user.value = {
      id: data.id,
      email: data.email,
      display_name: data.display_name,
    }
    households.value = data.households

    if (data.households.length > 0) {
      // Bestehendes Household beibehalten falls noch gültig
      const stillValid = data.households.some(h => h.id === currentHouseholdId.value)
      if (!stillValid) {
        currentHouseholdId.value = data.households[0].id
        localStorage.setItem(HOUSEHOLD_KEY, currentHouseholdId.value!)
      }
    }
  }

  // ── Switch Household ──

  function switchHousehold(householdId: string) {
    currentHouseholdId.value = householdId
    localStorage.setItem(HOUSEHOLD_KEY, householdId)
  }

  // ── Logout — Single-Flight ──

  let _logoutPromise: Promise<void> | null = null

  async function logout(options?: { reason?: 'user' | 'expired' }): Promise<void> {
    // Single-flight: concurrent callers teilen sich dasselbe Promise
    if (_logoutPromise) return _logoutPromise
    _logoutPromise = _doLogout(options)
    try {
      await _logoutPromise
    } finally {
      _logoutPromise = null
    }
  }

  async function _doLogout(options?: { reason?: 'user' | 'expired' }): Promise<void> {
    const reason = options?.reason ?? 'expired'

    // Socket zuerst trennen: Der Logout-Aufruf beendet serverseitig alle Verbindungen
    // des Users; diese hier soll darauf nicht mehr reagieren (kein Reconnect/Refresh).
    try {
      const { useSocket } = await import('../composables/useSocket')
      useSocket().disconnect()
    } catch {
      // Best-effort
    }

    // Gerät vom Push abmelden, damit nach dem Logout keine Erinnerungen mehr ankommen.
    // Backend nur bei manuellem Logout informieren: Bei 'expired' ist der Access-Token
    // ungültig, der 401-Interceptor würde erneut logout() aufrufen (Single-Flight-Deadlock).
    try {
      const { disablePush } = await import('../services/pushService')
      await disablePush({ notifyBackend: reason === 'user' })
    } catch {
      // Best-effort
    }

    // Best-effort: Backend revoked den Refresh-Token aus dem Cookie und löscht den Cookie.
    // Ob ein Cookie existiert, sieht JS nicht (HttpOnly) — der Endpunkt ist idempotent.
    try {
      await axios.post(`${API_BASE}/api/auth/logout`, {}, authRequestConfig())
    } catch {
      // Ignore — Logout ist best-effort
    }

    await _clearState()
    sessionExpired.value = reason === 'expired'

    const { default: router } = await import('../router')
    if (reason === 'expired') {
      const currentPath = router.currentRoute.value.fullPath
      if (currentPath && currentPath !== '/login' && currentPath !== '/register') {
        router.push({ path: '/login', query: { redirect: currentPath } })
      } else {
        router.push('/login')
      }
    } else {
      // Manueller Logout → kein redirect
      router.push('/login')
    }
  }

  // ── Internal: State zurücksetzen (async) ──

  async function _clearState() {
    token.value = null
    hasOfflineSession.value = false
    user.value = null
    currentHouseholdId.value = null
    households.value = []
    // Löscht den Marker → storage-Event in anderen Tabs (Cross-Tab-Logout)
    sessionMarker.clear()
    localStorage.removeItem(HOUSEHOLD_KEY)
  }

  // ── Cross-Tab Storage Listener ──
  //
  // Der Refresh-Token selbst muss nicht mehr zwischen Tabs abgeglichen werden: Alle Tabs
  // teilen sich den Cookie, jeder Tab holt sich seinen Access-Token selbst (Grace-Window
  // im Backend fängt gleichzeitige Refreshes ab). Synchronisiert werden nur Logout und Login.

  function _registerStorageListener() {
    window.addEventListener('storage', (event) => {
      if (event.key !== SESSION_MARKER_KEY) return

      if (event.newValue === null) {
        // Anderer Tab hat sich abgemeldet (Cookie ist weg) → lokalen Zustand verwerfen
        if (!isAuthenticated.value) return
        _clearState()
        // Navigiere zu /login OHNE redirect und OHNE Backend-Logout-Call
        import('../router').then(({ default: router }) => {
          router.push('/login')
        })
      } else if (!token.value) {
        // Anderer Tab hat sich angemeldet → Sitzung über den gemeinsamen Cookie übernehmen
        refresh()
          .then(() => fetchMe())
          .catch(() => {
            // Best-effort — der nächste geschützte Request versucht es erneut
          })
      }
    })
  }

  // ── Socket-Event-Handler für Household-Events ──

  function handleHouseholdUpdated(data: { id: string; name: string; ai_enabled?: boolean }) {
    const h = households.value.find(h => h.id === data.id)
    if (!h) return
    h.name = data.name
    if (typeof data.ai_enabled === 'boolean') h.ai_enabled = data.ai_enabled
  }

  function handleMemberJoined(_data: { household_id: string; user_id: string; display_name: string; role: string }) {
    // Kein State-Update nötig im auth store — HouseholdView refetcht Members
  }

  function handleMemberLeft(data: { household_id: string; user_id: string }) {
    _handleRemoval(data.household_id, data.user_id)
  }

  function handleMemberRemoved(data: { household_id: string; user_id: string }) {
    _handleRemoval(data.household_id, data.user_id)
  }

  // ── Haushalt verlassen ──

  /** Haushalte, die der User gerade selbst verlässt (Socket-Event ist dann keine „Entfernung“). */
  const _ownLeaves = new Set<string>()

  /**
   * Eigener Austritt: `request` ruft die API auf. Das Socket-Event `household_member_left`
   * kann schon vor der HTTP-Antwort eintreffen – solange der Austritt läuft, entfernt
   * _handleRemoval den Haushalt nur still (kein „Du wurdest entfernt“, keine Navigation).
   * Gibt das Navigationsziel zurück; Meldung und Navigation übernimmt die View.
   */
  async function leaveHousehold(
    householdId: string,
    request: () => Promise<unknown>,
  ): Promise<'/dashboard' | '/no-household'> {
    _ownLeaves.add(householdId)
    try {
      await request()
      _dropHousehold(householdId)
    } finally {
      _ownLeaves.delete(householdId)
    }
    return households.value.length > 0 ? '/dashboard' : '/no-household'
  }

  /** Haushalt lokal entfernen; war er aktiv, auf den nächsten wechseln (oder keinen). */
  function _dropHousehold(householdId: string) {
    households.value = households.value.filter(h => h.id !== householdId)
    if (currentHouseholdId.value !== householdId) return
    if (households.value.length > 0) {
      switchHousehold(households.value[0].id)
    } else {
      currentHouseholdId.value = null
      localStorage.removeItem(HOUSEHOLD_KEY)
    }
  }

  function _handleRemoval(householdId: string, userId: string) {
    // Eigener Austritt läuft gerade → still entfernen, die View meldet und navigiert
    if (userId === user.value?.id && _ownLeaves.has(householdId)) {
      _dropHousehold(householdId)
      return
    }
    // Betrifft es den EIGENEN User im AKTUELLEN Haushalt?
    if (userId === user.value?.id && householdId === currentHouseholdId.value) {
      const removedName = households.value.find(h => h.id === householdId)?.name ?? ''
      // Haushalt aus Liste entfernen
      households.value = households.value.filter(h => h.id !== householdId)

      // Toast + Navigation
      const { showToast } = useToast()
      const { t } = i18n.global

      if (households.value.length > 0) {
        // Auf ersten verbleibenden Haushalt wechseln
        switchHousehold(households.value[0].id)
        showToast(t('household.switchedTo', { name: households.value[0].name }), 'info')
      } else {
        // Kein Haushalt mehr → Zustand "kein Haushalt"
        currentHouseholdId.value = null
        localStorage.removeItem(HOUSEHOLD_KEY)
        showToast(t('household.youWereRemoved', { name: removedName }), 'info')
        // Navigation analog logout()
        import('../router').then(({ default: router }) => {
          router.replace('/no-household')
        })
      }
    }
  }

  return {
    // State
    token,
    hasOfflineSession,
    user,
    currentHouseholdId,
    households,
    isInitialized,
    authReady,
    sessionExpired,
    // Getters
    isAuthenticated,
    currentHousehold,
    // Actions
    initialize,
    login,
    register,
    fetchMe,
    refresh,
    refreshForSocket,
    switchHousehold,
    leaveHousehold,
    logout,
    // Socket-Event-Handler
    handleHouseholdUpdated,
    handleMemberJoined,
    handleMemberLeft,
    handleMemberRemoved,
  }
})
