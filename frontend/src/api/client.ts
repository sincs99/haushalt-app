import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
})

// Request-Interceptor: JWT aus Auth-Store als Bearer-Token
// Lazy dynamic import, damit Pinia-Initialisierung nicht blockiert wird
api.interceptors.request.use(async (config) => {
  const { useAuthStore } = await import('../stores/auth')
  const authStore = useAuthStore()
  if (authStore.token) {
    config.headers.Authorization = `Bearer ${authStore.token}`
  }
  return config
})

// Response-Interceptor: Bei 401 → Auth-Store leeren, auf /login redirecten
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      const { useAuthStore } = await import('../stores/auth')
      const authStore = useAuthStore()
      authStore.token = null
      authStore.user = null
      authStore.currentHouseholdId = null

      const { default: router } = await import('../router')
      router.push('/login')
    }
    return Promise.reject(error)
  }
)

export default api
