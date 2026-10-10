import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlinePetsRepository } from '../repositories/petsRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { localDateString } from '../utils/dates'
import type {
  Pet, PetCreatePayload, PetUpdatePayload, PetFeedingStatus, PetHistory, FeedingLog, FeedingSlot,
  HouseholdMemberInfo, Medication, MedicationCreatePayload, MedicationUpdatePayload, MedicationLog,
  PetCareTask, PetCareTaskCreatePayload, PetCareTaskUpdatePayload,
} from '../types'

/** Payload, in dem geleerte Felder als `null` gesendet werden (Backend löscht sie dann). */
export type Clearable<T> = { [K in keyof T]?: T[K] | null }

/** Ergebnis eines Fütterungs-Toggles. `duplicate` = jemand anderes hat schon gefüttert (409). */
export type FeedingToggleResult = 'fed' | 'unfed' | 'duplicate'

/** Ergebnis von „Alle gefüttert“: eigene Fütterungen + bestätigter Status nach dem Refetch. */
export interface FeedAllResult {
  created: FeedingLog[]
  allFed: boolean
  fed: number
  total: number
}

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
  let stateVersion = 0
  let requestVersion = 0
  const latestRequests = new Map<string, number>()

  function captureHousehold(householdId: string) {
    const version = stateVersion
    return () => version === stateVersion && useAuthStore().currentHouseholdId === householdId
  }

  function captureRequest(householdId: string, key: string) {
    const active = captureHousehold(householdId)
    const version = ++requestVersion
    latestRequests.set(key, version)
    return () => active() && latestRequests.get(key) === version
  }

  function upsertMedicationLog(log: MedicationLog) {
    const logs = medicationLogs.value[log.medication_id] ?? []
    medicationLogs.value[log.medication_id] = [log, ...logs.filter(item => item.id !== log.id)].slice(0, 10)
  }

  // Actions
  async function fetchPets() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'pets')

    loading.value = true
    try {
      const result = await repo.fetchAll(householdId)
      if (active()) pets.value = result
    } finally {
      if (active()) loading.value = false
    }
  }

  async function fetchFeedingStatus() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'feeding')

    try {
      const result = await repo.fetchFeedingStatus(householdId)
      if (active()) feedingStatus.value = result
    } catch {
      // Silently fail — feeding status is non-critical
    }
  }

  async function fetchMembers() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'members')

    const result = await householdRepo.fetchMembers(householdId)
    if (active()) members.value = result
  }

  async function createPet(payload: PetCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    const created = await repo.create(householdId, payload)
    if (!active()) return created
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

  async function updatePet(petId: string, payload: Clearable<PetUpdatePayload>, targetHouseholdId?: string) {
    const authStore = useAuthStore()
    const householdId = targetHouseholdId ?? authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    // null = Feld leeren (Backend: exclude_unset, null wird gespeichert)
    const updated = await repo.update(householdId, petId, payload as PetUpdatePayload)
    const idx = pets.value.findIndex(p => p.id === petId)
    if (active() && idx !== -1) {
      pets.value[idx] = updated
    }
    return updated
  }

  async function removePet(petId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

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
      if (active()) {
        if (removed && idx !== -1 && !pets.value.some(pet => pet.id === petId)) pets.value.splice(idx, 0, removed)
        await fetchFeedingStatus()
      }
      throw error
    }
  }

  /**
   * Tier archivieren (verstorben/abgegeben, PD-P2): Verlauf bleibt, das Tier fällt aus
   * Fütterung, Dashboard und Erinnerungen. Rückgängig über `unarchivePet`.
   */
  async function archivePet(petId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    const updated = await repo.archive(householdId, petId)
    if (active()) handlePetUpdated(updated)
    return updated
  }

  async function unarchivePet(petId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    const updated = await repo.unarchive(householdId, petId)
    if (active()) handlePetUpdated(updated)
    return updated
  }

  /** Umfang des Verlaufs (Fütterungen, Gaben, Pflegeaufgaben) für die Lösch-Warnung. */
  async function fetchPetHistory(petId: string): Promise<PetHistory | undefined> {
    const householdId = useAuthStore().currentHouseholdId
    if (!householdId) return
    return repo.fetchHistory(householdId, petId)
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

  /**
   * Alle Tiere für den Slot füttern. Liefert die neu angelegten Fütterungen (für Undo)
   * und — aus dem danach neu geladenen Status — ob wirklich alle Tiere gefüttert sind
   * (CASA-13: „Alle gefüttert“ nur melden, wenn der Server-Status das bestätigt).
   */
  async function feedAll(slot: FeedingSlot): Promise<FeedAllResult> {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return { created: [], allFed: false, fed: 0, total: 0 }
    const active = captureHousehold(householdId)

    let created: FeedingLog[] = []
    try {
      const result = await repo.feedAll(householdId, slot)
      created = Array.isArray(result) ? result : []
      // Eigene Fütterungen sofort übernehmen (falls der Status-Refetch scheitert)
      if (active()) created.forEach(handleFeedingCreated)
    } finally {
      // Server-Wahrheit (auch bei Fehler)
      await fetchFeedingStatus()
    }
    const fed = feedingStatus.value.filter(s => !!s[slot]).length
    const total = feedingStatus.value.length
    return { created, allFed: total > 0 && fed === total, fed, total }
  }

  /** Undo für „Alle gefüttert“: die eben angelegten Fütterungen wieder löschen. */
  async function undoFeedings(feedings: FeedingLog[]) {
    const householdId = feedings[0]?.household_id
    if (!householdId || feedings.some(f => f.household_id !== householdId)) return

    try {
      await Promise.all(feedings.map(f => repo.deleteFeeding(householdId, f.pet_id, f.id)))
    } finally {
      if (useAuthStore().currentHouseholdId === householdId) await fetchFeedingStatus()
    }
  }

  // ── Medication Actions ──

  async function fetchMedications(petId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'medications')

    // Tierwechsel: Daten des vorherigen Tiers nicht stehen lassen
    if (medicationsPetId.value !== petId) {
      medications.value = []
      medicationLogs.value = {}
    }
    medicationsPetId.value = petId
    const meds = await repo.fetchMedications(householdId, petId)
    // Antwort eines inzwischen verlassenen Tiers verwerfen
    if (active() && medicationsPetId.value === petId) medications.value = meds
  }

  async function createMedication(petId: string, payload: MedicationCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    const created = await repo.createMedication(householdId, petId, payload)
    if (!active() || (medicationsPetId.value && medicationsPetId.value !== petId)) return created
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
    const active = captureHousehold(householdId)

    const updated = await repo.updateMedication(householdId, petId, medicationId, payload as MedicationUpdatePayload)
    const idx = medications.value.findIndex(m => m.id === medicationId)
    if (active() && idx !== -1) {
      medications.value[idx] = updated
    }
    return updated
  }

  async function removeMedication(petId: string, medicationId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    await repo.removeMedication(householdId, petId, medicationId)
    if (!active()) return
    medications.value = medications.value.filter(m => m.id !== medicationId)
    delete medicationLogs.value[medicationId]
  }

  async function giveMedication(petId: string, medicationId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    // Client-ID: ein Retry derselben Gabe (Timeout, Doppel-Request) wird nicht doppelt gespeichert
    const log = await repo.giveMedication(householdId, petId, medicationId, crypto.randomUUID())
    if (active() && (!medicationsPetId.value || medicationsPetId.value === petId)) upsertMedicationLog(log)
    return log
  }

  async function fetchMedicationLog(petId: string, medicationId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, `logs:${medicationId}`)

    try {
      const logs = await repo.fetchMedicationLog(householdId, petId, medicationId)
      if (active() && (!medicationsPetId.value || medicationsPetId.value === petId)) {
        const combined = [...logs, ...(medicationLogs.value[medicationId] ?? [])]
        medicationLogs.value[medicationId] = combined.filter((log, index) => combined.findIndex(item => item.id === log.id) === index)
          .sort((a, b) => (b.given_at ?? '').localeCompare(a.given_at ?? '')).slice(0, 10)
      }
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
    const wasArchived = idx !== -1 ? pets.value[idx].archived : pet.archived
    if (idx !== -1) {
      pets.value[idx] = pet
    }
    // Archivierte Tiere haben keinen Fütterungsstatus mehr; reaktivierte brauchen ihn wieder
    if (pet.archived) feedingStatus.value = feedingStatus.value.filter(s => s.pet_id !== pet.id)
    else if (wasArchived) fetchFeedingStatus()
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
    if (medicationsPetId.value && !medications.value.some(med => med.id === log.medication_id)) return
    upsertMedicationLog(log)
  }

  // ── Care Task Actions ──

  async function fetchCareTasks(petId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'careTasks')

    if (careTasksPetId.value !== petId) careTasks.value = []
    careTasksPetId.value = petId
    const tasks = await repo.fetchCareTasks(householdId, petId)
    if (active() && careTasksPetId.value === petId) careTasks.value = tasks
  }

  async function createCareTask(petId: string, payload: PetCareTaskCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    const created = await repo.createCareTask(householdId, petId, payload)
    if (!active() || (careTasksPetId.value && careTasksPetId.value !== petId)) return created
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
    const active = captureHousehold(householdId)

    const updated = await repo.updateCareTask(householdId, petId, taskId, payload)
    const idx = careTasks.value.findIndex(t => t.id === taskId)
    if (active() && idx !== -1) {
      careTasks.value[idx] = updated
    }
    return updated
  }

  async function completeCareTask(petId: string, taskId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const inHousehold = captureHousehold(householdId)
    const active = () => inHousehold() && (!careTasksPetId.value || careTasksPetId.value === petId)

    const previous = careTasks.value.find(task => task.id === taskId)

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
    const optimistic = careTasks.value[idx]

    try {
      const updated = await repo.completeCareTask(householdId, petId, taskId)
      // Server-Wahrheit übernehmen
      const i = careTasks.value.findIndex(t => t.id === taskId)
      if (active() && i !== -1) careTasks.value[i] = updated
      return updated
    } catch (error) {
      const i = careTasks.value.findIndex(task => task.id === taskId)
      if (active() && i !== -1 && previous && careTasks.value[i] === optimistic) careTasks.value[i] = previous
      throw error
    }
  }

  async function removeCareTask(petId: string, taskId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const inHousehold = captureHousehold(householdId)
    const active = () => inHousehold() && (!careTasksPetId.value || careTasksPetId.value === petId)

    // Optimistic Delete
    const idx = careTasks.value.findIndex(task => task.id === taskId)
    const removed = careTasks.value[idx]
    careTasks.value = careTasks.value.filter(t => t.id !== taskId)

    try {
      await repo.removeCareTask(householdId, petId, taskId)
    } catch (error) {
      // Rollback
      if (active() && removed && !careTasks.value.some(task => task.id === taskId)) careTasks.value.splice(idx, 0, removed)
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
    stateVersion++
    latestRequests.clear()
    loading.value = false
    medicationsPetId.value = null
    careTasksPetId.value = null
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
    archivePet,
    unarchivePet,
    fetchPetHistory,
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
