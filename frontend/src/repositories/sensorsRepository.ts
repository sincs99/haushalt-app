import api from '../api/client'
import { deleteIdempotent } from './http'
import type { SensorDevice, SensorReadingPoint } from '../types'
import type { WidgetTokenCreated, WidgetTokenStatus } from './widgetRepository'

/** Raumklima-Sensoren und ihr Verlauf (Backend: routers/sensors.py) */
export function createOnlineSensorsRepository() {
  const url = (householdId: string) => `/api/households/${householdId}/sensors`
  return {
    async fetchAll(householdId: string): Promise<SensorDevice[]> {
      const { data } = await api.get<SensorDevice[]>(url(householdId))
      return data
    },
    async update(
      householdId: string,
      deviceId: string,
      payload: { name?: string; room?: string | null },
    ): Promise<SensorDevice> {
      const { data } = await api.patch<SensorDevice>(`${url(householdId)}/${deviceId}`, payload)
      return data
    },
    async remove(householdId: string, deviceId: string): Promise<void> {
      await deleteIdempotent(`${url(householdId)}/${deviceId}`)
    },
    async fetchReadings(householdId: string, deviceId: string, hours: number): Promise<SensorReadingPoint[]> {
      const { data } = await api.get<SensorReadingPoint[]>(
        `${url(householdId)}/${deviceId}/readings`,
        { params: { hours } },
      )
      return data
    },
  }
}

/** Schreib-Schlüssel des Haushalts für die Sensor-Brücke; gleiche Form wie der Widget-Schlüssel */
export function createOnlineSensorKeyRepository() {
  const url = (householdId: string) => `/api/households/${householdId}/sensors/ingest-token`
  return {
    async fetchStatus(householdId: string): Promise<WidgetTokenStatus> {
      const { data } = await api.get<WidgetTokenStatus>(url(householdId))
      return data
    },
    async create(householdId: string): Promise<WidgetTokenCreated> {
      const { data } = await api.post<WidgetTokenCreated>(url(householdId))
      return data
    },
    async revoke(householdId: string): Promise<void> {
      await api.delete(url(householdId))
    },
  }
}
