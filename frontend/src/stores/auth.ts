import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
import api from '../api/client'
import type { UserInfo, HouseholdInfo, MeResponse } from '../types'
import { tokenStorage } from '../services/tokenStorage'
import { useToast } from '../composables/useToast'
import i18n from '../i18n'

const HOUSEHOLD_KEY = 'haushalt_household_id'

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
    // Nur einmal ausführen
    if (isInitialized.value) return

    const saved = tokenStorage.get()
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
      // Access-Token abgelaufen? → Refresh versuchen
      if (err?.response?.status === 401) {
        try {
          await refresh()
          await fetchMe()
        } catch {
          // Refresh auch fehlgeschlagen → sauber ausloggen
          _clearState()
        }
      } else {
        _clearState()
      }
    }

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
    if (!refreshToken.value) throw new Error('No refresh token')

    // Direkter axios call OHNE Interceptor (um Endlos-Loop zu vermeiden)
    const response = await axios.post(
      `${import.meta.env.VITE_API_URL}/api/auth/refresh`,
      { refresh_token: refreshToken.value },
    )

    const data = response.data
    token.value = data.access_token
    refreshToken.value = data.refresh_token

    tokenStorage.set({
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

    tokenStorage.set({
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

    tokenStorage.set({
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

  // ── Logout ──

  async function logout() {
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

    _clearState()

    const { default: router } = await import('../router')
    const currentPath = router.currentRoute.value.fullPath
    // Nur redirect-Parameter setzen wenn nicht bereits auf /login oder /register
    if (currentPath && currentPath !== '/login' && currentPath !== '/register') {
      router.push({ path: '/login', query: { redirect: currentPath } })
    } else {
      router.push('/login')
    }
  }

  // ── Internal: State zurücksetzen ──

  function _clearState() {
    token.value = null
    refreshToken.value = null
    user.value = null
    currentHouseholdId.value = null
    households.value = []
    tokenStorage.clear()
    localStorage.removeItem(HOUSEHOLD_KEY)
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
