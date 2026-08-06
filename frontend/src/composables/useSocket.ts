import { ref } from 'vue'
import { io, type Socket } from 'socket.io-client'

let socket: Socket | null = null
const isConnected = ref(false)

function connect(token: string) {
  if (socket?.connected) {
    return
  }

  // Socket.IO-Client hängt /socket.io automatisch als Path an,
  // daher URL OHNE /socket.io Suffix verwenden
  socket = io(import.meta.env.VITE_API_URL, {
    auth: { token },
  })

  socket.on('connect', () => {
    isConnected.value = true
  })

  socket.on('disconnect', () => {
    isConnected.value = false
  })
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

function disconnect() {
  if (!socket) return
  socket.disconnect()
  socket = null
  isConnected.value = false
}

export function useSocket() {
  return {
    connect,
    joinHousehold,
    leaveHousehold,
    on,
    off,
    disconnect,
    isConnected,
  }
}
