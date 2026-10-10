import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { captureHousehold as captureSharedHousehold } from '../utils/householdGuard'
import { createOnlinePlantsRepository } from '../repositories/plantsRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import { planAdvice, mergeCareNotes, selectPlan } from '../utils/plantCare'
import { localDateString } from '../utils/dates'
import type {
  AiPlantCareAdvice, Plant, PlantCreatePayload, PlantUpdatePayload, PlantCareStatus, PlantCareStatusTask,
  PlantCareTask, PlantCareTaskCreatePayload, PlantCareTaskUpdatePayload, PlantCareLog,
  HouseholdMemberInfo,
} from '../types'

const CARE_LOG_LIMIT = 50

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
  // Letztes Laden des Pflegestatus gescheitert (alter Status bleibt stehen)
  const careStatusError = ref(false)
  // Detailansicht: Pflegeaufgaben und Log der gerade geöffneten Pflanze
  const careTasks = ref<PlantCareTask[]>([])
  const careTasksPlantId = ref<string | null>(null)
  const careLog = ref<PlantCareLog[]>([])
  const careLogPlantId = ref<string | null>(null)

  // Mutex gegen Doppel-Taps auf "Erledigt"
  const pendingCompletions = new Set<string>()
  let stateVersion = 0
  let requestVersion = 0
  const latestRequests = new Map<string, number>()

  function captureHousehold(householdId: string) {
    const version = stateVersion
    // Gemeinsame Haushalts-/Sitzungs-Generation (Logout, Wechsel A → B → A; CASA-12)
    const inScope = captureSharedHousehold(householdId)
    return () => version === stateVersion && inScope()
  }

  function captureRequest(householdId: string, key: string) {
    const active = captureHousehold(householdId)
    const version = ++requestVersion
    latestRequests.set(key, version)
    return () => active() && latestRequests.get(key) === version
  }

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
    const active = captureRequest(householdId, 'plants')

    loading.value = true
    try {
      const result = await repo.fetchAll(householdId)
      if (active()) plants.value = result
    } finally {
      if (active()) loading.value = false
    }
  }

  async function fetchCareStatus() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'careStatus')

    try {
      const result = await repo.fetchCareStatus(householdId)
      if (active()) {
        careStatus.value = result
        careStatusError.value = false
      }
    } catch {
      // Kein Throw (viele Aufrufer, u. a. Socket-Events); bisheriger Status bleibt stehen,
      // die Ansicht zeigt über careStatusError einen Hinweis mit „Erneut versuchen“.
      if (active()) careStatusError.value = true
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

  async function createPlant(payload: PlantCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    const created = await repo.create(householdId, payload)
    if (!active()) return created
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

  async function updatePlant(plantId: string, payload: PlantUpdatePayload, targetHouseholdId?: string) {
    const authStore = useAuthStore()
    const householdId = targetHouseholdId ?? authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    const updated = await repo.update(householdId, plantId, payload)
    if (active()) handlePlantUpdated(updated)
    return updated
  }

  async function removePlant(plantId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    // Optimistic Delete
    const idx = plants.value.findIndex(p => p.id === plantId)
    const removed = idx !== -1 ? plants.value[idx] : null
    const statusIndex = careStatus.value.findIndex(item => item.plant_id === plantId)
    const removedStatus = careStatus.value[statusIndex]
    if (idx !== -1) plants.value.splice(idx, 1)
    careStatus.value = careStatus.value.filter(s => s.plant_id !== plantId)

    try {
      await repo.remove(householdId, plantId)
    } catch (error) {
      // Rollback
      if (active()) {
        if (removed && idx !== -1 && !plants.value.some(plant => plant.id === plantId)) plants.value.splice(idx, 0, removed)
        if (removedStatus && !careStatus.value.some(item => item.plant_id === plantId)) careStatus.value.splice(statusIndex, 0, removedStatus)
      }
      throw error
    }
  }

  // ── Care Task Actions ──

  async function fetchCareTasks(plantId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'careTasks')

    if (careTasksPlantId.value !== plantId) careTasks.value = []
    careTasksPlantId.value = plantId
    const tasks = await repo.fetchCareTasks(householdId, plantId)
    // Antwort einer inzwischen verlassenen Pflanze verwerfen
    if (active() && careTasksPlantId.value === plantId) careTasks.value = tasks
  }

  async function createCareTask(plantId: string, payload: PlantCareTaskCreatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    const created = await repo.createCareTask(householdId, plantId, payload)
    if (active()) {
      upsertCareTask(created)
      upsertStatusTask(created)
    }
    return created
  }

  async function updateCareTask(plantId: string, taskId: string, payload: PlantCareTaskUpdatePayload) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    const updated = await repo.updateCareTask(householdId, plantId, taskId, payload)
    if (active()) {
      upsertCareTask(updated)
      upsertStatusTask(updated)
    }
    return updated
  }

  /**
   * KERN-USECASE: Pflege erledigt (optimistic). Setzt Fälligkeit neu und schreibt einen Log-Eintrag.
   * Liefert den Log-Eintrag; `null` = heute schon erledigt, der Server hat nichts geändert (CASA-29).
   */
  async function completeCareTask(plantId: string, taskId: string, note?: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureHousehold(householdId)

    if (pendingCompletions.has(taskId)) return
    pendingCompletions.add(taskId)

    // Snapshots für Rollback
    const previousTask = careTasks.value.find(task => task.id === taskId)

    // Optimistic: nächste Fälligkeit sofort berechnen
    const today = localDateString()
    const existing = careTasks.value.find(t => t.id === taskId)
    const statusTask = careStatus.value
      .find(s => s.plant_id === plantId)?.tasks.find(t => t.task_id === taskId)
    const previousStatusTask = statusTask ? { ...statusTask } : null
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
    const optimisticTask = careTasks.value.find(task => task.id === taskId)

    try {
      const { task, log } = await repo.completeCareTask(householdId, plantId, taskId, note)
      // Server-Wahrheit übernehmen
      if (active()) {
        upsertCareTask(task)
        upsertStatusTask(task)
        if (log) prependLog(log)
      }
      return log ?? null
    } catch (error) {
      if (active()) {
        const current = careTasks.value.find(task => task.id === taskId)
        if (previousTask && current === optimisticTask) upsertCareTask(previousTask)
        const item = careStatus.value.find(item => item.plant_id === plantId)
        const currentStatus = item?.tasks.find(task => task.task_id === taskId)
        if (item && previousStatusTask && currentStatus === statusTask) {
          Object.assign(currentStatus!, previousStatusTask)
          refreshFlags(item)
        }
      }
      throw error
    } finally {
      pendingCompletions.delete(taskId)
    }
  }

  /** "Gegossen": erledigt alle Giessaufgaben der Pflanze. Liefert die neuen Log-Einträge. */
  async function waterPlant(plantId: string): Promise<PlantCareLog[]> {
    const item = careStatus.value.find(s => s.plant_id === plantId)
    const waterTasks = item?.tasks.filter(t => t.care_type === 'water') ?? []
    const logs = await Promise.all(waterTasks.map(t => completeCareTask(plantId, t.task_id)))
    return logs.filter((log): log is PlantCareLog => !!log)
  }

  /** "Alle fälligen giessen". */
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
   * `selected`: in der Vorschau angehakte Einträge (PD-P5, Schlüssel aus `adviceKey`);
   * ohne Angabe alle. Liefert die Anzahl angelegter und aktualisierter Aufgaben.
   */
  async function applyAdviceTasks(plantId: string, advice: AiPlantCareAdvice, selected?: string[] | null) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return { created: 0, updated: 0 }

    const existing = await repo.fetchCareTasks(householdId, plantId)
    const plan = selectPlan(planAdvice(advice, existing), selected)
    for (const task of plan.update) {
      await updateCareTask(plantId, task.id, { interval_days: task.interval_days })
    }
    for (const task of plan.create) {
      await createCareTask(plantId, { care_type: task.care_type, interval_days: task.interval_days })
    }
    return { created: plan.create.length, updated: plan.update.length }
  }

  /** Aufgaben + Pflegehinweise (angehängt) + Art (nur wenn leer) einer bestehenden Pflanze übernehmen. */
  async function applyCareAdvice(plant: Plant, advice: AiPlantCareAdvice, selected?: string[] | null) {
    const result = await applyAdviceTasks(plant.id, advice, selected)
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
    const active = captureHousehold(householdId)

    // Optimistic Delete
    const removed = careTasks.value.find(task => task.id === taskId)
    const removedStatus = careStatus.value.find(item => item.plant_id === plantId)?.tasks.find(task => task.task_id === taskId)
    careTasks.value = careTasks.value.filter(t => t.id !== taskId)
    removeStatusTask(taskId, plantId)

    try {
      await repo.removeCareTask(householdId, plantId, taskId)
    } catch (error) {
      if (active()) {
        if (removed && !careTasks.value.some(task => task.id === taskId)) upsertCareTask(removed)
        const item = careStatus.value.find(item => item.plant_id === plantId)
        if (item && removedStatus && !item.tasks.some(task => task.task_id === taskId)) {
          item.tasks.push(removedStatus)
          refreshFlags(item)
        }
      }
      throw error
    }
  }

  async function fetchCareLog(plantId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'careLog')

    if (careLogPlantId.value !== plantId) careLog.value = []
    careLogPlantId.value = plantId
    const log = await repo.fetchCareLog(householdId, plantId)
    if (active() && careLogPlantId.value === plantId) careLog.value = log.slice(0, CARE_LOG_LIMIT)
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
    stateVersion++
    latestRequests.clear()
    loading.value = false
    careStatusError.value = false
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
    careStatusError,
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
