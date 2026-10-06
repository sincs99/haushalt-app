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
 * Native Builds (Capacitor) haben keinen Browser-Cookie-Jar im selben Sinn. Dort
 * müsste der Refresh-Token per Body ausgetauscht werden (ohne den Header
 * `X-Requested-With: casa`; das Backend unterstützt diesen Pfad weiterhin) und in
 * SecureStorage abgelegt werden — nicht Teil des Web-Builds.
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
