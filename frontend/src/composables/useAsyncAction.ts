import { ref } from 'vue'
import i18n from '../i18n'
import { useToast } from './useToast'

export interface AsyncActionOptions<T> {
  /** Schlüssel für den Doppelklick-Schutz, z. B. die ID des Eintrags. Standard: ein gemeinsamer Schlüssel. */
  key?: string
  /** Erfolgsmeldung (Text oder Funktion des Ergebnisses). Leer = keine Meldung. */
  success?: string | ((result: T) => string | undefined)
  /** Mit `undo` wird die Erfolgsmeldung zum Toast mit „Rückgängig“. */
  undo?: (result: T) => unknown | Promise<unknown>
  /**
   * Fehlermeldung, falls der API-Fehlercode keine eigene Übersetzung hat.
   * Als Funktion bestimmt sie den Text selbst aus dem Fehler (z. B. Upload-Gründe).
   */
  error?: string | ((err: unknown) => string)
  /** Ohne Netz gar nicht erst senden, sondern einen Hinweis zeigen. Standard: true */
  requireOnline?: boolean
}

const DEFAULT_KEY = '__default__'

/**
 * Einheitliches Muster für Aktionen, die einen Request auslösen:
 * - Doppelklick-Schutz pro Schlüssel (`isPending(key)` für `:loading`/`:disabled`)
 * - ohne Netz: Hinweis statt fehlschlagendem Request
 * - Erfolg: kurzer Toast, optional mit „Rückgängig“
 * - Fehler: übersetzter Fehlercode oder `error`-Text
 *
 * `run` gibt `true` zurück, wenn die Aktion geklappt hat (z. B. um einen Dialog zu schliessen).
 */
export function useAsyncAction() {
  const { notifySuccess, notifyError, notifyInfo, notifyUndoable } = useToast()
  const pending = ref<Set<string>>(new Set())

  function isPending(key: string = DEFAULT_KEY) {
    return pending.value.has(key)
  }

  const anyPending = () => pending.value.size > 0

  async function run<T>(fn: () => Promise<T>, options: AsyncActionOptions<T> = {}): Promise<boolean> {
    const key = options.key ?? DEFAULT_KEY
    if (pending.value.has(key)) return false
    const t = i18n.global.t
    if ((options.requireOnline ?? true) && typeof navigator !== 'undefined' && navigator.onLine === false) {
      notifyInfo(t('offline.actionBlocked'))
      return false
    }
    pending.value = new Set(pending.value).add(key)
    try {
      const result = await fn()
      const text = typeof options.success === 'function' ? options.success(result) : options.success
      if (text) {
        if (options.undo) {
          const undo = options.undo
          notifyUndoable(text, () => undo(result))
        } else {
          notifySuccess(text)
        }
      }
      return true
    } catch (err) {
      if (typeof options.error === 'function') notifyError(options.error(err))
      else notifyError(options.error ?? t('errors.unknown'), err)
      return false
    } finally {
      const next = new Set(pending.value)
      next.delete(key)
      pending.value = next
    }
  }

  return { run, isPending, anyPending }
}
