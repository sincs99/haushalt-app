import { ref } from 'vue'

/**
 * Lade-Zustand einer Ansicht: merkt sich, ob das Laden gescheitert ist, und
 * bietet `reload` für den „Erneut versuchen“-Button (BaseErrorState).
 *
 * `load` darf mehrere Requests bündeln; scheitert einer, gilt das Laden als gescheitert.
 */
export function useLoader(load: () => Promise<unknown>) {
  const loadError = ref(false)
  const reloading = ref(false)

  async function reload() {
    if (reloading.value) return
    reloading.value = true
    try {
      await load()
      loadError.value = false
    } catch {
      loadError.value = true
    } finally {
      reloading.value = false
    }
  }

  return { loadError, reloading, reload }
}
