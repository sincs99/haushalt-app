import { ref, watch, type Ref } from 'vue'
import type { WidgetTokenCreated, WidgetTokenStatus } from '../repositories/widgetRepository'
import { currentDataGeneration } from '../services/sessionScope'

interface WidgetRepo {
  fetchStatus(householdId: string): Promise<WidgetTokenStatus>
  create(householdId: string): Promise<WidgetTokenCreated>
  revoke(householdId: string): Promise<void>
}

/**
 * Zustand der Widget-Karte, an den aktuellen Haushalt gebunden (CASA-50).
 *
 * Jede Anfrage merkt sich den Haushalt, für den sie gestartet wurde. Wechselt der
 * Haushalt, bevor die Antwort da ist, wird sie verworfen — sonst stünde der Schlüssel
 * (oder das Skript mit Klartext-Schlüssel) von Haushalt A in der Ansicht von B.
 * `onError` bekommt Fehler nur, solange der Haushalt noch derselbe ist.
 */
export function useWidgetToken(
  householdId: Readonly<Ref<string | null>>,
  repo: WidgetRepo,
  buildScript: (token: string) => string | Promise<string>,
  onError: (error: unknown) => void = () => {},
) {
  const status = ref<WidgetTokenStatus | null>(null)
  const script = ref<string | null>(null) // nur direkt nach dem Erzeugen bekannt
  const busy = ref(false)

  let revision = 0
  function capture(id: string) {
    const generation = currentDataGeneration()
    const version = revision
    return () => householdId.value === id && version === revision && generation === currentDataGeneration()
  }

  async function load() {
    const id = householdId.value
    if (!id) return
    const active = capture(id)
    try {
      const result = await repo.fetchStatus(id)
      if (active()) status.value = result
    } catch {
      if (active()) status.value = null
    }
  }

  async function create(): Promise<boolean> {
    const id = householdId.value
    if (!id) return false
    const active = capture(id)
    busy.value = true
    try {
      const created = await repo.create(id)
      if (!active()) return false
      const generated = await buildScript(created.token)
      if (!active()) return false
      script.value = generated
      await load()
      return active()
    } catch (error) {
      if (active()) onError(error)
      return false
    } finally {
      if (active()) busy.value = false
    }
  }

  async function revoke(): Promise<boolean> {
    const id = householdId.value
    if (!id) return false
    const active = capture(id)
    busy.value = true
    try {
      await repo.revoke(id)
      if (!active()) return false
      script.value = null
      await load()
      return active()
    } catch (error) {
      if (active()) onError(error)
      return false
    } finally {
      if (active()) busy.value = false
    }
  }

  // Haushaltswechsel: alten Zustand sofort verwerfen, neuen laden
  watch(householdId, () => {
    revision++
    busy.value = false
    script.value = null
    status.value = null
    void load()
  }, { flush: 'sync' })

  return { status, script, busy, load, create, revoke }
}
