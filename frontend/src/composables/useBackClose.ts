import { ref, watch, nextTick, onBeforeUnmount, toValue, type Ref } from 'vue'

/**
 * Schliesst einen Dialog / ein Bottom-Sheet mit der Zurück-Taste (Android, Browser),
 * statt die Seite zu verlassen.
 *
 * Beim Öffnen wird ein History-Eintrag mit gleicher URL und `overlayDepth` angelegt
 * (der vue-router-State bleibt erhalten). Zurück entfernt ihn → `close()`.
 * Wird das Overlay per Button geschlossen, wird der eigene Eintrag wieder entfernt.
 *
 * Die dabei entstehenden popstate-Events sieht der Router nicht: URL und
 * Router-State sind danach identisch mit vorher, eine Router-Navigation wäre
 * überflüssig und würde eine gleichzeitig laufende router.push() abbrechen.
 * Dafür muss unser Listener VOR dem des Routers registriert sein (am Window gilt
 * die Registrierungsreihenfolge) – deshalb ein einziger Listener beim Laden dieses
 * Moduls, das `router/index.ts` vor `createRouter()` importiert.
 */
const openOverlays = ref(0)
let pendingBack: Promise<void> | null = null
let finishPendingBack: (() => void) | null = null

interface OverlayEntry {
  depth: number
  onBack: () => void
}
const overlays: OverlayEntry[] = []

function onPopState(event: PopStateEvent) {
  // Eigenes history.back() eines per Button geschlossenen Overlays
  if (finishPendingBack) {
    event.stopImmediatePropagation()
    finishPendingBack()
    return
  }
  const depth = (event.state?.overlayDepth as number | undefined) ?? 0
  const affected = overlays.filter((o) => o.depth > depth).sort((a, b) => b.depth - a.depth)
  if (affected.length === 0) return
  // Nur der Overlay-Eintrag wurde entfernt, die Seite bleibt → Router nicht stören
  if (affected.length === 1 && depth === affected[0].depth - 1) event.stopImmediatePropagation()
  for (const overlay of affected) overlay.onBack()
}

if (typeof window !== 'undefined') {
  window.addEventListener('popstate', onPopState)
}

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
    const timer = setTimeout(() => finishPendingBack?.(), 500) // falls kein popstate kommt
    finishPendingBack = () => {
      clearTimeout(timer)
      finishPendingBack = null
      pendingBack = null
      resolve()
    }
  })
  window.history.back()
}

export function useBackClose(isOpen: Ref<boolean> | (() => boolean), close: () => void) {
  let entry: OverlayEntry | null = null

  function onBack() {
    if (!entry) return
    const previousDepth = entry.depth
    release()
    close()
    reacquireIfStillOpen(previousDepth)
  }

  /**
   * Hat die Ansicht das Schliessen abgefangen (z. B. Rückfrage „Änderungen verwerfen?“),
   * bleibt das Overlay offen und braucht wieder einen eigenen Eintrag – aber erst,
   * wenn ein dabei geöffneter Rückfrage-Dialog wieder zu ist, sonst stimmt die
   * Reihenfolge der Einträge nicht.
   */
  function reacquireIfStillOpen(previousDepth: number) {
    const reacquire = () => waitForOverlayBack().then(() => {
      if (toValue(isOpen)) acquire()
    })
    // Erst nach dem Re-Render prüfen: dann ist `open` aktuell und ein
    // Rückfrage-Dialog hat seinen Eintrag schon angelegt.
    nextTick(() => {
      if (!toValue(isOpen)) return
      if (openOverlays.value < previousDepth) {
        reacquire()
        return
      }
      const stop = watch([openOverlays, () => toValue(isOpen)], ([count, open]) => {
        if (!open) {
          stop()
        } else if (count < previousDepth) {
          stop()
          reacquire()
        }
      }, { flush: 'post' })
    })
  }

  function acquire() {
    if (typeof window === 'undefined' || entry) return
    openOverlays.value += 1
    const current: OverlayEntry = { depth: openOverlays.value, onBack }
    entry = current
    const push = () => {
      if (entry !== current) return // inzwischen wieder geschlossen
      window.history.pushState({ ...(window.history.state ?? {}), overlayDepth: current.depth }, '')
      overlays.push(current)
    }
    // Läuft noch das history.back() eines eben geschlossenen Overlays, würde es
    // den neuen Eintrag gleich wieder entfernen → erst danach anlegen.
    if (pendingBack) pendingBack.then(push)
    else push()
  }

  function release() {
    if (!entry) return
    const idx = overlays.indexOf(entry)
    if (idx !== -1) overlays.splice(idx, 1)
    openOverlays.value = Math.max(0, openOverlays.value - 1)
    entry = null
  }

  function closedByUi() {
    if (!entry) return
    const ownEntryOnTop = overlays.includes(entry) && window.history.state?.overlayDepth === entry.depth
    release()
    if (ownEntryOnTop) overlayBack()
  }

  watch(isOpen, (open) => (open ? acquire() : closedByUi()), { immediate: true })
  onBeforeUnmount(closedByUi)
}
