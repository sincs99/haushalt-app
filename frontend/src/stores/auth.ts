import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api/client'
import type { UserInfo, HouseholdInfo, MeResponse } from '../types'

const STORAGE_KEY = 'haushalt_token'
const HOUSEHOLD_KEY = 'haushalt_household_id'

export const useAuthStore = defineStore('auth', () => {
  // State
  const token = ref<string | null>(null)
  const user = ref<UserInfo | null>(null)
  const currentHouseholdId = ref<string | null>(null)
  const households = ref<HouseholdInfo[]>([])

  // Init: Token aus localStorage wiederherstellen
  const savedToken = localStorage.getItem(STORAGE_KEY)
  if (savedToken) {
    token.value = savedToken
    fetchMe().catch(() => {
      // Token expired oder ungültig → sauber ausloggen
      token.value = null
      localStorage.removeItem(STORAGE_KEY)
    })
  }

  // Init: HouseholdId aus localStorage wiederherstellen
  const savedHouseholdId = localStorage.getItem(HOUSEHOLD_KEY)
  if (savedHouseholdId) {
    currentHouseholdId.value = savedHouseholdId
  }

  // Getters
  const isAuthenticated = computed(() => !!token.value)

  const currentHousehold = computed<HouseholdInfo | null>(() => {
    if (!currentHouseholdId.value || households.value.length === 0) return null
    return households.value.find(h => h.id === currentHouseholdId.value) ?? null
  })

  // Actions
  async function login(email: string, password: string) {
    const response = await api.post(
      '/api/auth/login',
      new URLSearchParams({ username: email, password }),
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
    )
    token.value = response.data.access_token
    localStorage.setItem(STORAGE_KEY, token.value!)
    await fetchMe()
  }

  async function register(
    email: string,
    password: string,
    displayName: string,
    householdName: string
  ) {
    const response = await api.post('/api/auth/register', {
      email,
      password,
      display_name: displayName,
      household_name: householdName,
    })
    token.value = response.data.access_token
    localStorage.setItem(STORAGE_KEY, token.value!)
    await fetchMe()
  }

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

  function switchHousehold(householdId: string) {
    currentHouseholdId.value = householdId
    localStorage.setItem(HOUSEHOLD_KEY, householdId)
  }

  async function logout() {
    token.value = null
    user.value = null
    currentHouseholdId.value = null
    households.value = []
    localStorage.removeItem(STORAGE_KEY)
    localStorage.removeItem(HOUSEHOLD_KEY)
    const { default: router } = await import('../router')
    router.push('/login')
  }

  // Socket-Event-Handler für Household-Events
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
      // Haushalt aus Liste entfernen
      households.value = households.value.filter(h => h.id !== householdId)
      if (households.value.length > 0) {
        // Auf ersten verbleibenden Haushalt wechseln
        switchHousehold(households.value[0].id)
      } else {
        // Kein Haushalt mehr → Zustand "kein Haushalt"
        currentHouseholdId.value = null
        localStorage.removeItem(HOUSEHOLD_KEY)
      }
    }
  }

  return {
    // State
    token,
    user,
    currentHouseholdId,
    households,
    // Getters
    isAuthenticated,
    currentHousehold,
    // Actions
    login,
    register,
    fetchMe,
    switchHousehold,
    logout,
    // Socket-Event-Handler
    handleHouseholdUpdated,
    handleMemberJoined,
    handleMemberLeft,
    handleMemberRemoved,
  }
})
