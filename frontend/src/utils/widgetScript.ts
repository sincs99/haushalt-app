import template from '../assets/scriptable-widget.js?raw'

/**
 * Scriptable-Skript mit eingesetzter Adresse, Schlüssel und Sprache.
 * Die Vorlage liegt in assets/scriptable-widget.js (läuft nur in Scriptable, nicht im Browser).
 */
export async function buildWidgetScript(baseUrl: string, key: string, lang: string): Promise<string> {
  const origin = baseUrl.replace(/\/+$/, '')
  const locale = lang === 'en' ? 'en' : 'de'
  // Kein Bearer-Geheimnis im Dateinamen; unterschiedliche Server/Schlüssel/Sprachen
  // teilen niemals einen Cache. Web Crypto ist im HTTPS-Betrieb verfügbar.
  const digest = await crypto.subtle.digest(
    'SHA-256', new TextEncoder().encode(JSON.stringify([origin, key, locale])),
  )
  const cacheId = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('')
  return template
    .replace("'__BASE_URL__'", () => JSON.stringify(origin))
    .replace("'__WIDGET_KEY__'", () => JSON.stringify(key))
    .replace("'__LANG__'", () => JSON.stringify(locale))
    .replace("'__CACHE_ID__'", () => JSON.stringify(cacheId))
}
