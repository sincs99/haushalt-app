import { ref, readonly } from 'vue'
import i18n from '../i18n'
import { translateApiError } from '../utils/apiErrors'

export interface ToastAction {
  label: string
  onAction: () => void
}

export interface ToastMessage {
  id: number
  text: string
  type: 'error' | 'success' | 'info'
  action?: ToastAction
}

/** Anzeigedauer: normale Toasts 4 s, Toasts mit Aktion (z. B. Rückgängig) 6 s. */
export const TOAST_DURATION = 4000
export const TOAST_ACTION_DURATION = 6000
/** Höchstens so viele Toasts gleichzeitig; ältere fallen raus. */
const MAX_TOASTS = 3

const toasts = ref<ToastMessage[]>([])
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let nextId = 0

function showToast(
  text: string,
  type: ToastMessage['type'] = 'error',
  duration?: number,
  action?: ToastAction,
) {
  const id = nextId++
  const effectiveDuration = duration ?? (action ? TOAST_ACTION_DURATION : TOAST_DURATION)
  // Dieselbe Meldung nicht stapeln (z. B. mehrfach „Gegossen“ hintereinander)
  for (const existing of toasts.value.filter((t) => t.text === text && t.type === type && !t.action)) {
    dismissToast(existing.id)
  }
  toasts.value.push({ id, text, type, action })
  while (toasts.value.length > MAX_TOASTS) {
    dismissToast(toasts.value[0].id)
  }
  timers.set(id, setTimeout(() => dismissToast(id), effectiveDuration))

  // Rückgabe einer dismiss-Funktion (optional nutzbar)
  return () => dismissToast(id)
}

function dismissToast(id: number) {
  const timer = timers.get(id)
  if (timer) {
    clearTimeout(timer)
    timers.delete(id)
  }
  toasts.value = toasts.value.filter((t) => t.id !== id)
}

/** Kurze Erfolgsmeldung für Aktionen, deren Ergebnis nicht direkt sichtbar ist. */
function notifySuccess(text: string) {
  return showToast(text, 'success')
}

/** Neutraler Hinweis (z. B. „Du bist offline“). */
function notifyInfo(text: string) {
  return showToast(text, 'info')
}

/**
 * Fehlermeldung. Mit `error` wird der API-Fehlercode übersetzt (errors.<CODE>);
 * gibt es dafür keine Übersetzung, gilt `fallback`.
 */
function notifyError(fallback: string, error?: unknown) {
  return showToast(errorText(fallback, error), 'error')
}

/**
 * Nutzertext für einen Fehler: offline → Offline-Hinweis, bekannter API-Code →
 * errors.<CODE>, Netzwerkfehler → errors.network, sonst `fallback`.
 */
export function errorText(fallback: string, error?: unknown): string {
  const t = i18n.global.t
  if (error === undefined) return fallback
  if (typeof navigator !== 'undefined' && navigator.onLine === false) return t('offline.actionBlocked')
  const err = error as any
  const code = err?.response?.data?.detail?.code
  if (typeof code === 'string' && i18n.global.te(`errors.${code}`)) return t(`errors.${code}`)
  if (!err?.response && err?.message === 'Network Error') return translateApiError(err)
  return fallback
}

export interface UndoOptions {
  /** Beschriftung des Buttons, Standard: „Rückgängig“ */
  undoLabel?: string
  /** Meldung, falls das Rückgängigmachen scheitert */
  undoErrorText?: string
  /** Meldung nach erfolgreichem Rückgängigmachen (Standard: keine) */
  undoneText?: string
}

/**
 * Erfolgsmeldung mit „Rückgängig“-Button (6 s). Für Löschen, Abhaken, Erledigen
 * und andere Aktionen, die leicht versehentlich passieren.
 *
 * `undo` darf asynchron sein; scheitert es, erscheint eine Fehlermeldung.
 * Ein zweiter Klick auf denselben Toast löst das Undo nicht doppelt aus.
 */
function notifyUndoable(
  text: string,
  undo: () => unknown | Promise<unknown>,
  options: UndoOptions = {},
) {
  const t = i18n.global.t
  let used = false
  return showToast(text, 'success', undefined, {
    label: options.undoLabel ?? t('common.undo'),
    onAction: () => {
      if (used) return
      used = true
      Promise.resolve()
        .then(() => undo())
        .then(() => {
          if (options.undoneText) showToast(options.undoneText, 'info')
        })
        .catch((err) => {
          notifyError(options.undoErrorText ?? t('common.undoError'), err)
        })
    },
  })
}

export function useToast() {
  return {
    toasts: readonly(toasts),
    showToast,
    dismissToast,
    notifySuccess,
    notifyInfo,
    notifyError,
    notifyUndoable,
  }
}
