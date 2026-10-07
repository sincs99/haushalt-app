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
  let pending: Promise<void> | null = null
  let requested = false

  function reload(): Promise<void> {
    requested = true
    if (pending) return pending
    reloading.value = true
    pending = Promise.resolve().then(drain)
    return pending
  }

  async function drain() {
    try {
      while (requested) {
        requested = false
        try {
          await load()
          loadError.value = false
        } catch {
          loadError.value = true
        }
      }
    } finally {
      requested = false
      pending = null
      reloading.value = false
    }
  }

  return { loadError, reloading, reload }
}
