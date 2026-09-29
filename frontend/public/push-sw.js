// Push-Handler — wird per workbox.importScripts in den generierten Service Worker geladen.
// Payload (vom Backend, app/services/push_service.py): { title, body, url, tag }

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = { body: event.data ? event.data.text() : '' }
  }

  event.waitUntil(
    self.registration.showNotification(data.title || 'Haushalt App', {
      body: data.body || '',
      tag: data.tag,
      icon: '/pwa-192x192.png',
      badge: '/pwa-64x64.png',
      data: { url: data.url || '/' },
    }),
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
