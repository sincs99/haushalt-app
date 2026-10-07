import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlinePetsRepository } from '../repositories/petsRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { localDateString } from '../utils/dates'
import type {
  Pet, PetCreatePayload, PetUpdatePayload, PetFeedingStatus, FeedingLog, FeedingSlot,
  HouseholdMemberInfo, Medication, MedicationCreatePayload, MedicationUpdatePayload, MedicationLog,
  PetCareTask, PetCareTaskCreatePayload, PetCareTaskUpdatePayload,
} from '../types'

/** Payload, in dem geleerte Felder als `null` gesendet werden (Backend löscht sie dann). */
export type Clearable<T> = { [K in keyof T]?: T[K] | null }

/** Ergebnis eines Fütterungs-Toggles. `duplicate` = jemand anderes hat schon gefüttert (409). */
export type FeedingToggleResult = 'fed' | 'unfed' | 'duplicate'

function isFeedingDuplicate(err: unknown): boolean {
  const e = err as { response?: { status?: number; data?: { detail?: { code?: string } } } }
  return e?.response?.status === 409 || e?.response?.data?.detail?.code === 'FEEDING_DUPLICATE'
}

function addDays(dateStr: string, days: number): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  return localDateString(new Date(y, m - 1, d + days))
}

export const usePetsStore = defineStore('pets', () => {
  const repo = createOnlinePetsRepository()
  const householdRepo = createOnlineHouseholdsRepository()

  // State
  const pets = ref<Pet[]>([])
  const feedingStatus = ref<PetFeedingStatus[]>([])
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)
  const medications = ref<Medication[]>([])
  const medicationLogs = ref<Record<string, MedicationLog[]>>({})  // medication_id → logs
  const careTasks = ref<PetCareTask[]>([])
  // Für welches Tier Medikamente/Pflegeaufgaben geladen sind (Tierwechsel → Listen leeren)
  const medicationsPetId = ref<string | null>(null)
  const careTasksPetId = ref<string | null>(null)

  // Mutex für Toggle-Operationen
  const pendingToggles = new Set<string>()

  // Actions
  async function fetchPets() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      pets.value = await repo.fetchAll(householdId)
    } finally {
      loading.value = false
    }
  }

  async function fetchFeedingStatus() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    try {
      feedingStatus.value = await repo.fetchFeedingStatus(householdId)
    } catch {
      // Silently fail — feeding status is non-critical
    }
  }

  async function fetchMembers() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    members.value = await householdRepo.fetchMembers(householdId)
  }

  async function createPet(payload: PetCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const created = await repo.create(householdId, payload)
    // Dedupe: falls Socket schneller war
    const idx = pets.value.findIndex(p => p.id === created.id)
    if (idx === -1) {
      pets.value.push(created)
    } else {
      pets.value[idx] = created
    }
    // Feeding-Status neu laden (neues Pet hat leeren Status)
    await fetchFeedingStatus()
    return created
  }

  async function updatePet(petId: string, payload: Clearable<PetUpdatePayload>) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // null = Feld leeren (Backend: exclude_unset, null wird gespeichert)
    const updated = await repo.update(householdId, petId, payload as PetUpdatePayload)
    const idx = pets.value.findIndex(p => p.id === petId)
    if (idx !== -1) {
      pets.value[idx] = updated
    }
    return updated
  }

  async function removePet(petId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic Delete
    const idx = pets.value.findIndex(p => p.id === petId)
    const removed = idx !== -1 ? pets.value[idx] : null
    if (idx !== -1) pets.value.splice(idx, 1)
    // Auch FeedingStatus entfernen
    feedingStatus.value = feedingStatus.value.filter(s => s.pet_id !== petId)

    try {
      await repo.remove(householdId, petId)
    } catch (error) {
      // Rollback
      if (removed && idx !== -1) pets.value.splice(idx, 0, removed)
      await fetchFeedingStatus()
      throw error
    }
  }

  /**
   * KERN-USECASE: Toggle-Fütterung (optimistic).
   * Fehler werden nach dem Rollback weitergereicht; 409 (schon gefüttert) lädt den
   * Status neu und liefert `duplicate`. `undefined` = nichts passiert (Mutex/unbekannt).
   */
  async function toggleFeeding(petId: string, slot: FeedingSlot): Promise<FeedingToggleResult | undefined> {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const key = `${petId}-${slot}`
    if (pendingToggles.has(key)) return
    pendingToggles.add(key)

    const statusItem = feedingStatus.value.find(s => s.pet_id === petId)
    if (!statusItem) { pendingToggles.delete(key); return }

    const existing = statusItem[slot]

    if (existing) {
      // Undo: DELETE feeding
      statusItem[slot] = null
      try {
        await repo.deleteFeeding(householdId, petId, existing.id)
        return 'unfed'
      } catch (err) {
        statusItem[slot] = existing  // Rollback
        throw err
      } finally {
        pendingToggles.delete(key)
      }
    } else {
      // Create feeding
      const tempFeeding: FeedingLog = {
        id: 'temp',
        household_id: householdId,
        pet_id: petId,
        slot,
        fed_at: new Date().toISOString(),
        fed_by_user_id: authStore.user?.id ?? '',
        date: localDateString(),
      }
      statusItem[slot] = tempFeeding
      try {
        const real = await repo.createFeeding(householdId, petId, slot)
        statusItem[slot] = real
        return 'fed'
      } catch (err: unknown) {
        statusItem[slot] = null  // Rollback
        // 409 = schon gefüttert → Server-Status holen, kein Fehler
        if (isFeedingDuplicate(err)) {
          await fetchFeedingStatus()
          return 'duplicate'
        }
        throw err
      } finally {
        pendingToggles.delete(key)
      }
    }
  }

  /** Alle Tiere für den Slot füttern. Liefert die neu angelegten Fütterungen (für Undo). */
  async function feedAll(slot: FeedingSlot): Promise<FeedingLog[]> {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return []

    try {
      const created = await repo.feedAll(householdId, slot)
      return Array.isArray(created) ? created : []
    } finally {
      // Server-Wahrheit (auch bei Fehler)
      await fetchFeedingStatus()
    }
  }

  /** Undo für „Alle gefüttert“: die eben angelegten Fütterungen wieder löschen. */
  async function undoFeedings(feedings: FeedingLog[]) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    try {
      await Promise.all(feedings.map(f => repo.deleteFeeding(householdId, f.pet_id, f.id)))
    } finally {
      await fetchFeedingStatus()
    }
  }

  // ── Medication Actions ──

  async function fetchMedications(petId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Tierwechsel: Daten des vorherigen Tiers nicht stehen lassen
    if (medicationsPetId.value !== petId) {
      medications.value = []
      medicationLogs.value = {}
    }
    medicationsPetId.value = petId
    const meds = await repo.fetchMedications(householdId, petId)
    // Antwort eines inzwischen verlassenen Tiers verwerfen
    if (medicationsPetId.value === petId) medications.value = meds
  }

  async function createMedication(petId: string, payload: MedicationCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const created = await repo.createMedication(householdId, petId, payload)
    const idx = medications.value.findIndex(m => m.id === created.id)
    if (idx === -1) {
      medications.value.push(created)
    } else {
      medications.value[idx] = created
    }
    return created
  }

  async function updateMedication(petId: string, medicationId: string, payload: Clearable<MedicationUpdatePayload>) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.updateMedication(householdId, petId, medicationId, payload as MedicationUpdatePayload)
    const idx = medications.value.findIndex(m => m.id === medicationId)
    if (idx !== -1) {
      medications.value[idx] = updated
    }
    return updated
  }

  async function removeMedication(petId: string, medicationId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    await repo.removeMedication(householdId, petId, medicationId)
    medications.value = medications.value.filter(m => m.id !== medicationId)
    delete medicationLogs.value[medicationId]
  }

  async function giveMedication(petId: string, medicationId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const log = await repo.giveMedication(householdId, petId, medicationId)
    const logs = medicationLogs.value[medicationId] ?? []
    medicationLogs.value[medicationId] = [log, ...logs].slice(0, 10)
    return log
  }

  async function fetchMedicationLog(petId: string, medicationId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    try {
      const logs = await repo.fetchMedicationLog(householdId, petId, medicationId)
      medicationLogs.value[medicationId] = logs.slice(0, 10)
    } catch {
      // Silently fail
    }
  }

  // Socket-Handler — Idempotent (Server gewinnt)
  function handlePetCreated(pet: Pet) {
    const idx = pets.value.findIndex(p => p.id === pet.id)
    if (idx !== -1) {
      pets.value[idx] = pet
    } else {
      pets.value.push(pet)
    }
  }

  function handlePetUpdated(pet: Pet) {
    const idx = pets.value.findIndex(p => p.id === pet.id)
    if (idx !== -1) {
      pets.value[idx] = pet
    }
  }

  function handlePetDeleted(data: { id: string }) {
    pets.value = pets.value.filter(p => p.id !== data.id)
    feedingStatus.value = feedingStatus.value.filter(s => s.pet_id !== data.id)
  }

  function handleFeedingCreated(feeding: FeedingLog) {
    const statusItem = feedingStatus.value.find(s => s.pet_id === feeding.pet_id)
    if (statusItem) {
      statusItem[feeding.slot as 'morning' | 'evening'] = feeding
    }
  }

  function handleFeedingDeleted(data: { id: string; pet_id: string }) {
    const statusItem = feedingStatus.value.find(s => s.pet_id === data.pet_id)
    if (statusItem) {
      if (statusItem.morning?.id === data.id) statusItem.morning = null
      if (statusItem.evening?.id === data.id) statusItem.evening = null
    }
  }

  // ── Medication Socket-Handler ──

  function handleMedicationCreated(med: Medication) {
    // Nur Medikamente des geöffneten Tiers übernehmen
    if (med.pet_id !== medicationsPetId.value) return
    const idx = medications.value.findIndex(m => m.id === med.id)
    if (idx !== -1) medications.value[idx] = med
    else medications.value.push(med)
  }

  function handleMedicationUpdated(med: Medication) {
    const idx = medications.value.findIndex(m => m.id === med.id)
    if (idx !== -1) medications.value[idx] = med
  }

  function handleMedicationDeleted(data: { id: string }) {
    medications.value = medications.value.filter(m => m.id !== data.id)
    delete medicationLogs.value[data.id]
  }

  function handleMedicationGiven(log: MedicationLog) {
    const logs = medicationLogs.value[log.medication_id] ?? []
    medicationLogs.value[log.medication_id] = [log, ...logs].slice(0, 10)
  }

  // ── Care Task Actions ──

  async function fetchCareTasks(petId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    if (careTasksPetId.value !== petId) careTasks.value = []
    careTasksPetId.value = petId
    const tasks = await repo.fetchCareTasks(householdId, petId)
    if (careTasksPetId.value === petId) careTasks.value = tasks
  }

  async function createCareTask(petId: string, payload: PetCareTaskCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const created = await repo.createCareTask(householdId, petId, payload)
    const idx = careTasks.value.findIndex(t => t.id === created.id)
    if (idx === -1) {
      careTasks.value.push(created)
    } else {
      careTasks.value[idx] = created
    }
    return created
  }

  async function updateCareTask(petId: string, taskId: string, payload: PetCareTaskUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.updateCareTask(householdId, petId, taskId, payload)
    const idx = careTasks.value.findIndex(t => t.id === taskId)
    if (idx !== -1) {
      careTasks.value[idx] = updated
    }
    return updated
  }

  async function completeCareTask(petId: string, taskId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Vollständiger Snapshot für Rollback
    const snapshot = careTasks.value.map(t => ({ ...t }))

    // Optimistic: Datum sofort berechnen
    const idx = careTasks.value.findIndex(t => t.id === taskId)
    if (idx !== -1) {
      const today = localDateString()
      careTasks.value[idx] = {
        ...careTasks.value[idx],
        last_done_at: today,
        next_due_at: addDays(today, careTasks.value[idx].interval_days),
        notified_at: null,
      }
    }

    try {
      const updated = await repo.completeCareTask(householdId, petId, taskId)
      // Server-Wahrheit übernehmen
      const i = careTasks.value.findIndex(t => t.id === taskId)
      if (i !== -1) careTasks.value[i] = updated
      return updated
    } catch (error) {
      // Vollständiger Rollback
      careTasks.value = snapshot
      throw error
    }
  }

  async function removeCareTask(petId: string, taskId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic Delete
    const snapshot = careTasks.value.map(t => ({ ...t }))
    careTasks.value = careTasks.value.filter(t => t.id !== taskId)

    try {
      await repo.removeCareTask(householdId, petId, taskId)
    } catch (error) {
      // Rollback
      careTasks.value = snapshot
      throw error
    }
  }

  // ── Care Task Socket-Handler ──

  function handleCareTaskCreated(task: PetCareTask) {
    // Nur Aufgaben des geöffneten Tiers übernehmen
    if (task.pet_id !== careTasksPetId.value) return
    const idx = careTasks.value.findIndex(t => t.id === task.id)
    if (idx !== -1) careTasks.value[idx] = task
    else careTasks.value.push(task)
  }

  function handleCareTaskUpdated(task: PetCareTask) {
    const idx = careTasks.value.findIndex(t => t.id === task.id)
    if (idx !== -1) careTasks.value[idx] = task
  }

  function handleCareTaskDeleted(data: { id: string }) {
    careTasks.value = careTasks.value.filter(t => t.id !== data.id)
  }

  /** Haushaltswechsel: Daten gehören zum alten Haushalt. */
  function reset() {
    pets.value = []
    feedingStatus.value = []
    members.value = []
    medications.value = []
    medicationLogs.value = {}
    careTasks.value = []
  }

  return {
    reset,
    // State
    pets,
    feedingStatus,
    members,
    loading,
    medications,
    medicationLogs,
    careTasks,
    // Actions
    fetchPets,
    fetchFeedingStatus,
    fetchMembers,
    createPet,
    updatePet,
    removePet,
    toggleFeeding,
    feedAll,
    undoFeedings,
    fetchMedications,
    createMedication,
    updateMedication,
    removeMedication,
    giveMedication,
    fetchMedicationLog,
    fetchCareTasks,
    createCareTask,
    updateCareTask,
    completeCareTask,
    removeCareTask,
    // Socket-Handlers
    handlePetCreated,
    handlePetUpdated,
    handlePetDeleted,
    handleFeedingCreated,
    handleFeedingDeleted,
    handleMedicationCreated,
    handleMedicationUpdated,
    handleMedicationDeleted,
    handleMedicationGiven,
    handleCareTaskCreated,
    handleCareTaskUpdated,
    handleCareTaskDeleted,
  }
})
