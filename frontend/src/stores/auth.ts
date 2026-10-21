import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import axios from 'axios'
import api, { API_BASE, authRequestConfig } from '../api/client'
import type { UserInfo, HouseholdInfo, MeResponse, TokenResponse } from '../types'
import { nativeRefreshToken, sessionMarker, SESSION_MARKER_KEY, takeLegacyRefreshToken } from '../services/tokenStorage'
import { isNativeApp } from '../services/platform'
import { useToast } from '../composables/useToast'
import i18n from '../i18n'
import { resetHouseholdScopedStores } from './householdScope'
import { assertSessionGeneration, currentSessionGeneration, invalidateSessionScope, ScopeChangedError, isScopeChanged } from '../services/sessionScope'

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
  /** Nur in nativen Apps gefüllt (Web: HttpOnly-Cookie) */
  refresh_token?: string | null
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
  const scopeKey = ref(0)

  // This watcher runs before any next render or promise continuation, including
  // direct membership-removal paths. Same-user JWT refresh does not change scope.
  watch(currentHouseholdId, () => {
    scopeKey.value++
    resetHouseholdScopedStores()
  }, { flush: 'sync' })

  // Cookie responses must finish in order: a late refresh/login must not install
  // its HttpOnly cookie after a later logout or login has already completed.
  let credentialQueue: Promise<unknown> = Promise.resolve()
  function credentialRequest<T>(request: () => Promise<T>): Promise<T> {
    const result = credentialQueue.then(request, request)
    credentialQueue = result.catch(() => {})
    return result
  }

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
    // Native App: Refresh-Token aus dem Geräte-Speicher (kein Cookie)
    const generation = currentSessionGeneration()
    const storedNativeToken = isNativeApp() ? await nativeRefreshToken.get() : null
    if (generation !== currentSessionGeneration()) {
      _registerStorageListener()
      isInitialized.value = true
      _authReadyResolve()
      return
    }
    if (legacyRefreshToken || storedNativeToken || sessionMarker.isSet()) {
      try {
        // Access-Token wird nie persistiert: Cookie oder nativen Refresh-Token verwenden.
        await _refreshWith(legacyRefreshToken)
        assertSessionGeneration(generation)
        await fetchMe()
      } catch (err: any) {
        if (isScopeChanged(err) || generation !== currentSessionGeneration()) {
          _registerStorageListener()
          isInitialized.value = true
          _authReadyResolve()
          return
        }
        if (isAuthRejection(err)) {
          // Cookie fehlt/abgelaufen/revoked (Backend hat ihn gelöscht) → ausgeloggt
          _clearState()
          sessionExpired.value = true
          await _unsubscribePushLocally()
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

    const pending = _doRefresh(legacyRefreshToken)
    _refreshPromise = pending
    try {
      await _refreshPromise
    } finally {
      if (_refreshPromise === pending) _refreshPromise = null
    }
  }

  async function _doRefresh(legacyRefreshToken: string | null): Promise<void> {
    if (_logoutPromise) throw new ScopeChangedError()
    const generation = currentSessionGeneration()
    const expectedSubject = token.value ? tokenSubject(token.value) : user.value?.id
    // Direkter axios call OHNE Interceptor (um Endlos-Loop zu vermeiden).
    // Web: Der Refresh-Token kommt aus dem HttpOnly-Cookie (withCredentials); nur bei der
    // einmaligen Migration steht der alte localStorage-Token im Body.
    await credentialRequest(async () => {
      const storedToken = legacyRefreshToken ?? (isNativeApp() ? await nativeRefreshToken.get() : null)
      assertSessionGeneration(generation)
      const body = storedToken ? { refresh_token: storedToken } : {}
      const response = await axios.post(`${API_BASE}/api/auth/refresh`, body, authRequestConfig())
      assertSessionGeneration(generation)
      const nextSubject = tokenSubject(response.data.access_token)
      if (expectedSubject && nextSubject !== expectedSubject) {
        // Another tab replaced the shared cookie. Never replay this principal's
        // in-flight mutations using that other principal's newly issued JWT.
        _clearState(false)
        void import('../router').then(({ default: router }) => router.replace('/login'))
        throw new ScopeChangedError()
      }
      await _installTokens(response.data, generation)
    })
  }

  function tokenSubject(value: string): string | undefined {
    try {
      const payload = value.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
      const subject = JSON.parse(atob(payload)).sub
      return typeof subject === 'string' ? subject : undefined
    } catch { return undefined }
  }

  /** Übernimmt den Access-Token einer Login-/Register-/Refresh-Antwort (Cookie setzt der Browser). */
  async function _installTokens(data: TokenPayload, generation: number) {
    assertSessionGeneration(generation)
    if (isNativeApp() && data.refresh_token) {
      await nativeRefreshToken.set(data.refresh_token)
      assertSessionGeneration(generation)
    }
    token.value = data.access_token
    hasOfflineSession.value = false
    sessionExpired.value = false
    sessionMarker.set()
  }

  function _applyTokens(data: TokenPayload) {
    const generation = currentSessionGeneration()
    return credentialRequest(() => _installTokens(data, generation))
  }

  /** Password changes rotate credentials too, so order them with refresh/login/logout. */
  async function changePassword(currentPassword: string, newPassword: string): Promise<TokenResponse> {
    const generation = currentSessionGeneration()
    if (!isAuthenticated.value || _logoutPromise) throw new ScopeChangedError()
    if (!token.value) {
      await refresh()
      assertSessionGeneration(generation)
    }
    const send = () => credentialRequest(async () => {
      assertSessionGeneration(generation)
      const { data } = await axios.put<TokenResponse>(
        `${API_BASE}/api/account/password`,
        { current_password: currentPassword, new_password: newPassword },
        authRequestConfig({ Authorization: `Bearer ${token.value}` }),
      )
      await _installTokens(data, generation)
      return data
    })
    try {
      return await send()
    } catch (error) {
      assertSessionGeneration(generation)
      if (!isAuthRejection(error)) throw error
      try {
        await refresh()
      } catch (refreshError) {
        assertSessionGeneration(generation)
        if (isAuthRejection(refreshError)) await logout({ reason: 'expired' })
        throw refreshError
      }
      assertSessionGeneration(generation)
      return send()
    }
  }

  function markEmailVerified() {
    if (user.value) user.value.email_verified = true
  }

  /**
   * Frisches Access-Token für den Socket, nachdem der Server ihn wegen Ablauf getrennt hat.
   * null, wenn ausgeloggt (oder Logout läuft) oder der Refresh nicht klappt; lehnt der
   * Server den Refresh-Token ab, wird wie beim API-Interceptor ausgeloggt.
   */
  async function refreshForSocket(): Promise<string | null> {
    if (_logoutPromise || !token.value) return null
    const generation = currentSessionGeneration()
    try {
      await refresh()
      assertSessionGeneration(generation)
      return token.value
    } catch (err: any) {
      if (generation === currentSessionGeneration() && isAuthRejection(err)) await logout({ reason: 'expired' })
      return null
    }
  }

  // ── Login ──

  async function login(email: string, password: string) {
    if (_logoutPromise) await _logoutPromise
    _clearState()
    const generation = currentSessionGeneration()
    await credentialRequest(async () => {
      assertSessionGeneration(generation)
      const response = await axios.post(
        `${API_BASE}/api/auth/login`,
        new URLSearchParams({ username: email, password }),
        authRequestConfig({ 'Content-Type': 'application/x-www-form-urlencoded' }),
      )
      await _installTokens(response.data, generation)
    })
    assertSessionGeneration(generation)

    await fetchMe()
  }

  // ── Register ──

  async function register(
    email: string,
    password: string,
    displayName: string,
    options: { householdName: string } | { inviteCode: string },
    acceptTerms = false,
  ) {
    if (_logoutPromise) await _logoutPromise
    _clearState()
    const generation = currentSessionGeneration()
    const payload: Record<string, string | boolean> = {
      email,
      password,
      display_name: displayName,
    }
    if ('householdName' in options) {
      payload.household_name = options.householdName
    } else {
      payload.invite_code = options.inviteCode
    }
    if (acceptTerms) payload.accept_terms = true
    await credentialRequest(async () => {
      assertSessionGeneration(generation)
      const response = await axios.post(`${API_BASE}/api/auth/register`, payload, authRequestConfig())
      await _installTokens(response.data, generation)
    })
    assertSessionGeneration(generation)

    await fetchMe()
  }

  // ── Fetch Me ──

  async function fetchMe() {
    const generation = currentSessionGeneration()
    const response = await api.get<MeResponse>('/api/auth/me')
    assertSessionGeneration(generation)
    const data = response.data
    if (user.value && user.value.id !== data.id) {
      _clearState(false)
      throw new ScopeChangedError()
    }
    user.value = {
      id: data.id,
      email: data.email,
      display_name: data.display_name,
      email_verified: data.email_verified === true,
      is_platform_admin: data.is_platform_admin === true,
    }
    households.value = data.households

    if (data.households.length > 0) {
      // Bestehendes Household beibehalten falls noch gültig
      const stillValid = data.households.some(h => h.id === currentHouseholdId.value)
      if (!stillValid) {
        currentHouseholdId.value = data.households[0].id
        localStorage.setItem(HOUSEHOLD_KEY, currentHouseholdId.value!)
      }
    } else {
      currentHouseholdId.value = null
      localStorage.removeItem(HOUSEHOLD_KEY)
    }
  }

  // ── Mitgliedschaft neu prüfen (CASA-49) ──

  let _revalidatePromise: Promise<void> | null = null

  /**
   * Lädt /me neu und behandelt den aktuellen Haushalt als verlassen, wenn er fehlt.
   * Aufgerufen nach einem Socket-Reconnect (Entfernung verpasst, solange offline), bei
   * 403 NOT_HOUSEHOLD_MEMBER auf den aktuellen Haushalt und beim entsprechenden
   * Socket-`error`. Single-Flight; Fehler (offline) werden verschluckt.
   */
  async function revalidateMembership(): Promise<void> {
    if (!token.value) return
    if (_revalidatePromise) return _revalidatePromise
    const generation = currentSessionGeneration()
    const pending = (async () => {
      const previousId = currentHouseholdId.value
      const previousName = households.value.find(h => h.id === previousId)?.name ?? ''
      try {
        await fetchMe()
      } catch {
        return // Offline/Serverfehler — der nächste Anlass prüft erneut
      }
      if (generation !== currentSessionGeneration() || !previousId || households.value.some(h => h.id === previousId)) return
      // Eigener Austritt läuft gerade → die View meldet und navigiert selbst
      if (_ownLeaves.has(previousId)) return
      _announceRemoval(previousName)
    })()
    _revalidatePromise = pending
    try {
      await _revalidatePromise
    } finally {
      if (_revalidatePromise === pending) _revalidatePromise = null
    }
  }

  /** Socket-`error` vom Server: nicht (mehr) Mitglied des Haushalts → wie 403 behandeln. */
  function handleSocketError(data: { code?: string; household_id?: string } | null | undefined) {
    if (data?.code !== 'NOT_HOUSEHOLD_MEMBER') return
    if (data.household_id && data.household_id !== currentHouseholdId.value) return
    void revalidateMembership()
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
    // Privacy boundary is synchronous; network cleanup must not retain private
    // notes, dialogs or pending optimistic rollback snapshots in the next login.
    _clearState(true, false)
    sessionExpired.value = reason === 'expired'

    // Socket zuerst trennen: Der Logout-Aufruf beendet serverseitig alle Verbindungen
    // des Users; diese hier soll darauf nicht mehr reagieren (kein Reconnect/Refresh).
    try {
      const { useSocket } = await import('../composables/useSocket')
      useSocket().disconnect()
    } catch {
      // Best-effort
    }

    // Unsubscribe the browser directly after clearing credentials. Do not let
    // cleanup acquire a later account's token through the API refresh interceptor.
    try {
      const { disablePush } = await import('../services/pushService')
      await disablePush({ notifyBackend: false })
    } catch {
      // Best-effort
    }

    // Best-effort: Backend revoked den Refresh-Token aus dem Cookie und löscht den Cookie.
    // Ob ein Cookie existiert, sieht JS nicht (HttpOnly) — der Endpunkt ist idempotent.
    // Native App: Token aus dem Geräte-Speicher im Body mitschicken.
    try {
      await credentialRequest(async () => {
        try {
          const storedToken = isNativeApp() ? await nativeRefreshToken.get() : null
          await axios.post(`${API_BASE}/api/auth/logout`, storedToken ? { refresh_token: storedToken } : {}, authRequestConfig())
        } finally {
          if (isNativeApp()) await nativeRefreshToken.clear()
        }
      })
    } catch {
      // Ignore — Logout ist best-effort
    }

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

  /**
   * Push-Subscription dieses Browsers abmelden, ohne das Backend zu fragen (kein gültiger
   * Access-Token mehr). Das Backend räumt den Endpoint beim nächsten Versand auf (410).
   */
  async function _unsubscribePushLocally() {
    try {
      const { disablePush } = await import('../services/pushService')
      await disablePush({ notifyBackend: false })
    } catch {
      // Best-effort
    }
  }

  // ── Internal: State synchron zurücksetzen, native Ablage geordnet leeren ──

  function _clearState(broadcast = true, clearNative = true) {
    scopeKey.value++
    invalidateSessionScope()
    _refreshPromise = null
    _revalidatePromise = null
    _ownLeaves.clear()
    resetHouseholdScopedStores()
    token.value = null
    hasOfflineSession.value = false
    user.value = null
    currentHouseholdId.value = null
    households.value = []
    // Löscht den Marker → storage-Event in anderen Tabs (Cross-Tab-Logout)
    if (broadcast) sessionMarker.clear()
    localStorage.removeItem(HOUSEHOLD_KEY)
    if (clearNative && isNativeApp()) {
      void credentialRequest(() => nativeRefreshToken.clear()).catch(() => {})
    }
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
        _clearState(false)
        void _unsubscribePushLocally()
        // Navigiere zu /login OHNE redirect und OHNE Backend-Logout-Call
        import('../router').then(({ default: router }) => {
          router.push('/login')
        })
      } else {
        _clearState(false)
        const generation = currentSessionGeneration()
        // Anderer Tab hat sich angemeldet → Sitzung über den gemeinsamen Cookie übernehmen
        refresh()
          .then(() => { assertSessionGeneration(generation); return fetchMe() })
          .catch(() => {
            // Best-effort — der nächste geschützte Request versucht es erneut
          })
      }
    })
  }

  // ── Socket-Event-Handler für Household-Events ──

  function handleHouseholdUpdated(data: { id: string; name: string; ai_enabled?: boolean; plan?: string }) {
    const h = households.value.find(h => h.id === data.id)
    if (!h) return
    h.name = data.name
    if (typeof data.ai_enabled === 'boolean') h.ai_enabled = data.ai_enabled
    if (typeof data.plan === 'string') h.plan = data.plan
  }

  function handleMemberJoined(_data: { household_id: string; user_id: string; display_name: string; role: string }) {
    // Kein State-Update nötig im auth store — HouseholdView refetcht Members
  }

  /** Payload von household_member_left/_removed; `released` = freigegebene Bereiche (PD-H1). */
  interface MemberDepartedPayload {
    household_id: string
    user_id: string
    released?: string[]
  }

  function handleMemberLeft(data: MemberDepartedPayload) {
    _handleRemoval(data.household_id, data.user_id, data.released)
  }

  function handleMemberRemoved(data: MemberDepartedPayload) {
    _handleRemoval(data.household_id, data.user_id, data.released)
  }

  // ── Haushalt verlassen ──

  /** Haushalte, die der User gerade selbst verlässt (Socket-Event ist dann keine „Entfernung“). */
  const _ownLeaves = new Map<string, { generation: number; confirmed: boolean }>()

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
    const generation = currentSessionGeneration()
    const operation = { generation, confirmed: false }
    _ownLeaves.set(householdId, operation)
    try {
      try {
        await request()
      } catch (error) {
        // The server can confirm our departure via the socket before DELETE
        // resolves. That household switch cancels the old HTTP scope; the
        // confirmed departure is still successful in this same login session.
        assertSessionGeneration(generation)
        if (!operation.confirmed || (error as { code?: string })?.code !== 'ERR_CANCELED') throw error
      }
      assertSessionGeneration(generation)
      _dropHousehold(householdId)
    } finally {
      if (_ownLeaves.get(householdId) === operation) _ownLeaves.delete(householdId)
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

  function _handleRemoval(householdId: string, userId: string, released?: string[]) {
    // Eigener Austritt läuft gerade → still entfernen, die View meldet und navigiert
    const ownLeave = _ownLeaves.get(householdId)
    if (userId === user.value?.id && ownLeave?.generation === currentSessionGeneration()) {
      ownLeave.confirmed = true
      _dropHousehold(householdId)
      return
    }
    // Jemand anderes ist gegangen: Verlässt der einzige Admin den Haushalt, befördert der
    // Server das dienstälteste Mitglied — vielleicht uns. Rollen kommen nur über /me,
    // deshalb neu laden statt bis zum nächsten Start mit alter Rolle weiterzuarbeiten.
    if (userId !== user.value?.id) {
      if (households.value.some(h => h.id === householdId)) {
        fetchMe().catch(() => {
          // Best-effort — der nächste Start lädt /me ohnehin
        })
      }
      // Der Server hat die offenen Zuständigkeiten der Person freigegeben (PD-H1):
      // betroffene Listen des aktuellen Haushalts neu laden
      if (householdId === currentHouseholdId.value) {
        import('../services/memberDeparture')
          .then(({ refetchAfterMemberDeparture }) => refetchAfterMemberDeparture(released))
          .catch(() => {
            // Best-effort — beim nächsten Reconnect/Öffnen wird ohnehin neu geladen
          })
      }
      return
    }
    // Betrifft es den EIGENEN User im AKTUELLEN Haushalt?
    if (householdId === currentHouseholdId.value) {
      const removedName = households.value.find(h => h.id === householdId)?.name ?? ''
      // Haushalt aus Liste entfernen
      households.value = households.value.filter(h => h.id !== householdId)
      if (households.value.length > 0) {
        // Auf ersten verbleibenden Haushalt wechseln
        switchHousehold(households.value[0].id)
      } else {
        currentHouseholdId.value = null
        localStorage.removeItem(HOUSEHOLD_KEY)
      }
      _announceRemoval(removedName)
    }
  }

  /** Toast + Navigation, nachdem der aktuelle Haushalt weggefallen ist (Liste schon aktualisiert). */
  function _announceRemoval(removedName: string) {
    const { showToast } = useToast()
    const { t } = i18n.global

    if (households.value.length > 0) {
      showToast(t('household.switchedTo', { name: households.value[0].name }), 'info')
    } else {
      // Kein Haushalt mehr → Zustand "kein Haushalt"
      showToast(t('household.youWereRemoved', { name: removedName }), 'info')
      // Navigation analog logout()
      import('../router').then(({ default: router }) => {
        router.replace('/no-household')
      })
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
    scopeKey,
    // Getters
    isAuthenticated,
    currentHousehold,
    // Actions
    initialize,
    login,
    register,
    changePassword,
    fetchMe,
    refresh,
    refreshForSocket,
    switchHousehold,
    leaveHousehold,
    revalidateMembership,
    logout,
    markEmailVerified,
    /** Neues Token-Paar übernehmen (z. B. nach Passwort-Änderung, die andere Geräte abmeldet). */
    applyTokenResponse: _applyTokens,
    // Socket-Event-Handler
    handleHouseholdUpdated,
    handleMemberJoined,
    handleMemberLeft,
    handleMemberRemoved,
    handleSocketError,
  }
})
