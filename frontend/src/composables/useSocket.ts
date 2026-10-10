import { ref } from 'vue'
import { io, type Socket } from 'socket.io-client'
import { API_BASE } from '../api/client'
import { isForeignHouseholdPayload } from '../utils/householdGuard'

let socket: Socket | null = null
const isConnected = ref(false)

// Aktuelles Access-Token. Socket.IO liest es über die auth-Funktion bei jedem
// (Re-)Connect neu, damit automatische Reconnects nie mit einem alten Token laufen.
let currentToken: string | null = null

/**
 * Room-Status des aktuellen Haushalts (CASA-46). Der Server meldet einen gescheiterten
 * `join_household` nur über ein `error`-Event — verbunden heisst also noch nicht, dass
 * Events des Haushalts ankommen. Der Sync-Punkt zeigt „verbunden“ erst bei 'joined'.
 */
export type RoomStatus = 'none' | 'joining' | 'joined' | 'failed'
const roomStatus = ref<RoomStatus>('none')
// Haushalt, dessen Room wir betreten wollen bzw. betreten haben
let targetHouseholdId: string | null = null
let joinSeq = 0
let joinAttempt = 0
let joinRetryTimer: ReturnType<typeof setTimeout> | null = null
// Wartezeiten zwischen erneuten Beitrittsversuchen; danach erst wieder bei Reconnect/Wechsel
const JOIN_RETRY_DELAYS_MS = [2_000, 5_000, 15_000, 30_000, 60_000]

// Registrierte Listener → Wrapper mit Haushaltsfilter (pro Callback und Event, mehrfach möglich)
const wrappedHandlers = new Map<(...args: any[]) => void, Map<string, Array<(...args: any[]) => void>>>()

// Reconnect-Mechanismus: Callbacks werden bei automatischem Reconnect aufgerufen
const reconnectCallbacks = new Set<() => void>()
let hasConnectedBefore = false

// Server-seitiges Sitzungsende: Der Server schickt `session_ended` mit Grund
// ("expired" | "logout" | "revoked") und trennt dann. Socket.IO verbindet nach
// einem Server-Disconnect nicht selbst neu, das übernimmt recover().
type TokenRefresher = () => Promise<string | null>
let tokenRefresher: TokenRefresher | null = null
let sessionEndReason: string | null = null
// Höchstens ein Token-Refresh pro Verbindungsverlust (kein Endlos-Refresh, wenn der
// Server die Verbindung aus anderen Gründen ablehnt). Nach "logout"/"revoked" gar
// keiner: Der Refresh-Token kann dann widerrufen sein, ein Refresh damit würde die
// Reuse-Detection auslösen und alle Geräte abmelden.
let refreshBlocked = false

/** Liefert nach Ablauf des Access-Tokens ein frisches Token (null = ausgeloggt). */
function setTokenRefresher(refresher: TokenRefresher | null) {
  tokenRefresher = refresher
}

async function recover(withRefresh: boolean) {
  const s = socket
  if (!s || !currentToken) return
  if (withRefresh) {
    if (refreshBlocked || !tokenRefresher) return
    refreshBlocked = true
    const token = await tokenRefresher()
    if (!token || socket !== s) return
    currentToken = token
  }
  if (!s.active) s.connect()
}

function connect(token: string) {
  currentToken = token
  if (socket) {
    if (!socket.active) socket.connect()
    return
  }

  // Socket.IO-Client hängt /socket.io automatisch als Path an,
  // daher URL OHNE /socket.io Suffix verwenden
  const s = io(API_BASE || undefined, {
    auth: (cb) => cb({ token: currentToken }),
  })
  socket = s

  s.on('connect', () => {
    isConnected.value = true
    refreshBlocked = false

    // Bei Reconnect alle registrierten Callbacks aufrufen
    if (hasConnectedBefore) {
      reconnectCallbacks.forEach((cb) => cb())
    }
    hasConnectedBefore = true
  })

  s.on('session_ended', (data: { reason?: string } | undefined) => {
    sessionEndReason = data?.reason ?? null
  })

  // Gescheiterter join_household (nicht angemeldet, kein Mitglied, Serverfehler):
  // Status zeigen statt „verbunden“ und den Beitritt später erneut versuchen
  s.on('error', () => {
    if (roomStatus.value !== 'joining') return
    roomStatus.value = 'failed'
    scheduleJoinRetry()
  })

  s.on('disconnect', (reason) => {
    isConnected.value = false
    // Nach einem Verbindungsabbruch ist der Socket in keinem Room mehr; den erneuten
    // Beitritt macht der Reconnect-Callback (App.vue)
    clearJoinRetry()
    if (roomStatus.value !== 'none') roomStatus.value = 'none'
    if (reason !== 'io server disconnect') return // alles andere verbindet Socket.IO selbst neu

    const ended = sessionEndReason
    sessionEndReason = null
    if (ended === 'logout' || ended === 'revoked') refreshBlocked = true
    // Abgelaufen → erst frisches Token holen; sonst mit dem aktuellen Token neu
    // verbinden (z.B. hat sich ein anderes Gerät abgemeldet, unser Token gilt noch).
    void recover(ended === 'expired')
  })

  s.on('connect_error', () => {
    // active=false heisst: Server hat die Verbindung abgelehnt (z.B. Token abgelaufen),
    // Socket.IO versucht es nicht erneut. Bei Netzwerkfehlern bleibt active=true.
    if (!s.active) void recover(true)
  })
}

/** Neues Access-Token nach einem Refresh: bestehende Verbindung verlängern statt neu aufbauen. */
function updateToken(token: string) {
  if (!socket) {
    connect(token)
    return
  }
  if (token !== currentToken) {
    currentToken = token
    refreshBlocked = false
    if (socket.connected) {
      socket.emit('reauth', { token })
      return
    }
  }
  if (!socket.active) socket.connect()
}

function clearJoinRetry() {
  if (joinRetryTimer) clearTimeout(joinRetryTimer)
  joinRetryTimer = null
}

function scheduleJoinRetry() {
  clearJoinRetry()
  if (joinAttempt >= JOIN_RETRY_DELAYS_MS.length) return
  const householdId = targetHouseholdId
  const delay = JOIN_RETRY_DELAYS_MS[joinAttempt++]
  joinRetryTimer = setTimeout(() => {
    joinRetryTimer = null
    if (householdId && householdId === targetHouseholdId && socket?.connected) emitJoin(householdId)
  }, delay)
}

function emitJoin(householdId: string) {
  if (!socket) return
  const seq = ++joinSeq
  roomStatus.value = 'joining'
  // Ack kommt, wenn der Server-Handler fertig ist — ein `error` käme vorher an
  socket.emit('join_household', { household_id: householdId }, () => {
    if (seq !== joinSeq || roomStatus.value !== 'joining') return
    roomStatus.value = 'joined'
    joinAttempt = 0
  })
}

function joinHousehold(householdId: string) {
  if (householdId !== targetHouseholdId) joinAttempt = 0
  targetHouseholdId = householdId
  clearJoinRetry()
  emitJoin(householdId)
}

function leaveHousehold(householdId: string) {
  if (householdId === targetHouseholdId) {
    targetHouseholdId = null
    joinSeq++
    clearJoinRetry()
    roomStatus.value = 'none'
  }
  if (!socket) return
  socket.emit('leave_household', { household_id: householdId })
}

/**
 * Listener registrieren. Payloads mit `household_id` eines anderen als des aktuellen
 * Haushalts werden verworfen (CASA-12) — z. B. Events, die zwischen Wechsel und
 * `leave_household` noch aus dem alten Room kommen.
 */
function on(event: string, callback: (...args: any[]) => void) {
  if (!socket) return
  const handler = (...args: any[]) => {
    if (isForeignHouseholdPayload(args[0], targetHouseholdId)) return
    callback(...args)
  }
  let perEvent = wrappedHandlers.get(callback)
  if (!perEvent) {
    perEvent = new Map()
    wrappedHandlers.set(callback, perEvent)
  }
  const list = perEvent.get(event) ?? []
  list.push(handler)
  perEvent.set(event, list)
  socket.on(event, handler)
}

function off(event: string, callback: (...args: any[]) => void) {
  const perEvent = wrappedHandlers.get(callback)
  const handler = perEvent?.get(event)?.pop()
  if (!handler) return
  if (perEvent!.get(event)!.length === 0) perEvent!.delete(event)
  if (perEvent!.size === 0) wrappedHandlers.delete(callback)
  socket?.off(event, handler)
}

function onReconnect(callback: () => void) {
  reconnectCallbacks.add(callback)
}

function offReconnect(callback: () => void) {
  reconnectCallbacks.delete(callback)
}

function disconnect() {
  currentToken = null
  sessionEndReason = null
  refreshBlocked = false
  targetHouseholdId = null
  joinSeq++
  clearJoinRetry()
  roomStatus.value = 'none'
  if (!socket) return
  const s = socket
  socket = null
  wrappedHandlers.clear()
  s.disconnect()
  isConnected.value = false
  hasConnectedBefore = false
}

export function useSocket() {
  return {
    connect,
    updateToken,
    setTokenRefresher,
    joinHousehold,
    leaveHousehold,
    on,
    off,
    onReconnect,
    offReconnect,
    disconnect,
    isConnected,
    roomStatus,
  }
}
