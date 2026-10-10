/**
 * CASA-41: Update-Prüfung beim Zurückkehren in die App und periodisch; „Update
 * verfügbar“ bleibt bestehen, bis neu geladen wird.
 */
import type {} from 'vitest'

let visibilityHandler: (() => void) | null = null
const doc = {
  visibilityState: 'visible' as 'visible' | 'hidden',
  addEventListener: vi.fn((_: string, fn: () => void) => { visibilityHandler = fn }),
  removeEventListener: vi.fn(),
}

// Vor dem document-Stub laden (vue greift beim Import auf document zu)
async function load() {
  vi.unstubAllGlobals()
  vi.resetModules()
  const mod = await import('../usePwaUpdate')
  vi.stubGlobal('document', doc)
  vi.stubGlobal('navigator', { onLine: true })
  return mod
}

beforeEach(() => {
  vi.useFakeTimers()
  visibilityHandler = null
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

test('prüft beim Zurückkehren in die App (gedrosselt) und stündlich', async () => {
  const { watchForUpdates, MIN_CHECK_GAP_MS, UPDATE_CHECK_INTERVAL_MS } = await load()
  const registration = { update: vi.fn().mockResolvedValue(undefined) }
  const stop = watchForUpdates(registration)

  doc.visibilityState = 'visible'
  visibilityHandler!()
  expect(registration.update).not.toHaveBeenCalled() // gerade erst registriert

  vi.advanceTimersByTime(MIN_CHECK_GAP_MS + 1)
  visibilityHandler!()
  expect(registration.update).toHaveBeenCalledTimes(1)
  visibilityHandler!()
  expect(registration.update).toHaveBeenCalledTimes(1) // gedrosselt

  vi.advanceTimersByTime(UPDATE_CHECK_INTERVAL_MS)
  expect(registration.update).toHaveBeenCalledTimes(2)
  stop()
})

test('offline: keine Prüfung', async () => {
  const { watchForUpdates, MIN_CHECK_GAP_MS } = await load()
  vi.stubGlobal('navigator', { onLine: false })
  const registration = { update: vi.fn().mockResolvedValue(undefined) }
  watchForUpdates(registration)
  vi.advanceTimersByTime(MIN_CHECK_GAP_MS + 1)
  visibilityHandler!()
  expect(registration.update).not.toHaveBeenCalled()
})

test('Update verfügbar bleibt gesetzt und lädt über die SW-Funktion neu', async () => {
  const { setUpdateAvailable, usePwaUpdate } = await load()
  const { updateAvailable, reloadForUpdate } = usePwaUpdate()
  expect(updateAvailable.value).toBe(false)

  const apply = vi.fn()
  setUpdateAvailable(apply)
  vi.advanceTimersByTime(10 * 60_000) // kein Ablauf wie beim Toast
  expect(updateAvailable.value).toBe(true)

  reloadForUpdate()
  expect(apply).toHaveBeenCalledTimes(1)
})
