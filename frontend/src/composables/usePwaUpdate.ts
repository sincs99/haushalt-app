import { readonly, ref } from 'vue'

/**
 * App-Update (CASA-41). Installierte PWAs (v. a. iOS) laufen oft tagelang ohne Neustart
 * und prüfen dann nie auf eine neue Version — das alte Frontend spricht weiter mit dem
 * neuen Backend. Deshalb:
 * - Update-Prüfung beim Zurückkehren in die App (visibilitychange) und stündlich,
 * - „Update verfügbar“ bleibt im Mehr-Sheet stehen, bis neu geladen wird
 *   (zusätzlich zum Toast, der nach einer Minute verschwindet).
 */

const updateAvailable = ref(false)
let applyUpdate: (() => Promise<void> | void) | null = null

export const UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000
// Häufiges Hin- und Herwechseln löst nicht jedes Mal einen Request aus
export const MIN_CHECK_GAP_MS = 60 * 1000

/** Neue Version liegt bereit; `apply` aktiviert sie und lädt neu. */
export function setUpdateAvailable(apply: () => Promise<void> | void): void {
  applyUpdate = apply
  updateAvailable.value = true
}

export function usePwaUpdate() {
  return {
    updateAvailable: readonly(updateAvailable),
    reloadForUpdate(): void {
      if (applyUpdate) void applyUpdate()
      else window.location.reload()
    },
  }
}

/**
 * Prüft regelmässig, ob der Server einen neuen Service Worker hat. Liefert eine
 * Funktion zum Beenden (Tests).
 */
export function watchForUpdates(registration: Pick<ServiceWorkerRegistration, 'update'>): () => void {
  let lastCheck = Date.now()

  function check() {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return
    if (Date.now() - lastCheck < MIN_CHECK_GAP_MS) return
    lastCheck = Date.now()
    registration.update().catch(() => {
      // Offline/Server nicht erreichbar — beim nächsten Mal wieder
    })
  }

  function onVisibilityChange() {
    if (document.visibilityState === 'visible') check()
  }

  const timer = setInterval(check, UPDATE_CHECK_INTERVAL_MS)
  document.addEventListener('visibilitychange', onVisibilityChange)
  return () => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
}
