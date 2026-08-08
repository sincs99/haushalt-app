import api from '../api/client'
import type { CalendarEvent, CalendarEventCreatePayload, CalendarEventUpdatePayload } from '../types'

export interface CalendarRepository {
  fetchByRange(householdId: string, fromDate: string, toDate: string): Promise<CalendarEvent[]>
  create(householdId: string, data: CalendarEventCreatePayload): Promise<CalendarEvent>
  update(householdId: string, eventId: string, data: CalendarEventUpdatePayload): Promise<CalendarEvent>
  remove(householdId: string, eventId: string): Promise<void>
}

export function createOnlineCalendarRepository(): CalendarRepository {
  return {
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
  }
}
