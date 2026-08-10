import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlinePetsRepository } from '../repositories/petsRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type {
  Pet, PetCreatePayload, PetUpdatePayload, PetFeedingStatus, FeedingLog, FeedingSlot,
  HouseholdMemberInfo, Medication, MedicationCreatePayload, MedicationUpdatePayload, MedicationLog,
  PetCareTask, PetCareTaskCreatePayload, PetCareTaskUpdatePayload,
} from '../types'

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

  async function updatePet(petId: string, payload: PetUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.update(householdId, petId, payload)
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

  // KERN-USECASE: Toggle-Fütterung (optimistic)
  async function toggleFeeding(petId: string, slot: FeedingSlot) {
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
      } catch {
        statusItem[slot] = existing  // Rollback
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
        date: new Date().toISOString().slice(0, 10),
      }
      statusItem[slot] = tempFeeding
      try {
        const real = await repo.createFeeding(householdId, petId, slot)
        statusItem[slot] = real
      } catch (err: unknown) {
        statusItem[slot] = null  // Rollback
        // 409 = already fed → refetch
        const axiosErr = err as { response?: { status?: number } }
        if (axiosErr.response?.status === 409) await fetchFeedingStatus()
      } finally {
        pendingToggles.delete(key)
      }
    }
  }

  async function feedAll(slot: FeedingSlot) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    try {
      await repo.feedAll(householdId, slot)
      await fetchFeedingStatus()
    } catch {
      await fetchFeedingStatus()
    }
  }

  // ── Medication Actions ──

  async function fetchMedications(petId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    try {
      medications.value = await repo.fetchMedications(householdId, petId)
    } catch {
      // Silently fail
    }
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

  async function updateMedication(petId: string, medicationId: string, payload: MedicationUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.updateMedication(householdId, petId, medicationId, payload)
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

    try {
      careTasks.value = await repo.fetchCareTasks(householdId, petId)
    } catch {
      // Silently fail
    }
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
      const today = new Date().toISOString().slice(0, 10)
      const nextDue = new Date()
      nextDue.setDate(nextDue.getDate() + careTasks.value[idx].interval_days)
      careTasks.value[idx] = {
        ...careTasks.value[idx],
        last_done_at: today,
        next_due_at: nextDue.toISOString().slice(0, 10),
        notified_at: null,
      }
    }

    try {
      const updated = await repo.completeCareTask(householdId, petId, taskId)
      // Server-Wahrheit übernehmen
      const i = careTasks.value.findIndex(t => t.id === taskId)
      if (i !== -1) careTasks.value[i] = updated
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

  return {
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
