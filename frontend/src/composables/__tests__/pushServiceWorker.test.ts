/**
 * public/push-sw.js (CASA-40): Die Zahl am App-Icon aus einer Push-Payload wird nur
 * übernommen, wenn sie zum Haushalt gehört, den die App gerade zeigt.
 *
 * Das Skript läuft hier mit einem nachgebauten Service-Worker-Global.
 */
import type {} from 'vitest'
import SCRIPT from '../../../public/push-sw.js?raw'

type Listener = (event: any) => void

function loadServiceWorker() {
  const listeners = new Map<string, Listener>()
  const store = new Map<string, string>()
  const cache = {
    match: vi.fn(async (key: string) => (store.has(key) ? new Response(store.get(key)!) : undefined)),
    put: vi.fn(async (key: string, res: Response) => { store.set(key, await res.text()) }),
    delete: vi.fn(async (key: string) => store.delete(key)),
  }
  const self = {
    location: { origin: 'https://casa.test' },
    navigator: { setAppBadge: vi.fn().mockResolvedValue(undefined), clearAppBadge: vi.fn().mockResolvedValue(undefined) },
    registration: { showNotification: vi.fn().mockResolvedValue(undefined) },
    clients: { matchAll: vi.fn().mockResolvedValue([]), openWindow: vi.fn() },
    addEventListener: (type: string, fn: Listener) => listeners.set(type, fn),
  }
  const caches = { open: vi.fn(async () => cache) }
  new Function('self', 'caches', SCRIPT)(self, caches)

  async function dispatch(type: string, data: unknown) {
    let done: Promise<unknown> = Promise.resolve()
    listeners.get(type)!({ data, waitUntil: (p: Promise<unknown>) => { done = p } })
    await done
  }
  return {
    self,
    setCurrent: (householdId: string | null) => dispatch('message', { type: 'casa:current-household', householdId }),
    push: (payload: object) => dispatch('push', { json: () => payload }),
  }
}

test('Push des aktuellen Haushalts setzt die Zahl', async () => {
  const sw = loadServiceWorker()
  await sw.setCurrent('hh-A')
  await sw.push({ title: 'T', url: '/todos?hh=hh-A', badge: 3 })
  expect(sw.self.navigator.setAppBadge).toHaveBeenCalledWith(3)
})

test('Push eines anderen Haushalts: Benachrichtigung ja, Zahl nein', async () => {
  const sw = loadServiceWorker()
  await sw.setCurrent('hh-A')
  await sw.push({ title: 'T', url: '/pets/p1?hh=hh-B', badge: 5 })
  expect(sw.self.registration.showNotification).toHaveBeenCalled()
  expect(sw.self.navigator.setAppBadge).not.toHaveBeenCalled()
})

test('ohne bekannten Haushalt (noch keine Nachricht der App) wird die Zahl gesetzt', async () => {
  const sw = loadServiceWorker()
  await sw.push({ title: 'T', url: '/todos?hh=hh-B', badge: 2 })
  expect(sw.self.navigator.setAppBadge).toHaveBeenCalledWith(2)
})
