import { scopeRepository, isScopeChanged, currentDataGeneration, assertDataGeneration } from '../services/sessionScope'
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineSensorsRepository } from '../repositories/sensorsRepository'
import type { SensorDevice, SensorReadingPoint } from '../types'
import { createRequestGuard } from '../utils/householdGuard'

export const useSensorsStore = defineStore('sensors', () => {
  const repo = scopeRepository(createOnlineSensorsRepository())

  const devices = ref<SensorDevice[]>([])
  const loading = ref(false)

  // Verspätete Antworten eines anderen Haushalts/einer alten Sitzung verwerfen (CASA-12)
  const captureRequest = createRequestGuard()

  async function fetchDevices() {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'devices')

    loading.value = true
    try {
      const result = await repo.fetchAll(householdId)
      if (active()) devices.value = result
    } finally {
      if (active.latest()) loading.value = false
    }
  }

  /** Verlauf eines Sensors; null, wenn die Antwort nicht mehr zum aktuellen Haushalt gehört. */
  async function fetchReadings(deviceId: string, hours: number): Promise<SensorReadingPoint[] | null> {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return null
    const active = captureRequest(householdId, `readings:${deviceId}`)
    const result = await repo.fetchReadings(householdId, deviceId, hours)
    return active() ? result : null
  }

  async function updateDevice(deviceId: string, data: { name?: string; room?: string | null }) {
    const actionGeneration = currentDataGeneration()
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return
    const saved = await repo.update(householdId, deviceId, data)
    assertDataGeneration(actionGeneration)
    handleSensorUpdated(saved)
  }

  async function deleteDevice(deviceId: string) {
    const actionGeneration = currentDataGeneration()
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return

    const index = devices.value.findIndex((d) => d.id === deviceId)
    if (index === -1) return
    const removed = devices.value[index]
    devices.value.splice(index, 1)

    try {
      await repo.remove(householdId, deviceId)
      assertDataGeneration(actionGeneration)
    } catch (error) {
      assertDataGeneration(actionGeneration)
      if (isScopeChanged(error)) throw error
      if (!devices.value.some((d) => d.id === deviceId)) devices.value.splice(index, 0, removed)
      throw error
    }
  }

  // Socket-Handler: Server gewinnt; ein neuer Sensor erscheint beim ersten Messwert
  function handleSensorUpdated(device: SensorDevice) {
    if (device.household_id !== useAuthStore().currentHouseholdId) return
    const index = devices.value.findIndex((d) => d.id === device.id)
    if (index !== -1) devices.value[index] = device
    else devices.value.push(device)
  }

  function handleSensorDeleted(data: { id: string }) {
    devices.value = devices.value.filter((d) => d.id !== data.id)
  }

  /** Haushaltswechsel: Daten gehören zum alten Haushalt. */
  function reset() {
    loading.value = false
    devices.value = []
  }

  return {
    reset,
    devices,
    loading,
    fetchDevices,
    fetchReadings,
    updateDevice,
    deleteDevice,
    handleSensorUpdated,
    handleSensorDeleted,
  }
})
