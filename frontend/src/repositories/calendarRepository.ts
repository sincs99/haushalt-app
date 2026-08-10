import api from '../api/client'
import type {
  CalendarEvent,
  CalendarEventCreatePayload,
  CalendarEventUpdatePayload,
  CalendarInfo,
  CalendarCreatePayload,
  CalendarUpdatePayload,
} from '../types'

export interface CalendarRepository {
  // Event-Methoden
  fetchByRange(householdId: string, fromDate: string, toDate: string): Promise<CalendarEvent[]>
  create(householdId: string, data: CalendarEventCreatePayload): Promise<CalendarEvent>
  update(householdId: string, eventId: string, data: CalendarEventUpdatePayload): Promise<CalendarEvent>
  remove(householdId: string, eventId: string): Promise<void>

  // Calendar-CRUD
  fetchCalendars(householdId: string): Promise<CalendarInfo[]>
  createCalendar(householdId: string, data: CalendarCreatePayload): Promise<CalendarInfo>
  updateCalendar(householdId: string, calendarId: string, data: CalendarUpdatePayload): Promise<CalendarInfo>
  deleteCalendar(householdId: string, calendarId: string): Promise<void>
}

export function createOnlineCalendarRepository(): CalendarRepository {
  return {
    // ── Events ──
    async fetchByRange(householdId, fromDate, toDate) {
      const { data } = await api.get<CalendarEvent[]>(
        `/api/households/${householdId}/events/`,
        { params: { from_date: fromDate, to_date: toDate } },
      )
      return data
    },
    async create(householdId, payload) {
      const { data } = await api.post<CalendarEvent>(
        `/api/households/${householdId}/events/`,
        payload,
      )
      return data
    },
    async update(householdId, eventId, payload) {
      const { data } = await api.patch<CalendarEvent>(
        `/api/households/${householdId}/events/${eventId}`,
        payload,
      )
      return data
    },
    async remove(householdId, eventId) {
      await api.delete(`/api/households/${householdId}/events/${eventId}`)
    },

    // ── Calendars ──
    async fetchCalendars(householdId) {
      const { data } = await api.get<CalendarInfo[]>(
        `/api/households/${householdId}/calendars/`,
      )
      return data
    },
    async createCalendar(householdId, payload) {
      const { data } = await api.post<CalendarInfo>(
        `/api/households/${householdId}/calendars/`,
        payload,
      )
      return data
    },
    async updateCalendar(householdId, calendarId, payload) {
      const { data } = await api.patch<CalendarInfo>(
        `/api/households/${householdId}/calendars/${calendarId}`,
        payload,
      )
      return data
    },
    async deleteCalendar(householdId, calendarId) {
      await api.delete(`/api/households/${householdId}/calendars/${calendarId}`)
    },
  }
}
