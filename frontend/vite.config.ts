import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      // Update erst nach Bestätigung (Toast) aktivieren — kein Reload mitten in einer Eingabe
      registerType: 'prompt',
      // Icons: aus public/logo.svg via `npm run pwa:icons` erzeugt und eingecheckt
      includeAssets: ['favicon.ico', 'apple-touch-icon-180x180.png', 'logo.svg'],
      manifest: {
        name: 'Haushalt App',
        short_name: 'Haushalt',
        description: 'Einkaufsliste, Aufgaben, Putzplan und Ausgaben für den ganzen Haushalt',
        lang: 'de',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#DDE8E4',
        theme_color: '#DDE8E4',
        icons: [
          { src: 'pwa-64x64.png', sizes: '64x64', type: 'image/png' },
          { src: 'pwa-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'pwa-512x512.png', sizes: '512x512', type: 'image/png' },
          { src: 'maskable-icon-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
        // Langes Drücken auf das App-Icon (Android/Chrome, Desktop)
        shortcuts: [
          { name: 'Einkaufsliste', short_name: 'Einkauf', url: '/shopping' },
          { name: 'Aufgaben', short_name: 'Aufgaben', url: '/todos' },
          { name: 'Haustiere', short_name: 'Tiere', url: '/pets' },
        ],
        // Tag-Scans (/t/<token>, NFC/QR) in einem bereits offenen App-Fenster
        // öffnen statt jedes Mal ein neues zu starten (Chromium)
        launch_handler: { client_mode: ['navigate-existing', 'auto'] },
      },
      workbox: {
        // Nur die App-Shell precachen. API-Daten werden bewusst NICHT gecacht
        // (Offline-Sync kommt separat, siehe docs/offline-ready-architecture.md)
        globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2}'],
        // Navigationen (auch /t/<token> von NFC/QR-Tags) bekommen die vorgecachte
        // App-Shell; die Antwort hängt nicht vom Pfad ab, der Token landet in
        // keinem Cache. Ohne runtimeCaching werden auch die POST-Aufrufe an
        // /api/tags/* nie gecacht.
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/socket\.io\//],
        cleanupOutdatedCaches: true,
        // Push- und Notification-Click-Handler (public/push-sw.js)
        importScripts: ['/push-sw.js'],
      },
    }),
  ],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/socket.io': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
