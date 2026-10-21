import { computed, type ComputedRef } from 'vue'
import { useSocket } from './useSocket'
import { useConnectivity } from './useConnectivity'
import { useAuthStore } from '../stores/auth'

export type SyncStatus = 'offline' | 'connected' | 'reconnecting'

/**
 * Status des Sync-Punkts. „Verbunden“ heisst: Socket steht UND der Room des aktuellen
 * Haushalts ist betreten. Scheitert `join_household` (Server schickt `error`), bleibt der
 * Punkt gelb, bis der erneute Beitritt klappt (CASA-46).
 */
export function useSyncStatus(): ComputedRef<SyncStatus> {
  const { isConnected, roomStatus } = useSocket()
  const { isOnline } = useConnectivity()
  const authStore = useAuthStore()

  return computed<SyncStatus>(() => {
    if (!isOnline.value) return 'offline'
    if (!isConnected.value) return 'reconnecting'
    if (authStore.currentHouseholdId && roomStatus.value !== 'joined') return 'reconnecting'
    return 'connected'
  })
}
