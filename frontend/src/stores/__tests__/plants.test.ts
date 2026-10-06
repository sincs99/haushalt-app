import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import type { Plant, PlantCareLog, PlantCareStatus, PlantCareTask } from '../../types'
import { deferred } from './helpers'

const { repo, householdRepo, auth } = vi.hoisted(() => ({
  repo: {
    fetchAll: vi.fn(),
    fetchOne: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    fetchCareStatus: vi.fn(),
    waterAll: vi.fn(),
    fetchCareTasks: vi.fn(),
    createCareTask: vi.fn(),
    updateCareTask: vi.fn(),
    completeCareTask: vi.fn(),
    removeCareTask: vi.fn(),
    fetchCareLog: vi.fn(),
  },
  householdRepo: { fetchMembers: vi.fn() },
  auth: { currentHouseholdId: 'h1' as string | null, user: { id: 'u1' } },
}))

vi.mock('../auth', () => ({ useAuthStore: () => auth }))
vi.mock('../../repositories/plantsRepository', () => ({
  createOnlinePlantsRepository: () => repo,
}))
vi.mock('../../repositories/householdsRepository', () => ({
  createOnlineHouseholdsRepository: () => householdRepo,
}))

import { usePlantsStore } from '../plants'

const TODAY = '2024-03-10'

function plant(over: Partial<Plant> = {}): Plant {
  return {
    id: 'p1',
    household_id: 'h1',
    name: 'Monstera',
    species: null,
    location: null,
    notes: null,
    care_notes: null,
    photo_file_id: null,
    created_at: '2024-01-01T00:00:00Z',
    ...over,
  }
}

function task(over: Partial<PlantCareTask> = {}): PlantCareTask {
  return {
    id: 't1',
    household_id: 'h1',
    plant_id: 'p1',
    care_type: 'water',
    label: null,
    interval_days: 7,
    next_due_at: '2024-03-08',
    last_done_at: null,
    notified_at: null,
    created_at: '2024-01-01T00:00:00Z',
    ...over,
  }
}

function log(over: Partial<PlantCareLog> = {}): PlantCareLog {
  return {
    id: 'l1',
    household_id: 'h1',
    plant_id: 'p1',
    care_task_id: 't1',
    care_type: 'water',
    label: null,
    done_at: '2024-03-10T08:00:00Z',
    done_by_user_id: 'u1',
    note: null,
    ...over,
  }
}

function status(over: Partial<PlantCareStatus> = {}): PlantCareStatus {
  return {
    plant_id: 'p1',
    plant_name: 'Monstera',
    species: null,
    location: null,
    photo_file_id: null,
    tasks: [{
      task_id: 't1', care_type: 'water', label: null, interval_days: 7,
      next_due_at: '2024-03-08', last_done_at: null, due_today: false, overdue: true,
    }],
    due_today: false,
    overdue: true,
    ...over,
  }
}

describe('plants store', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2024, 2, 10, 12, 0, 0)) // lokal 2024-03-10
    setActivePinia(createPinia())
    Object.values(repo).forEach(fn => fn.mockReset())
    householdRepo.fetchMembers.mockReset()
    auth.currentHouseholdId = 'h1'
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('fetchPlants loads data and resets loading, also on failure', async () => {
    repo.fetchAll.mockResolvedValueOnce([plant()])
    const s = usePlantsStore()
    await s.fetchPlants()
    expect(s.plants).toHaveLength(1)
    expect(repo.fetchAll).toHaveBeenCalledWith('h1')
    expect(s.loading).toBe(false)

    repo.fetchAll.mockRejectedValueOnce(new Error('x'))
    await expect(s.fetchPlants()).rejects.toThrow()
    expect(s.loading).toBe(false)
  })

  it('does nothing without a household', async () => {
    auth.currentHouseholdId = null
    const s = usePlantsStore()
    await s.fetchPlants()
    await s.fetchCareStatus()
    expect(repo.fetchAll).not.toHaveBeenCalled()
    expect(repo.fetchCareStatus).not.toHaveBeenCalled()
  })

  it('fetchCareStatus swallows errors', async () => {
    repo.fetchCareStatus.mockRejectedValue(new Error('x'))
    const s = usePlantsStore()
    await expect(s.fetchCareStatus()).resolves.toBeUndefined()
    expect(s.careStatus).toEqual([])
  })

  it('createPlant dedupes when the socket event was faster and refreshes status', async () => {
    const created = plant({ id: 'p2', name: 'Aloe' })
    repo.create.mockResolvedValue(created)
    repo.fetchCareStatus.mockResolvedValue([])
    const s = usePlantsStore()
    s.handlePlantCreated(created)
    await s.createPlant({ name: 'Aloe' })
    expect(s.plants).toHaveLength(1)
    expect(repo.fetchCareStatus).toHaveBeenCalledWith('h1')
  })

  it('keeps plants sorted by name on create', async () => {
    const s = usePlantsStore()
    s.handlePlantCreated(plant({ id: 'p1', name: 'Monstera' }))
    s.handlePlantCreated(plant({ id: 'p2', name: 'Aloe' }))
    expect(s.plants.map(p => p.name)).toEqual(['Aloe', 'Monstera'])
  })

  it('updatePlant replaces the plant and syncs the status entry', async () => {
    repo.update.mockResolvedValue(plant({ name: 'Monstera XL', location: 'Büro', photo_file_id: 'f1' }))
    const s = usePlantsStore()
    s.plants = [plant()]
    s.careStatus = [status()]
    await s.updatePlant('p1', { name: 'Monstera XL' })
    expect(s.plants[0].name).toBe('Monstera XL')
    expect(s.careStatus[0]).toMatchObject({ plant_name: 'Monstera XL', location: 'Büro', photo_file_id: 'f1' })
  })

  it('removePlant is optimistic and rolls back on failure', async () => {
    const d = deferred<void>()
    repo.remove.mockReturnValue(d.promise)
    const s = usePlantsStore()
    s.plants = [plant(), plant({ id: 'p2', name: 'Zamie' })]
    s.careStatus = [status(), status({ plant_id: 'p2' })]

    const p = s.removePlant('p1')
    expect(s.plants.map(x => x.id)).toEqual(['p2'])
    expect(s.careStatus.map(x => x.plant_id)).toEqual(['p2'])

    d.reject(new Error('fail'))
    await expect(p).rejects.toThrow('fail')
    expect(s.plants.map(x => x.id)).toEqual(['p1', 'p2'])
    expect(s.careStatus.map(x => x.plant_id)).toEqual(['p1', 'p2'])
  })

  it('completeCareTask updates optimistically using the local date, then takes the server truth', async () => {
    const d = deferred<{ task: PlantCareTask; log: PlantCareLog }>()
    repo.completeCareTask.mockReturnValue(d.promise)
    const s = usePlantsStore()
    repo.fetchCareTasks.mockResolvedValue([task()])
    await s.fetchCareTasks('p1')
    s.careStatus = [status()]

    const p = s.completeCareTask('p1', 't1', 'viel')
    expect(s.careTasks[0].next_due_at).toBe('2024-03-17')
    expect(s.careTasks[0].last_done_at).toBe(TODAY)
    expect(s.careStatus[0].tasks[0]).toMatchObject({ next_due_at: '2024-03-17', overdue: false, due_today: false })
    expect(s.careStatus[0].overdue).toBe(false)

    d.resolve({ task: task({ next_due_at: '2024-03-17', last_done_at: TODAY }), log: log() })
    await p
    expect(repo.completeCareTask).toHaveBeenCalledWith('h1', 'p1', 't1', 'viel')
    expect(s.careStatus[0].tasks[0].next_due_at).toBe('2024-03-17')
  })

  it('completeCareTask rolls back tasks and status on failure', async () => {
    repo.completeCareTask.mockRejectedValue(new Error('fail'))
    repo.fetchCareTasks.mockResolvedValue([task()])
    const s = usePlantsStore()
    await s.fetchCareTasks('p1')
    s.careStatus = [status()]

    await expect(s.completeCareTask('p1', 't1')).rejects.toThrow('fail')
    expect(s.careTasks[0].next_due_at).toBe('2024-03-08')
    expect(s.careStatus[0].tasks[0]).toMatchObject({ next_due_at: '2024-03-08', overdue: true })
    expect(s.careStatus[0].overdue).toBe(true)
  })

  it('completeCareTask ignores a second tap while the first is in flight', async () => {
    const d = deferred<{ task: PlantCareTask; log: PlantCareLog }>()
    repo.completeCareTask.mockReturnValue(d.promise)
    const s = usePlantsStore()
    s.careStatus = [status()]
    const first = s.completeCareTask('p1', 't1')
    await s.completeCareTask('p1', 't1')
    expect(repo.completeCareTask).toHaveBeenCalledTimes(1)
    d.resolve({ task: task({ next_due_at: '2024-03-17' }), log: log() })
    await first
    // danach wieder möglich
    repo.completeCareTask.mockResolvedValue({ task: task({ next_due_at: '2024-03-17' }), log: log({ id: 'l2' }) })
    await s.completeCareTask('p1', 't1')
    expect(repo.completeCareTask).toHaveBeenCalledTimes(2)
  })

  it('completeCareTask prepends the log for the open plant, deduping the socket echo', async () => {
    repo.fetchCareLog.mockResolvedValue([log({ id: 'old' })])
    repo.completeCareTask.mockResolvedValue({ task: task({ next_due_at: '2024-03-17' }), log: log({ id: 'new' }) })
    const s = usePlantsStore()
    await s.fetchCareLog('p1')
    s.careStatus = [status()]
    await s.completeCareTask('p1', 't1')
    s.handleCareLogged(log({ id: 'new' }))
    expect(s.careLog.map(l => l.id)).toEqual(['new', 'old'])
  })

  it('care log ignores entries of other plants and is capped', async () => {
    repo.fetchCareLog.mockResolvedValue([])
    const s = usePlantsStore()
    await s.fetchCareLog('p1')
    s.handleCareLogged(log({ id: 'x', plant_id: 'p2' }))
    expect(s.careLog).toEqual([])
    for (let i = 0; i < 60; i++) s.handleCareLogged(log({ id: `l${i}` }))
    expect(s.careLog).toHaveLength(50)
    expect(s.careLog[0].id).toBe('l59')
  })

  it('discards a late care-task response for a plant that is no longer open', async () => {
    const d = deferred<PlantCareTask[]>()
    repo.fetchCareTasks.mockReturnValueOnce(d.promise)
    repo.fetchCareTasks.mockResolvedValueOnce([task({ id: 't9', plant_id: 'p2' })])
    const s = usePlantsStore()
    const first = s.fetchCareTasks('p1')
    await s.fetchCareTasks('p2')
    d.resolve([task()])
    await first
    expect(s.careTasks.map(t => t.id)).toEqual(['t9'])
  })

  it('waterPlant completes every water task of the plant, not other care types', async () => {
    repo.completeCareTask.mockResolvedValue({ task: task({ next_due_at: '2024-03-17' }), log: log() })
    const s = usePlantsStore()
    s.careStatus = [status({
      tasks: [
        { task_id: 't1', care_type: 'water', label: null, interval_days: 7, next_due_at: '2024-03-08', last_done_at: null, due_today: false, overdue: true },
        { task_id: 't2', care_type: 'fertilize', label: null, interval_days: 30, next_due_at: '2024-03-08', last_done_at: null, due_today: false, overdue: true },
      ],
    })]
    await s.waterPlant('p1')
    expect(repo.completeCareTask).toHaveBeenCalledTimes(1)
    expect(repo.completeCareTask).toHaveBeenCalledWith('h1', 'p1', 't1', undefined)
  })

  it('waterAll refetches the status, also when the request fails', async () => {
    repo.waterAll.mockResolvedValueOnce([log()])
    repo.fetchCareStatus.mockResolvedValue([status({ overdue: false })])
    const s = usePlantsStore()
    await s.waterAll()
    expect(s.careStatus[0].overdue).toBe(false)

    repo.waterAll.mockRejectedValueOnce(new Error('fail'))
    await expect(s.waterAll()).rejects.toThrow('fail')
    expect(repo.fetchCareStatus).toHaveBeenCalledTimes(2)
  })

  it('createCareTask / updateCareTask keep tasks and status in sync', async () => {
    repo.fetchCareTasks.mockResolvedValue([])
    repo.createCareTask.mockResolvedValue(task({ id: 't2', care_type: 'fertilize', next_due_at: '2024-03-10' }))
    repo.updateCareTask.mockResolvedValue(task({ id: 't2', care_type: 'fertilize', next_due_at: '2024-04-01' }))
    const s = usePlantsStore()
    await s.fetchCareTasks('p1')
    s.careStatus = [status({ tasks: [], overdue: false })]

    await s.createCareTask('p1', { care_type: 'fertilize' })
    expect(s.careTasks.map(t => t.id)).toEqual(['t2'])
    expect(s.careStatus[0].tasks[0]).toMatchObject({ task_id: 't2', due_today: true, overdue: false })
    expect(s.careStatus[0].due_today).toBe(true)

    await s.updateCareTask('p1', 't2', { next_due_at: '2024-04-01' })
    expect(s.careStatus[0].tasks[0]).toMatchObject({ next_due_at: '2024-04-01', due_today: false })
    expect(s.careStatus[0].due_today).toBe(false)
  })

  it('removeCareTask is optimistic and rolls back on failure', async () => {
    repo.fetchCareTasks.mockResolvedValue([task()])
    repo.removeCareTask.mockRejectedValueOnce(new Error('fail'))
    const s = usePlantsStore()
    await s.fetchCareTasks('p1')
    s.careStatus = [status()]

    await expect(s.removeCareTask('p1', 't1')).rejects.toThrow('fail')
    expect(s.careTasks).toHaveLength(1)
    expect(s.careStatus[0].tasks).toHaveLength(1)

    repo.removeCareTask.mockResolvedValueOnce(undefined)
    await s.removeCareTask('p1', 't1')
    expect(s.careTasks).toHaveLength(0)
    expect(s.careStatus[0].tasks).toHaveLength(0)
    expect(s.careStatus[0].overdue).toBe(false)
  })

  it('socket handlers are idempotent and keep status flags in sync', async () => {
    repo.fetchCareTasks.mockResolvedValue([])
    const s = usePlantsStore()
    await s.fetchCareTasks('p1')
    s.careStatus = [status({ tasks: [], overdue: false })]

    const overdue = task({ id: 't5', next_due_at: '2024-03-01' })
    s.handleCareTaskCreated(overdue)
    s.handleCareTaskCreated(overdue)
    expect(s.careTasks).toHaveLength(1)
    expect(s.careStatus[0].tasks).toHaveLength(1)
    expect(s.careStatus[0].overdue).toBe(true)

    s.handleCareTaskUpdated(task({ id: 't5', next_due_at: '2024-03-17' }))
    expect(s.careStatus[0].overdue).toBe(false)

    s.handleCareTaskDeleted({ id: 't5', plant_id: 'p1' })
    expect(s.careTasks).toHaveLength(0)
    expect(s.careStatus[0].tasks).toHaveLength(0)
  })

  it('handlePlantDeleted clears plant, status and open detail data', async () => {
    repo.fetchCareTasks.mockResolvedValue([task()])
    repo.fetchCareLog.mockResolvedValue([log()])
    const s = usePlantsStore()
    s.plants = [plant()]
    s.careStatus = [status()]
    await s.fetchCareTasks('p1')
    await s.fetchCareLog('p1')

    s.handlePlantDeleted({ id: 'p1' })
    expect(s.plants).toEqual([])
    expect(s.careStatus).toEqual([])
    expect(s.careTasks).toEqual([])
    expect(s.careLog).toEqual([])
  })
})
