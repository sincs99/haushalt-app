import api from '../api/client'

/**
 * Zahl am App-Icon (Badging API) — was heute für die eingeloggte Person ansteht
 * (Backend: GET /api/households/{id}/dashboard/badge, services/attention.py).
 *
 * Unterstützt in installierten PWAs: iOS/iPadOS ab 16.4 (nur mit erlaubten
 * Benachrichtigungen), Chrome/Edge auf Desktop. Ohne Unterstützung passiert nichts.
 * Im Hintergrund setzt der Service Worker die Zahl aus der Push-Payload (public/push-sw.js).
 */

type BadgeNavigator = Navigator & {
  setAppBadge?: (count?: number) => Promise<void>
  clearAppBadge?: () => Promise<void>
}

/** Socket-Events, nach denen sich die Zahl ändern kann */
export const BADGE_EVENTS = [
  'todo_created',
  'todo_updated',
  'todo_deleted',
  'chore_created',
  'chore_updated',
  'chore_deleted',
  'chore_assignment_created',
  'chore_assignment_updated',
  'pet_care_task_created',
  'pet_care_task_updated',
  'pet_care_task_deleted',
  'plant_care_task_created',
  'plant_care_task_updated',
  'plant_care_task_deleted',
  'plant_care_logged',
  'plant_deleted',
] as const

const REFRESH_DELAY_MS = 1500

let householdId: string | null = null
let timer: ReturnType<typeof setTimeout> | null = null
let listening = false

function badgeNavigator(): BadgeNavigator | null {
  if (typeof navigator === 'undefined') return null
  const nav = navigator as BadgeNavigator
  return typeof nav.setAppBadge === 'function' ? nav : null
}

export function isAppBadgeSupported(): boolean {
  return badgeNavigator() !== null
}

async function apply(count: number): Promise<void> {
  const nav = badgeNavigator()
  if (!nav) return
  try {
    if (count > 0) await nav.setAppBadge!(count)
    else await nav.clearAppBadge?.()
  } catch {
    // z.B. iOS ohne Benachrichtigungs-Erlaubnis — kein Fehler für die App
  }
}

export async function refreshAppBadge(): Promise<void> {
  if (!badgeNavigator() || !householdId) return
  const id = householdId
  try {
    const { data } = await api.get<{ count: number }>(`/api/households/${id}/dashboard/badge`)
    if (id === householdId) await apply(data.count)
  } catch {
    // Offline oder abgemeldet: alte Zahl stehen lassen
  }
}

/** Mehrere Änderungen kurz hintereinander → ein Request */
export function refreshAppBadgeSoon(): void {
  if (!badgeNavigator()) return
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    timer = null
    void refreshAppBadge()
  }, REFRESH_DELAY_MS)
}

function onVisibilityChange(): void {
  if (document.visibilityState === 'visible') void refreshAppBadge()
}

/**
 * Dem Service Worker den aktuellen Haushalt mitteilen: Er setzt die Zahl aus einer
 * Push-Payload nur, wenn sie zu diesem Haushalt gehört (public/push-sw.js, CASA-40).
 */
function notifyServiceWorker(id: string | null): void {
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return
  navigator.serviceWorker.ready
    .then((registration) => {
      registration.active?.postMessage({ type: 'casa:current-household', householdId: id })
    })
    .catch(() => {
      // Kein Service Worker (Dev, nicht unterstützt) — nichts zu tun
    })
}

/** Aktuellen Haushalt setzen (null = abgemeldet → Zahl entfernen). */
export function setAppBadgeHousehold(id: string | null): void {
  const changed = id !== householdId
  householdId = id
  if (changed) notifyServiceWorker(id)
  if (!badgeNavigator()) return
  if (!listening && typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange)
    listening = true
  }
  if (id) void refreshAppBadge()
  else void apply(0)
}
