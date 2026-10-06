/**
 * Unit-Tests für das einheitliche Feedback-Muster (Toast-Helper und useAsyncAction):
 * Erfolg, Fehlercodes, Undo, Doppelklick-Schutz, Offline-Sperre.
 */
import type {} from 'vitest'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import i18n from '../../i18n'
import { useToast, errorText, TOAST_ACTION_DURATION } from '../useToast'
import { useAsyncAction } from '../useAsyncAction'

const t = i18n.global.t

function setOnline(value: boolean) {
  Object.defineProperty(globalThis, 'navigator', {
    value: { onLine: value, language: 'de' },
    configurable: true,
    writable: true,
  })
}

function apiError(code: string) {
  return { response: { status: 422, data: { detail: { code, message: 'x' } } }, message: 'Request failed' }
}

const flush = () => new Promise((r) => setTimeout(r, 0))

describe('useToast', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'de'
    setOnline(true)
    const { toasts, dismissToast } = useToast()
    for (const toast of [...toasts.value]) dismissToast(toast.id)
  })

  it('notifySuccess zeigt einen Erfolgs-Toast, der nach 4 s verschwindet', () => {
    vi.useFakeTimers()
    const { toasts, notifySuccess } = useToast()
    notifySuccess('Gegossen')
    expect(toasts.value).toHaveLength(1)
    expect(toasts.value[0]).toMatchObject({ text: 'Gegossen', type: 'success' })
    vi.advanceTimersByTime(4000)
    expect(toasts.value).toHaveLength(0)
    vi.useRealTimers()
  })

  it('stapelt gleiche Meldungen nicht und begrenzt auf drei Toasts', () => {
    const { toasts, notifySuccess, notifyInfo } = useToast()
    notifySuccess('A')
    notifySuccess('A')
    expect(toasts.value).toHaveLength(1)
    notifyInfo('B')
    notifyInfo('C')
    notifyInfo('D')
    expect(toasts.value.map((x) => x.text)).toEqual(['B', 'C', 'D'])
  })

  it('notifyUndoable ruft Undo genau einmal auf', async () => {
    vi.useFakeTimers()
    const { toasts, notifyUndoable } = useToast()
    const undo = vi.fn()
    notifyUndoable('Gelöscht', undo)
    const toast = toasts.value[0]
    expect(toast.type).toBe('success')
    expect(toast.action?.label).toBe(t('common.undo'))
    toast.action!.onAction()
    toast.action!.onAction()
    await vi.runAllTimersAsync()
    expect(undo).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })

  it('Undo-Toast bleibt 6 s stehen', () => {
    vi.useFakeTimers()
    const { toasts, notifyUndoable } = useToast()
    notifyUndoable('Erledigt', () => {})
    vi.advanceTimersByTime(TOAST_ACTION_DURATION - 1)
    expect(toasts.value).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(toasts.value).toHaveLength(0)
    vi.useRealTimers()
  })

  it('scheitert das Undo, erscheint eine Fehlermeldung', async () => {
    const { toasts, notifyUndoable } = useToast()
    notifyUndoable('Gelöscht', () => Promise.reject(new Error('boom')))
    toasts.value[0].action!.onAction()
    await flush()
    expect(toasts.value.at(-1)).toMatchObject({ type: 'error', text: t('common.undoError') })
  })

  it('errorText übersetzt bekannte Fehlercodes und fällt sonst auf den Text zurück', () => {
    expect(errorText('Fallback', apiError('BILL_ALREADY_BOOKED'))).toBe(t('errors.BILL_ALREADY_BOOKED'))
    expect(errorText('Fallback', apiError('SOMETHING_NEW'))).toBe('Fallback')
    expect(errorText('Fallback', { message: 'Network Error' })).toBe(t('errors.network'))
    expect(errorText('Fallback')).toBe('Fallback')
    setOnline(false)
    expect(errorText('Fallback', new Error('x'))).toBe(t('offline.actionBlocked'))
  })
})

describe('useAsyncAction', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'de'
    setOnline(true)
    const { toasts, dismissToast } = useToast()
    for (const toast of [...toasts.value]) dismissToast(toast.id)
  })

  it('zeigt bei Erfolg die Meldung und gibt true zurück', async () => {
    const { run } = useAsyncAction()
    const { toasts } = useToast()
    const ok = await run(() => Promise.resolve(3), { success: (n) => `${n} gegossen` })
    expect(ok).toBe(true)
    expect(toasts.value[0]).toMatchObject({ text: '3 gegossen', type: 'success' })
  })

  it('verhindert Doppelklicks pro Schlüssel', async () => {
    const { run, isPending } = useAsyncAction()
    let resolve!: () => void
    const fn = vi.fn(() => new Promise<void>((r) => { resolve = r }))
    const first = run(fn, { key: 'p1' })
    expect(isPending('p1')).toBe(true)
    expect(await run(fn, { key: 'p1' })).toBe(false)
    // anderer Schlüssel läuft parallel
    await run(() => Promise.resolve(), { key: 'p2' })
    resolve()
    expect(await first).toBe(true)
    expect(fn).toHaveBeenCalledTimes(1)
    expect(isPending('p1')).toBe(false)
  })

  it('sendet offline nichts und zeigt einen Hinweis', async () => {
    setOnline(false)
    const { run } = useAsyncAction()
    const { toasts } = useToast()
    const fn = vi.fn(() => Promise.resolve())
    expect(await run(fn)).toBe(false)
    expect(fn).not.toHaveBeenCalled()
    expect(toasts.value[0]).toMatchObject({ type: 'info', text: t('offline.actionBlocked') })
  })

  it('requireOnline: false lässt die Aktion offline zu', async () => {
    setOnline(false)
    const { run } = useAsyncAction()
    const fn = vi.fn(() => Promise.resolve())
    expect(await run(fn, { requireOnline: false })).toBe(true)
    expect(fn).toHaveBeenCalled()
  })

  it('zeigt bei Fehler den übersetzten Code bzw. den Fallback', async () => {
    const { run } = useAsyncAction()
    const { toasts } = useToast()
    expect(await run(() => Promise.reject(apiError('PLANT_NOT_FOUND')), { error: 'Gießen fehlgeschlagen' })).toBe(false)
    expect(toasts.value.at(-1)).toMatchObject({ type: 'error', text: t('errors.PLANT_NOT_FOUND') })
    await run(() => Promise.reject(new Error('x')), { error: 'Gießen fehlgeschlagen' })
    expect(toasts.value.at(-1)).toMatchObject({ type: 'error', text: 'Gießen fehlgeschlagen' })
  })

  it('bietet mit undo einen Rückgängig-Button an', async () => {
    const { run } = useAsyncAction()
    const { toasts } = useToast()
    const undo = vi.fn()
    await run(() => Promise.resolve('id-1'), { success: 'Erledigt', undo })
    toasts.value[0].action!.onAction()
    await flush()
    expect(undo).toHaveBeenCalledWith('id-1')
  })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useLoader', () => {
  it('setzt loadError bei Fehler und nach erfolgreichem Retry zurück', async () => {
    const { useLoader } = await import('../useLoader')
    let fail = true
    const { loadError, reload, reloading } = useLoader(() => (fail ? Promise.reject(new Error('x')) : Promise.resolve()))
    await reload()
    expect(loadError.value).toBe(true)
    fail = false
    const p = reload()
    expect(reloading.value).toBe(true)
    await p
    expect(loadError.value).toBe(false)
    expect(reloading.value).toBe(false)
  })
})
