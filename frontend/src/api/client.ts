import axios from 'axios'

export const API_BASE = import.meta.env.VITE_API_URL || ''

const api = axios.create({
  baseURL: API_BASE,
})

// URLs die NICHT refresht werden sollen (kein Retry bei 401)
const AUTH_URLS = ['/api/auth/login', '/api/auth/refresh', '/api/auth/logout']

// Request-Interceptor: JWT als Bearer-Token
api.interceptors.request.use(async (config) => {
  const { useAuthStore } = await import('../stores/auth')
  const authStore = useAuthStore()
  if (authStore.token) {
    config.headers.Authorization = `Bearer ${authStore.token}`
  }
  return config
})

// Response-Interceptor: Bei 401 → Refresh + Retry
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Nur bei 401, nicht bei auth-URLs, und nur einmal retrien
    if (
      error.response?.status === 401 &&
      !AUTH_URLS.some(url => originalRequest.url?.includes(url)) &&
      !originalRequest._retried
    ) {
      originalRequest._retried = true

      try {
        const { useAuthStore } = await import('../stores/auth')
        const authStore = useAuthStore()
        await authStore.refresh()

        // Original-Request mit neuem Token wiederholen
        originalRequest.headers.Authorization = `Bearer ${authStore.token}`
        return api(originalRequest)
      } catch (refreshErr: any) {
        // Refresh fehlgeschlagen → Logout NUR bei Auth-Rejection
        if (refreshErr?.response?.status === 401) {
          const { useAuthStore } = await import('../stores/auth')
          const authStore = useAuthStore()
          await authStore.logout({ reason: 'expired' })
        }
        // Bei Netzwerkfehler: KEIN Logout, Error durchreichen
      }
    }

    // 403 wird NICHT als Auth-Fehler behandelt — durchreichen!
    return Promise.reject(error)
  },
)

export default api
