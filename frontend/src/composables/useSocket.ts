import { ref } from 'vue'
import { io, type Socket } from 'socket.io-client'
import { API_BASE } from '../api/client'

let socket: Socket | null = null
const isConnected = ref(false)

// Aktuelles Access-Token. Socket.IO liest es über die auth-Funktion bei jedem
// (Re-)Connect neu, damit automatische Reconnects nie mit einem alten Token laufen.
let currentToken: string | null = null

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

  s.on('disconnect', (reason) => {
    isConnected.value = false
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

function joinHousehold(householdId: string) {
  if (!socket) return
  socket.emit('join_household', { household_id: householdId })
}

function leaveHousehold(householdId: string) {
  if (!socket) return
  socket.emit('leave_household', { household_id: householdId })
}

function on(event: string, callback: (...args: any[]) => void) {
  if (!socket) return
  socket.on(event, callback)
}

function off(event: string, callback: (...args: any[]) => void) {
  if (!socket) return
  socket.off(event, callback)
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
  if (!socket) return
  const s = socket
  socket = null
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
  }
}
