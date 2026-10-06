import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlinePlantsRepository } from '../repositories/plantsRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { planAdvice, mergeCareNotes } from '../utils/plantCare'
import type {
  AiPlantCareAdvice, Plant, PlantCreatePayload, PlantUpdatePayload, PlantCareStatus, PlantCareStatusTask,
  PlantCareTask, PlantCareTaskCreatePayload, PlantCareTaskUpdatePayload, PlantCareLog,
  HouseholdMemberInfo,
} from '../types'

const CARE_LOG_LIMIT = 50

/** Lokales Datum als "YYYY-MM-DD" (nicht UTC — sonst stimmt der Tag nachts nicht). */
function localDateString(date: Date = new Date()): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

function addDays(dateStr: string, days: number): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  return localDateString(new Date(y, m - 1, d + days))
}

function toStatusTask(task: PlantCareTask, today: string): PlantCareStatusTask {
  return {
    task_id: task.id,
    care_type: task.care_type,
    label: task.label,
    interval_days: task.interval_days,
    next_due_at: task.next_due_at,
    last_done_at: task.last_done_at,
    due_today: task.next_due_at === today,
    overdue: task.next_due_at < today,
  }
}

function refreshFlags(item: PlantCareStatus) {
  item.tasks.sort((a, b) => a.next_due_at.localeCompare(b.next_due_at))
  item.due_today = item.tasks.some(t => t.due_today)
  item.overdue = item.tasks.some(t => t.overdue)
}

export const usePlantsStore = defineStore('plants', () => {
  const repo = createOnlinePlantsRepository()
  const householdRepo = createOnlineHouseholdsRepository()

  // State
  const plants = ref<Plant[]>([])
  const careStatus = ref<PlantCareStatus[]>([])
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)
  // Detailansicht: Pflegeaufgaben und Log der gerade geöffneten Pflanze
  const careTasks = ref<PlantCareTask[]>([])
  const careTasksPlantId = ref<string | null>(null)
  const careLog = ref<PlantCareLog[]>([])
  const careLogPlantId = ref<string | null>(null)

  // Mutex gegen Doppel-Taps auf "Erledigt"
  const pendingCompletions = new Set<string>()

  // ── Helpers ──

  function upsertStatusTask(task: PlantCareTask) {
    const item = careStatus.value.find(s => s.plant_id === task.plant_id)
    if (!item) return
    const next = toStatusTask(task, localDateString())
    const idx = item.tasks.findIndex(t => t.task_id === task.id)
    if (idx !== -1) item.tasks[idx] = next
    else item.tasks.push(next)
    refreshFlags(item)
  }

  function removeStatusTask(taskId: string, plantId?: string) {
    for (const item of careStatus.value) {
      if (plantId && item.plant_id !== plantId) continue
      const before = item.tasks.length
      item.tasks = item.tasks.filter(t => t.task_id !== taskId)
      if (item.tasks.length !== before) refreshFlags(item)
    }
  }

  function upsertCareTask(task: PlantCareTask) {
    if (task.plant_id !== careTasksPlantId.value) return
    const idx = careTasks.value.findIndex(t => t.id === task.id)
    if (idx !== -1) careTasks.value[idx] = task
    else careTasks.value.push(task)
  }

  function prependLog(log: PlantCareLog) {
    if (log.plant_id !== careLogPlantId.value) return
    if (careLog.value.some(l => l.id === log.id)) return
    careLog.value = [log, ...careLog.value].slice(0, CARE_LOG_LIMIT)
  }

  // ── Plant Actions ──

  async function fetchPlants() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      plants.value = await repo.fetchAll(householdId)
    } finally {
      loading.value = false
    }
  }

  async function fetchCareStatus() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    try {
      careStatus.value = await repo.fetchCareStatus(householdId)
    } catch {
      // Silently fail — Status ist unkritisch
    }
  }

  async function fetchMembers() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    members.value = await householdRepo.fetchMembers(householdId)
  }

  async function createPlant(payload: PlantCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const created = await repo.create(householdId, payload)
    // Dedupe: falls Socket schneller war
    const idx = plants.value.findIndex(p => p.id === created.id)
    if (idx === -1) {
      plants.value.push(created)
      plants.value.sort((a, b) => a.name.localeCompare(b.name))
    } else {
      plants.value[idx] = created
    }
    await fetchCareStatus()
    return created
  }

  async function updatePlant(plantId: string, payload: PlantUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.update(householdId, plantId, payload)
    handlePlantUpdated(updated)
    return updated
  }

  async function removePlant(plantId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic Delete
    const idx = plants.value.findIndex(p => p.id === plantId)
    const removed = idx !== -1 ? plants.value[idx] : null
    const statusSnapshot = careStatus.value
    if (idx !== -1) plants.value.splice(idx, 1)
    careStatus.value = careStatus.value.filter(s => s.plant_id !== plantId)

    try {
      await repo.remove(householdId, plantId)
    } catch (error) {
      // Rollback
      if (removed && idx !== -1) plants.value.splice(idx, 0, removed)
      careStatus.value = statusSnapshot
      throw error
    }
  }

  // ── Care Task Actions ──

  async function fetchCareTasks(plantId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    if (careTasksPlantId.value !== plantId) careTasks.value = []
    careTasksPlantId.value = plantId
    try {
      const tasks = await repo.fetchCareTasks(householdId, plantId)
      // Antwort einer inzwischen verlassenen Pflanze verwerfen
      if (careTasksPlantId.value === plantId) careTasks.value = tasks
    } catch {
      // Silently fail
    }
  }

  async function createCareTask(plantId: string, payload: PlantCareTaskCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const created = await repo.createCareTask(householdId, plantId, payload)
    upsertCareTask(created)
    upsertStatusTask(created)
    return created
  }

  async function updateCareTask(plantId: string, taskId: string, payload: PlantCareTaskUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const updated = await repo.updateCareTask(householdId, plantId, taskId, payload)
    upsertCareTask(updated)
    upsertStatusTask(updated)
    return updated
  }

  /** KERN-USECASE: Pflege erledigt (optimistic). Setzt Fälligkeit neu und schreibt einen Log-Eintrag. */
  async function completeCareTask(plantId: string, taskId: string, note?: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    if (pendingCompletions.has(taskId)) return
    pendingCompletions.add(taskId)

    // Snapshots für Rollback
    const tasksSnapshot = careTasks.value.map(t => ({ ...t }))
    const statusSnapshot = careStatus.value.map(s => ({ ...s, tasks: s.tasks.map(t => ({ ...t })) }))

    // Optimistic: nächste Fälligkeit sofort berechnen
    const today = localDateString()
    const existing = careTasks.value.find(t => t.id === taskId)
    const statusTask = careStatus.value
      .find(s => s.plant_id === plantId)?.tasks.find(t => t.task_id === taskId)
    const intervalDays = existing?.interval_days ?? statusTask?.interval_days
    if (intervalDays !== undefined) {
      const nextDue = addDays(today, intervalDays)
      if (existing) {
        upsertCareTask({ ...existing, last_done_at: today, next_due_at: nextDue, notified_at: null })
      }
      if (statusTask) {
        statusTask.last_done_at = today
        statusTask.next_due_at = nextDue
        statusTask.due_today = false
        statusTask.overdue = false
        const item = careStatus.value.find(s => s.plant_id === plantId)
        if (item) refreshFlags(item)
      }
    }

    try {
      const { task, log } = await repo.completeCareTask(householdId, plantId, taskId, note)
      // Server-Wahrheit übernehmen
      upsertCareTask(task)
      upsertStatusTask(task)
      prependLog(log)
      return log
    } catch (error) {
      careTasks.value = tasksSnapshot
      careStatus.value = statusSnapshot
      throw error
    } finally {
      pendingCompletions.delete(taskId)
    }
  }

  /** "Gegossen": erledigt alle Gießaufgaben der Pflanze. */
  async function waterPlant(plantId: string) {
    const item = careStatus.value.find(s => s.plant_id === plantId)
    const waterTasks = item?.tasks.filter(t => t.care_type === 'water') ?? []
    await Promise.all(waterTasks.map(t => completeCareTask(plantId, t.task_id)))
  }

  /** "Alle fälligen gießen". */
  async function waterAll() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    try {
      const logs = await repo.waterAll(householdId)
      logs.forEach(prependLog)
      return logs
    } finally {
      // Server-Wahrheit (auch bei Fehler, falls teilweise geschrieben wurde)
      await fetchCareStatus()
    }
  }

  /**
   * KI-Vorschlag als Pflegeaufgaben übernehmen: gleiche Pflegeart wird aktualisiert,
   * fehlende angelegt. Liest die Aufgaben frisch vom Server (Fehler → Abbruch statt Duplikate).
   * Liefert die Anzahl angelegter und aktualisierter Aufgaben.
   */
  async function applyAdviceTasks(plantId: string, advice: AiPlantCareAdvice) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return { created: 0, updated: 0 }

    const existing = await repo.fetchCareTasks(householdId, plantId)
    const plan = planAdvice(advice, existing)
    for (const task of plan.update) {
      await updateCareTask(plantId, task.id, { interval_days: task.interval_days })
    }
    for (const task of plan.create) {
      await createCareTask(plantId, { care_type: task.care_type, interval_days: task.interval_days })
    }
    return { created: plan.create.length, updated: plan.update.length }
  }

  /** Aufgaben + Pflegehinweise (angehängt) + Art (nur wenn leer) einer bestehenden Pflanze übernehmen. */
  async function applyCareAdvice(plant: Plant, advice: AiPlantCareAdvice) {
    const result = await applyAdviceTasks(plant.id, advice)
    const payload: PlantUpdatePayload = {}
    const notes = mergeCareNotes(plant.care_notes, advice.care_notes)
    if (notes !== (plant.care_notes ?? '')) payload.care_notes = notes
    if (!plant.species?.trim() && advice.botanical_name) payload.species = advice.botanical_name.slice(0, 80)
    if (Object.keys(payload).length > 0) await updatePlant(plant.id, payload)
    return result
  }

  async function removeCareTask(plantId: string, taskId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // Optimistic Delete
    const tasksSnapshot = careTasks.value.map(t => ({ ...t }))
    const statusSnapshot = careStatus.value.map(s => ({ ...s, tasks: s.tasks.map(t => ({ ...t })) }))
    careTasks.value = careTasks.value.filter(t => t.id !== taskId)
    removeStatusTask(taskId, plantId)

    try {
      await repo.removeCareTask(householdId, plantId, taskId)
    } catch (error) {
      careTasks.value = tasksSnapshot
      careStatus.value = statusSnapshot
      throw error
    }
  }

  async function fetchCareLog(plantId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    if (careLogPlantId.value !== plantId) careLog.value = []
    careLogPlantId.value = plantId
    try {
      const log = await repo.fetchCareLog(householdId, plantId)
      if (careLogPlantId.value === plantId) careLog.value = log.slice(0, CARE_LOG_LIMIT)
    } catch {
      // Silently fail
    }
  }

  // ── Socket-Handler — Idempotent (Server gewinnt) ──

  function handlePlantCreated(plant: Plant) {
    const idx = plants.value.findIndex(p => p.id === plant.id)
    if (idx !== -1) {
      plants.value[idx] = plant
    } else {
      plants.value.push(plant)
      plants.value.sort((a, b) => a.name.localeCompare(b.name))
    }
  }

  function handlePlantUpdated(plant: Plant) {
    const idx = plants.value.findIndex(p => p.id === plant.id)
    if (idx !== -1) plants.value[idx] = plant
    const item = careStatus.value.find(s => s.plant_id === plant.id)
    if (item) {
      item.plant_name = plant.name
      item.species = plant.species
      item.location = plant.location
      item.photo_file_id = plant.photo_file_id
    }
  }

  function handlePlantDeleted(data: { id: string }) {
    plants.value = plants.value.filter(p => p.id !== data.id)
    careStatus.value = careStatus.value.filter(s => s.plant_id !== data.id)
    if (careTasksPlantId.value === data.id) careTasks.value = []
    if (careLogPlantId.value === data.id) careLog.value = []
  }

  function handleCareTaskCreated(task: PlantCareTask) {
    upsertCareTask(task)
    upsertStatusTask(task)
  }

  function handleCareTaskUpdated(task: PlantCareTask) {
    upsertCareTask(task)
    upsertStatusTask(task)
  }

  function handleCareTaskDeleted(data: { id: string; plant_id?: string }) {
    careTasks.value = careTasks.value.filter(t => t.id !== data.id)
    removeStatusTask(data.id, data.plant_id)
  }

  function handleCareLogged(log: PlantCareLog) {
    prependLog(log)
  }

  /** Haushaltswechsel: Daten gehören zum alten Haushalt. */
  function reset() {
    plants.value = []
    careStatus.value = []
    members.value = []
    careTasks.value = []
    careTasksPlantId.value = null
    careLog.value = []
    careLogPlantId.value = null
  }

  return {
    reset,
    // State
    plants,
    careStatus,
    members,
    loading,
    careTasks,
    careLog,
    // Actions
    fetchPlants,
    fetchCareStatus,
    fetchMembers,
    createPlant,
    updatePlant,
    removePlant,
    fetchCareTasks,
    createCareTask,
    updateCareTask,
    completeCareTask,
    waterPlant,
    waterAll,
    applyAdviceTasks,
    applyCareAdvice,
    removeCareTask,
    fetchCareLog,
    // Socket-Handlers
    handlePlantCreated,
    handlePlantUpdated,
    handlePlantDeleted,
    handleCareTaskCreated,
    handleCareTaskUpdated,
    handleCareTaskDeleted,
    handleCareLogged,
  }
})
