/**
 * Token-Haltung im Web-Build (H-01, docs/security/hardening-review.md):
 *
 * - Access-Token (15 Min.) nur im Speicher des Auth-Stores, nie persistiert.
 * - Refresh-Token als HttpOnly-Cookie `casa_rt`, vom Backend gesetzt und gelesen —
 *   für JavaScript (und damit für XSS) unsichtbar. Alle Tabs teilen sich den Cookie,
 *   ein Cross-Tab-Abgleich des Refresh-Tokens ist deshalb nicht mehr nötig.
 * - localStorage hält nur noch einen Sitzungs-Marker ohne Geheimnis: Er sagt beim
 *   Start, ob sich ein /refresh-Versuch lohnt (kein 401-Rauschen für Besucher der
 *   Login-Seite), und synchronisiert Login/Logout zwischen Tabs (storage-Event).
 *
 * Native Builds (Capacitor) haben keinen Browser-Cookie-Jar im selben Sinn. Dort wird
 * der Refresh-Token per Body ausgetauscht (ohne den Header `X-Requested-With: casa`,
 * siehe api/client.ts) und über `nativeRefreshToken` unten abgelegt: bevorzugt in einem
 * SecureStorage-Plugin (Keychain/Keystore), sonst in Capacitor Preferences, zuletzt im
 * localStorage der WebView (App-privat, aber unverschlüsselt — nur Entwicklung).
 */

/** localStorage-Schlüssel des Sitzungs-Markers ("1" = Cookie-Sitzung vermutlich vorhanden). */
export const SESSION_MARKER_KEY = 'haushalt_session'

/** Schlüssel der früheren Token-Persistenz (Access- + Refresh-Token im Klartext). */
const LEGACY_TOKEN_KEY = 'haushalt_tokens'

export const sessionMarker = {
  isSet(): boolean {
    return localStorage.getItem(SESSION_MARKER_KEY) === '1'
  },
  set(): void {
    // Nur schreiben, wenn sich der Wert ändert — sonst feuert in anderen Tabs kein storage-Event,
    // und ein unveränderter Wert braucht keines.
    if (!this.isSet()) localStorage.setItem(SESSION_MARKER_KEY, '1')
  },
  clear(): void {
    localStorage.removeItem(SESSION_MARKER_KEY)
  },
}

/**
 * Einmalige Migration: Liest den Refresh-Token der alten localStorage-Persistenz aus
 * und löscht den Eintrag — unabhängig davon, ob er lesbar war. Der Token wird danach
 * genau einmal per Body gegen einen Cookie getauscht (Auth-Store, initialize()).
 */
export function takeLegacyRefreshToken(): string | null {
  const raw = localStorage.getItem(LEGACY_TOKEN_KEY)
  if (raw === null) return null
  localStorage.removeItem(LEGACY_TOKEN_KEY)
  try {
    const parsed = JSON.parse(raw)
    return typeof parsed?.refreshToken === 'string' && parsed.refreshToken ? parsed.refreshToken : null
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------
// Native Builds: Refresh-Token-Ablage (docs/mobile-apps.md)
// ---------------------------------------------------------------------------

const NATIVE_REFRESH_KEY = 'haushalt_native_refresh'

interface KeyValuePlugin {
  get(options: { key: string }): Promise<{ value: string | null }>
  set(options: { key: string; value: string }): Promise<void>
  remove(options: { key: string }): Promise<void>
}

/** SecureStorage (capacitor-secure-storage-plugin) vor Preferences (@capacitor/preferences). */
function nativePlugin(): KeyValuePlugin | null {
  if (typeof window === 'undefined') return null
  const plugins = (window as unknown as { Capacitor?: { Plugins?: Record<string, unknown> } }).Capacitor?.Plugins
  const candidate = (plugins?.SecureStorage ?? plugins?.Preferences) as KeyValuePlugin | undefined
  return candidate && typeof candidate.get === 'function' ? candidate : null
}

export const nativeRefreshToken = {
  async get(): Promise<string | null> {
    const plugin = nativePlugin()
    if (plugin) {
      try {
        return (await plugin.get({ key: NATIVE_REFRESH_KEY })).value || null
      } catch {
        return null
      }
    }
    return localStorage.getItem(NATIVE_REFRESH_KEY)
  },
  async set(token: string): Promise<void> {
    const plugin = nativePlugin()
    if (plugin) {
      await plugin.set({ key: NATIVE_REFRESH_KEY, value: token })
      return
    }
    localStorage.setItem(NATIVE_REFRESH_KEY, token)
  },
  async clear(): Promise<void> {
    const plugin = nativePlugin()
    if (plugin) {
      try {
        await plugin.remove({ key: NATIVE_REFRESH_KEY })
      } catch {
        // Best-effort
      }
      return
    }
    localStorage.removeItem(NATIVE_REFRESH_KEY)
  },
}
