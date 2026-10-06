import { watch, onBeforeUnmount, type Ref } from 'vue'

/**
 * Schliesst einen Dialog / ein Bottom-Sheet mit der Zurück-Taste (Android, Browser),
 * statt die Seite zu verlassen.
 *
 * Beim Öffnen wird ein History-Eintrag mit gleicher URL und `overlayDepth` angelegt
 * (der vue-router-State bleibt erhalten). Zurück entfernt ihn → `close()`.
 * Wird das Overlay per Button geschlossen, wird der eigene Eintrag wieder entfernt.
 *
 * Die dabei entstehenden popstate-Events sieht der Router nicht (Listener in der
 * Capture-Phase, stopImmediatePropagation): URL und Router-State sind danach
 * identisch mit vorher, eine Router-Navigation wäre überflüssig und könnte eine
 * gleichzeitig laufende router.push() abbrechen.
 */
let openOverlays = 0
let pendingBack: Promise<void> | null = null

/**
 * Für einen Router-Guard: wartet, bis ein laufendes history.back() eines
 * geschlossenen Overlays fertig ist. Sonst nähme „Dialog schliessen, dann
 * router.push()“ den neuen Eintrag gleich wieder zurück.
 */
export function waitForOverlayBack(): Promise<void> {
  return pendingBack ?? Promise.resolve()
}

function overlayBack() {
  pendingBack = new Promise<void>((resolve) => {
    const finish = (event?: Event) => {
      // Das popstate gehört dem Overlay, nicht dem Router
      event?.stopImmediatePropagation()
      window.removeEventListener('popstate', finish, true)
      clearTimeout(timer)
      pendingBack = null
      resolve()
    }
    window.addEventListener('popstate', finish, true)
    // Sicherheitsnetz, falls der Browser kein popstate liefert
    const timer = setTimeout(() => finish(), 500)
  })
  window.history.back()
}

export function useBackClose(isOpen: Ref<boolean> | (() => boolean), close: () => void) {
  let myDepth = 0

  function onPopState(event: PopStateEvent) {
    if (pendingBack) return // eigenes back() eines anderen Overlays
    const depth = (event.state?.overlayDepth as number | undefined) ?? 0
    if (myDepth && depth < myDepth) {
      if (depth === myDepth - 1) event.stopImmediatePropagation()
      release()
      close()
    }
  }

  function acquire() {
    if (typeof window === 'undefined' || myDepth) return
    openOverlays += 1
    myDepth = openOverlays
    window.history.pushState({ ...(window.history.state ?? {}), overlayDepth: myDepth }, '')
    window.addEventListener('popstate', onPopState, true)
  }

  function release() {
    if (!myDepth) return
    window.removeEventListener('popstate', onPopState, true)
    openOverlays = Math.max(0, openOverlays - 1)
    myDepth = 0
  }

  function closedByUi() {
    if (!myDepth) return
    const ownEntryOnTop = window.history.state?.overlayDepth === myDepth
    release()
    if (ownEntryOnTop) overlayBack()
  }

  watch(isOpen, (open) => (open ? acquire() : closedByUi()), { immediate: true })
  onBeforeUnmount(closedByUi)
}
