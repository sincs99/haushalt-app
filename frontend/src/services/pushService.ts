/**
 * Web Push: Browser-Subscription verwalten und mit dem Backend synchron halten.
 *
 * iOS/iPadOS: Push funktioniert nur, wenn die App über "Zum Home-Bildschirm"
 * installiert wurde (ab iOS 16.4) — im normalen Safari-Tab gibt es kein PushManager.
 */
import i18n from '../i18n'
import { createOnlinePushRepository } from '../repositories/pushRepository'

const repo = createOnlinePushRepository()

export type PushSupport =
  | 'supported'
  | 'ios-needs-install' // iOS-Safari-Tab: erst zum Home-Bildschirm hinzufügen
  | 'unsupported'

export function getPushSupport(): PushSupport {
  const hasApis = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
  if (hasApis) return 'supported'

  const isIos = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches
    || (navigator as Navigator & { standalone?: boolean }).standalone === true
  return isIos && !isStandalone ? 'ios-needs-install' : 'unsupported'
}

export function getPermission(): NotificationPermission {
  return 'Notification' in window ? Notification.permission : 'denied'
}

async function getRegistration(): Promise<ServiceWorkerRegistration | null> {
  if (!('serviceWorker' in navigator)) return null
  // Kein Service Worker im Vite-Dev-Server → nicht ewig auf .ready warten
  return (await navigator.serviceWorker.getRegistration()) ?? null
}

export async function getCurrentSubscription(): Promise<PushSubscription | null> {
  const reg = await getRegistration()
  return reg ? reg.pushManager.getSubscription() : null
}

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + '='.repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(padded)
  const bytes = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
  return bytes
}

async function sendToBackend(sub: PushSubscription): Promise<void> {
  const json = sub.toJSON()
  await repo.subscribe({
    endpoint: sub.endpoint,
    keys: { p256dh: json.keys?.p256dh ?? '', auth: json.keys?.auth ?? '' },
    locale: i18n.global.locale.value,
  })
}

export class PushError extends Error {
  constructor(public code: 'disabled' | 'denied' | 'no-sw') {
    super(code)
  }
}

/** Muss aus einem User-Klick heraus aufgerufen werden (Permission-Prompt, v.a. iOS). */
export async function enablePush(): Promise<void> {
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new PushError('denied')

  const config = await repo.fetchConfig()
  if (!config.enabled || !config.public_key) throw new PushError('disabled')

  const reg = await getRegistration()
  if (!reg) throw new PushError('no-sw')

  let sub = await reg.pushManager.getSubscription()
  const key = urlBase64ToUint8Array(config.public_key)
  // Nach VAPID-Key-Rotation passt die bestehende Subscription nicht mehr
  const existingKey = sub?.options.applicationServerKey
  if (sub && existingKey && !sameBytes(new Uint8Array(existingKey), key)) {
    await sub.unsubscribe()
    sub = null
  }
  sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key })

  await sendToBackend(sub)
}

/**
 * notifyBackend=false z.B. bei abgelaufener Session: Der Browser meldet sich trotzdem
 * ab; das Backend räumt den Endpoint beim nächsten Versand selbst auf (HTTP 410).
 */
export async function disablePush({ notifyBackend = true } = {}): Promise<void> {
  const sub = await getCurrentSubscription()
  if (!sub) return
  try {
    if (notifyBackend) await repo.unsubscribe(sub.endpoint)
  } finally {
    await sub.unsubscribe()
  }
}

/**
 * Beim App-Start / nach Login / nach Sprachwechsel: bestehende Subscription dem
 * aktuellen User + Locale zuordnen. Fragt NIE nach Permission. Best-effort.
 */
export async function syncPushSubscription(): Promise<void> {
  try {
    if (getPushSupport() !== 'supported' || getPermission() !== 'granted') return
    const sub = await getCurrentSubscription()
    if (sub) await sendToBackend(sub)
  } catch {
    // Offline oder Push im Backend deaktiviert — beim nächsten Start erneut
  }
}

export async function sendTestPush(): Promise<number> {
  const { sent } = await repo.sendTest()
  return sent
}

function sameBytes(a: Uint8Array, b: Uint8Array): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i])
}
