/**
 * Plattform-Erkennung: Web (PWA) oder native Hülle (Capacitor, iOS/Android).
 *
 * Die nativen Apps laden dasselbe Frontend-Bundle. Unterschiede, die hier abgefragt werden:
 * - Refresh-Token: Web = HttpOnly-Cookie, nativ = SecureStorage/Preferences (services/tokenStorage.ts)
 * - Abos: Web = Stripe-Checkout, nativ = Store-Abrechnung (Apple/Google verlangen das für
 *   digitale Abos; Stripe-Links sind dort nicht erlaubt)
 * - Push: Web Push nur im Browser; nativ später über APNs/FCM
 *
 * Capacitor stellt `window.Capacitor` bereit; ohne das Objekt läuft die Web-Variante.
 */

interface CapacitorGlobal {
  isNativePlatform?: () => boolean
  getPlatform?: () => string
  Plugins?: Record<string, unknown>
}

function capacitor(): CapacitorGlobal | undefined {
  if (typeof window === 'undefined') return undefined
  return (window as unknown as { Capacitor?: CapacitorGlobal }).Capacitor
}

export function isNativeApp(): boolean {
  try {
    return capacitor()?.isNativePlatform?.() === true
  } catch {
    return false
  }
}

/** 'ios' | 'android' | 'web' */
export function platformName(): string {
  try {
    return capacitor()?.getPlatform?.() ?? 'web'
  } catch {
    return 'web'
  }
}
