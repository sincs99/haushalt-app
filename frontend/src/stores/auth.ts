import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import api from '../api/client'
import type { UserInfo, HouseholdInfo, MeResponse } from '../types'
import { tokenStorage, TOKEN_STORAGE_KEY } from '../services/tokenStorage'
import { useToast } from '../composables/useToast'
import i18n from '../i18n'

const HOUSEHOLD_KEY = 'haushalt_household_id'

/** True nur wenn der Server explizit 401 zurückgegeben hat (Auth-Rejection). */
function isAuthRejection(err: any): boolean {
  return err?.response?.status === 401
}

export const useAuthStore = defineStore('auth', () => {
  // State
  const token = ref<string | null>(null)
  const refreshToken = ref<string | null>(null)
  const user = ref<UserInfo | null>(null)
  const currentHouseholdId = ref<string | null>(null)
  const households = ref<HouseholdInfo[]>([])
  const isInitialized = ref(false)

  // Internes Promise-Setup für authReady
  let _authReadyResolve: () => void
  const authReady = new Promise<void>((resolve) => {
    _authReadyResolve = resolve
  })

  // Getters
  const isAuthenticated = computed(() => !!token.value)

  const currentHousehold = computed<HouseholdInfo | null>(() => {
    if (!currentHouseholdId.value || households.value.length === 0) return null
    return households.value.find(h => h.id === currentHouseholdId.value) ?? null
  })

  // ── Actions ──

  async function initialize() {
    if (isInitialized.value) return

    const saved = await tokenStorage.get()
    if (!saved) {
      isInitialized.value = true
      _authReadyResolve()
      return
    }

    // Tokens aus Storage wiederherstellen
    token.value = saved.accessToken
    refreshToken.value = saved.refreshToken

    // HouseholdId aus localStorage wiederherstellen
    const savedHouseholdId = localStorage.getItem(HOUSEHOLD_KEY)
    if (savedHouseholdId) {
      currentHouseholdId.value = savedHouseholdId
    }

    try {
      await fetchMe()
    } catch (err: any) {
      if (isAuthRejection(err)) {
        // Access-Token abgelaufen → Refresh versuchen
        try {
          await refresh()
          await fetchMe()
        } catch (refreshErr: any) {
          if (isAuthRejection(refreshErr)) {
            // Auth definitiv abgelehnt → ausloggen
            await _clearState()
          }
          // Netzwerkfehler bei Refresh → Tokens behalten, User "offline-eingeloggt"
        }
      }
      // Netzwerkfehler bei fetchMe → Tokens behalten!
      // user/households bleiben null, aber isAuthenticated bleibt true
    }

    // Cross-Tab storage event Listener registrieren
    _registerStorageListener()

    isInitialized.value = true
    _authReadyResolve()
  }

  // ── Refresh — Single-Flight ──

  let _refreshPromise: Promise<void> | null = null

  async function refresh(): Promise<void> {
    // Single-flight: concurrent callers teilen sich dasselbe Promise
    if (_refreshPromise) return _refreshPromise

    _refreshPromise = _doRefresh()
    try {
      await _refreshPromise
    } finally {
      _refreshPromise = null
    }
  }

  async function _doRefresh(): Promise<void> {
    // Immer den AKTUELLSTEN Token aus Storage lesen (anderer Tab könnte rotiert haben)
    const current = await tokenStorage.get()
    const rtToUse = current?.refreshToken ?? refreshToken.value
    if (!rtToUse) throw new Error('No refresh token')

    // Direkter axios call OHNE Interceptor (um Endlos-Loop zu vermeiden)
    const response = await axios.post(
      `${import.meta.env.VITE_API_URL}/api/auth/refresh`,
      { refresh_token: rtToUse },
    )

    const data = response.data
    token.value = data.access_token
    refreshToken.value = data.refresh_token

    await tokenStorage.set({
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      accessExpiresAt: Date.now() + data.expires_in * 1000,
    })
  }

  // ── Login ──

  async function login(email: string, password: string) {
    const response = await api.post(
      '/api/auth/login',
      new URLSearchParams({ username: email, password }),
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } },
    )
    const data = response.data
    token.value = data.access_token
    refreshToken.value = data.refresh_token

    await tokenStorage.set({
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      accessExpiresAt: Date.now() + data.expires_in * 1000,
    })

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
    const response = await api.post('/api/auth/register', payload)
    const data = response.data
    token.value = data.access_token
    refreshToken.value = data.refresh_token

    await tokenStorage.set({
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      accessExpiresAt: Date.now() + data.expires_in * 1000,
    })

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

    // Best-effort: Backend benachrichtigen
    if (refreshToken.value) {
      try {
        await axios.post(
          `${import.meta.env.VITE_API_URL}/api/auth/logout`,
          { refresh_token: refreshToken.value },
        )
      } catch {
        // Ignore — Logout ist best-effort
      }
    }

    await _clearState()

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
    refreshToken.value = null
    user.value = null
    currentHouseholdId.value = null
    households.value = []
    await tokenStorage.clear()
    localStorage.removeItem(HOUSEHOLD_KEY)
  }

  // ── Cross-Tab Storage Listener ──

  function _registerStorageListener() {
    window.addEventListener('storage', (event) => {
      if (event.key !== TOKEN_STORAGE_KEY) return

      if (event.newValue === null) {
        // Anderer Tab hat Tokens gelöscht (Logout)
        token.value = null
        refreshToken.value = null
        user.value = null
        currentHouseholdId.value = null
        households.value = []
        localStorage.removeItem(HOUSEHOLD_KEY)
        // Navigiere zu /login OHNE redirect und OHNE Backend-Logout-Call
        import('../router').then(({ default: router }) => {
          router.push('/login')
        })
      } else {
        // Anderer Tab hat Tokens aktualisiert (Refresh)
        try {
          const parsed = JSON.parse(event.newValue)
          if (parsed.accessToken && parsed.refreshToken) {
            token.value = parsed.accessToken
            refreshToken.value = parsed.refreshToken
          }
        } catch {
          // Ignore parse errors
        }
      }
    })
  }

  // ── Socket-Event-Handler für Household-Events ──

  function handleHouseholdUpdated(data: { id: string; name: string }) {
    const h = households.value.find(h => h.id === data.id)
    if (h) h.name = data.name
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

  function _handleRemoval(householdId: string, userId: string) {
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
    refreshToken,
    user,
    currentHouseholdId,
    households,
    isInitialized,
    authReady,
    // Getters
    isAuthenticated,
    currentHousehold,
    // Actions
    initialize,
    login,
    register,
    fetchMe,
    refresh,
    switchHousehold,
    logout,
    // Socket-Event-Handler
    handleHouseholdUpdated,
    handleMemberJoined,
    handleMemberLeft,
    handleMemberRemoved,
  }
})
