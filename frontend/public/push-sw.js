// Push-Handler — wird per workbox.importScripts in den generierten Service Worker geladen.
// Payload (vom Backend, app/services/push_service.py): { title, body, url, tag, badge? }
// `url` trägt den Haushalt als `?hh=<id>` (CASA-40).

// Aktueller Haushalt der App (per postMessage aus useAppBadge.ts). Im Cache Storage,
// weil der Service Worker zwischen zwei Pushes beendet werden kann.
const STATE_CACHE = 'casa-state'
const CURRENT_HOUSEHOLD_KEY = '/__casa/current-household'

async function getCurrentHousehold() {
  try {
    const cache = await caches.open(STATE_CACHE)
    const res = await cache.match(CURRENT_HOUSEHOLD_KEY)
    return res ? await res.text() : null
  } catch {
    return null
  }
}

async function setCurrentHousehold(householdId) {
  try {
    const cache = await caches.open(STATE_CACHE)
    if (householdId) await cache.put(CURRENT_HOUSEHOLD_KEY, new Response(householdId))
    else await cache.delete(CURRENT_HOUSEHOLD_KEY)
  } catch {
    // Best-effort
  }
}

function householdOfUrl(url) {
  try {
    return new URL(url || '/', self.location.origin).searchParams.get('hh')
  } catch {
    return null
  }
}

self.addEventListener('message', (event) => {
  const msg = event.data
  if (!msg || msg.type !== 'casa:current-household') return
  event.waitUntil(setCurrentHousehold(msg.householdId || null))
})

// Zahl am App-Icon (Badging API, services/attention.py im Backend). Die Zahl gilt für den
// Haushalt der Benachrichtigung — nur übernehmen, wenn die App gerade diesen zeigt,
// sonst springt das Icon zwischen den Haushalten hin und her (CASA-40).
async function updateAppBadge(count, url) {
  if (typeof count !== 'number' || !('setAppBadge' in self.navigator)) return
  const hh = householdOfUrl(url)
  if (hh) {
    const current = await getCurrentHousehold()
    if (current && current !== hh) return
  }
  try {
    if (count > 0) await self.navigator.setAppBadge(count)
    else await self.navigator.clearAppBadge()
  } catch {
    // Nicht erlaubt/unterstützt — Benachrichtigung trotzdem anzeigen
  }
}

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = { body: event.data ? event.data.text() : '' }
  }

  event.waitUntil(
    Promise.all([
      self.registration.showNotification(data.title || 'Haushalt App', {
        body: data.body || '',
        tag: data.tag,
        icon: '/pwa-192x192.png',
        badge: '/pwa-64x64.png',
        data: { url: data.url || '/' },
      }),
      updateAppBadge(data.badge, data.url),
    ]),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  // Nur same-origin Pfade öffnen
  const target = new URL(event.notification.data?.url || '/', self.location.origin)
  const url = target.origin === self.location.origin ? target.href : self.location.origin + '/'

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (clients) => {
      const client = clients.find((c) => new URL(c.url).origin === self.location.origin)
      if (client) {
        await client.focus()
        try {
          return await client.navigate(url)
        } catch {
          // navigate() geht nur für kontrollierte Clients — sonst neues Fenster
        }
      }
      return self.clients.openWindow(url)
    }),
  )
})
