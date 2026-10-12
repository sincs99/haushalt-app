import { ref, watch, type Ref } from 'vue'
import type { WidgetTokenCreated, WidgetTokenStatus } from '../repositories/widgetRepository'

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
  buildScript: (token: string) => string,
  onError: (error: unknown) => void = () => {},
) {
  const status = ref<WidgetTokenStatus | null>(null)
  const script = ref<string | null>(null) // nur direkt nach dem Erzeugen bekannt
  const busy = ref(false)

  const stillCurrent = (id: string) => householdId.value === id

  async function load() {
    const id = householdId.value
    if (!id) return
    try {
      const result = await repo.fetchStatus(id)
      if (stillCurrent(id)) status.value = result
    } catch {
      if (stillCurrent(id)) status.value = null
    }
  }

  async function create(): Promise<boolean> {
    const id = householdId.value
    if (!id) return false
    busy.value = true
    try {
      const created = await repo.create(id)
      if (!stillCurrent(id)) return false
      script.value = buildScript(created.token)
      await load()
      return true
    } catch (error) {
      if (stillCurrent(id)) onError(error)
      return false
    } finally {
      busy.value = false
    }
  }

  async function revoke(): Promise<boolean> {
    const id = householdId.value
    if (!id) return false
    busy.value = true
    try {
      await repo.revoke(id)
      if (!stillCurrent(id)) return false
      script.value = null
      await load()
      return true
    } catch (error) {
      if (stillCurrent(id)) onError(error)
      return false
    } finally {
      busy.value = false
    }
  }

  // Haushaltswechsel: alten Zustand sofort verwerfen, neuen laden
  watch(householdId, () => {
    script.value = null
    status.value = null
    void load()
  })

  return { status, script, busy, load, create, revoke }
}
