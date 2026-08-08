import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineCalendarRepository } from '../repositories/calendarRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type {
  CalendarEvent,
  CalendarEventCreatePayload,
  CalendarEventUpdatePayload,
  HouseholdMemberInfo,
} from '../types'

/**
 * Berechnet den ISO-Datumstring (YYYY-MM-DD) des Montags der Woche,
 * in der das gegebene Datum liegt.
 */
function getMondayOfWeek(date: Date): string {
  const d = new Date(date)
  const day = d.getDay() // 0=So, 1=Mo, ...
  const diff = day === 0 ? -6 : 1 - day
  d.setDate(d.getDate() + diff)
  return formatDate(d)
}

function formatDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function addDays(dateStr: string, days: number): string {
  const d = new Date(dateStr + 'T00:00:00')
  d.setDate(d.getDate() + days)
  return formatDate(d)
}

export const useCalendarStore = defineStore('calendar', () => {
  // Repositories
  const repo = createOnlineCalendarRepository()
  const householdRepo = createOnlineHouseholdsRepository()

  // State
  const events = ref<CalendarEvent[]>([])
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)
  const currentWeekStart = ref<string>(getMondayOfWeek(new Date()))

  // Interner State für Race-Condition-Schutz
  const pendingTempIds = new Set<string>()

  // Actions
  async function fetchEvents() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const fromDate = currentWeekStart.value
    const toDate = addDays(fromDate, 6) // Sonntag

    loading.value = true
    try {
      events.value = await repo.fetchByRange(householdId, fromDate, toDate)
    } finally {
      loading.value = false
    }
  }

  async function fetchMembers() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    members.value = await householdRepo.fetchMembers(householdId)
  }

  async function addEvent(payload: CalendarEventCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // 1. Optimistic: Sofort lokalen Temp-Eintrag erzeugen
    const tempId = crypto.randomUUID()
    const tempEvent: CalendarEvent = {
      id: tempId,
      household_id: householdId,
      title: payload.title,
      starts_at: payload.starts_at,
      ends_at: payload.ends_at ?? null,
      all_day: payload.all_day ?? false,
      category: payload.category ?? 'sonstiges',
      participant_ids: payload.participant_ids ?? [],
      note: payload.note ?? null,
      created_by_user_id: authStore.user?.id ?? '',
      created_at: new Date().toISOString(),
    }
    events.value.push(tempEvent)
    pendingTempIds.add(tempId)

    try {
      // 2. Server-Call via Repository
      const serverEvent = await repo.create(householdId, payload)
      pendingTempIds.delete(tempId)

      // 3. Defensive Duplikat-Prüfung: Socket könnte schneller gewesen sein
      const serverIdx = events.value.findIndex(e => e.id === serverEvent.id)
      const tempIdx = events.value.findIndex(e => e.id === tempId)

      if (serverIdx !== -1 && tempIdx !== -1) {
        // Socket war schneller → Server-Event existiert bereits → Temp-Event entfernen
        events.value.splice(tempIdx, 1)
      } else if (tempIdx !== -1) {
        // Normaler Fall → Temp-Event durch Server-Event ersetzen
        events.value[tempIdx] = serverEvent
      }
    } catch (error) {
      pendingTempIds.delete(tempId)
      // 4. Rollback bei Fehler
      events.value = events.value.filter(e => e.id !== tempId)
      throw error
    }
  }

  async function updateEvent(eventId: string, payload: CalendarEventUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const item = events.value.find(e => e.id === eventId)
    if (!item) return

    // 1. Snapshot für Rollback
    const snapshot = { ...item }

    // 2. Optimistic: Sofort aktualisieren
    Object.assign(item, payload)

    try {
      // 3. Server-Call
      await repo.update(householdId, eventId, payload)
    } catch (error) {
      // 4. Rollback auf Snapshot
      Object.assign(item, snapshot)
      throw error
    }
  }

  async function deleteEvent(eventId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // 1. Snapshot für Rollback
    const itemIndex = events.value.findIndex(e => e.id === eventId)
    if (itemIndex === -1) return
    const removedItem = events.value[itemIndex]

    // 2. Optimistic: Sofort entfernen
    events.value.splice(itemIndex, 1)

    try {
      // 3. Server-Call
      await repo.remove(householdId, eventId)
    } catch (error) {
      // 4. Rollback: Item wieder einfügen an gleicher Position
      events.value.splice(itemIndex, 0, removedItem)
      throw error
    }
  }

  function navigateWeek(offset: number) {
    currentWeekStart.value = addDays(currentWeekStart.value, offset * 7)
    fetchEvents()
  }

  // Socket-Handler — Idempotente Merges (Server gewinnt immer)
  function handleEventCreated(serverEvent: CalendarEvent) {
    if (pendingTempIds.size > 0) {
      const existingIdx = events.value.findIndex(e => e.id === serverEvent.id)
      if (existingIdx !== -1) {
        events.value[existingIdx] = serverEvent
      }
      // KEIN push — REST-Response-Handling macht den Swap
      return
    }
    // Normaler Fall (Event von anderem Haushaltsmitglied)
    const existingIdx = events.value.findIndex(e => e.id === serverEvent.id)
    if (existingIdx !== -1) {
      events.value[existingIdx] = serverEvent
    } else {
      events.value.push(serverEvent)
    }
  }

  function handleEventUpdated(serverEvent: CalendarEvent) {
    const idx = events.value.findIndex(e => e.id === serverEvent.id)
    if (idx !== -1) {
      events.value[idx] = serverEvent // Server gewinnt immer
    }
  }

  function handleEventDeleted(data: { id: string }) {
    events.value = events.value.filter(e => e.id !== data.id)
  }

  return {
    // State
    events,
    members,
    loading,
    currentWeekStart,
    // Actions
    fetchEvents,
    fetchMembers,
    addEvent,
    updateEvent,
    deleteEvent,
    navigateWeek,
    // Socket-Handlers
    handleEventCreated,
    handleEventUpdated,
    handleEventDeleted,
  }
})
