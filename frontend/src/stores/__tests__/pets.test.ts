/**
 * Unit-Tests für den Pets-Store: Pets, Fütterungs-Toggle (Optimistic + Mutex + Rollback),
 * Medikation, Pflegeaufgaben und Socket-Handler.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { deferred, HOUSEHOLD_ID, USER_ID } from './helpers'

const { repo, householdRepo, auth } = vi.hoisted(() => ({
  repo: {
    fetchAll: vi.fn(), fetchFeedingStatus: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn(),
    archive: vi.fn(), unarchive: vi.fn(), fetchHistory: vi.fn(),
    createFeeding: vi.fn(), deleteFeeding: vi.fn(), feedAll: vi.fn(),
    fetchMedications: vi.fn(), createMedication: vi.fn(), updateMedication: vi.fn(),
    removeMedication: vi.fn(), giveMedication: vi.fn(), fetchMedicationLog: vi.fn(),
    fetchCareTasks: vi.fn(), createCareTask: vi.fn(), updateCareTask: vi.fn(),
    completeCareTask: vi.fn(), removeCareTask: vi.fn(),
  },
  householdRepo: { fetchMembers: vi.fn() },
  auth: { currentHouseholdId: null as string | null, user: null as { id: string } | null },
}))

vi.mock('../../repositories/petsRepository', () => ({ createOnlinePetsRepository: () => repo }))
vi.mock('../../repositories/householdsRepository', () => ({ createOnlineHouseholdsRepository: () => householdRepo }))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { usePetsStore } from '../pets'

const pet = (id = 'p1', o: Record<string, unknown> = {}) => ({ id, name: 'Bello', ...o }) as any
const feeding = (id: string, slot = 'morning', petId = 'p1') => ({ id, household_id: HOUSEHOLD_ID, pet_id: petId, slot }) as any
const status = (petId = 'p1', o: Record<string, unknown> = {}) => ({ pet_id: petId, morning: null, evening: null, ...o }) as any
const med = (id = 'm1', o: Record<string, unknown> = {}) => ({ id, pet_id: 'p1', name: 'Pille', ...o }) as any
const task = (id = 't1', o: Record<string, unknown> = {}) => ({
  id, pet_id: 'p1', interval_days: 7, last_done_at: null, next_due_at: '2026-01-01', notified_at: 'x', ...o,
}) as any
const axios409 = { response: { status: 409, data: { detail: { code: 'FEEDING_DUPLICATE' } } } }

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  auth.currentHouseholdId = HOUSEHOLD_ID
  auth.user = { id: USER_ID }
})

describe('Pets', () => {
  test('fetchPets lädt und setzt loading zurück (auch bei Fehler)', async () => {
    const store = usePetsStore()
    repo.fetchAll.mockResolvedValue([pet()])
    await store.fetchPets()
    expect(store.pets).toHaveLength(1)
    repo.fetchAll.mockRejectedValue(new Error('x'))
    await expect(store.fetchPets()).rejects.toThrow('x')
    expect(store.loading).toBe(false)
  })

  test('fetchFeedingStatus schluckt Fehler; fetchMembers lädt', async () => {
    const store = usePetsStore()
    store.feedingStatus = [status()]
    repo.fetchFeedingStatus.mockRejectedValue(new Error('x'))
    await store.fetchFeedingStatus()
    expect(store.feedingStatus).toHaveLength(1)
    householdRepo.fetchMembers.mockResolvedValue([{ user_id: 'u' }])
    await store.fetchMembers()
    expect(store.members).toHaveLength(1)
  })

  test('createPet dedupliziert gegen Socket und lädt Feeding-Status nach', async () => {
    const store = usePetsStore()
    store.handlePetCreated(pet('new'))
    repo.create.mockResolvedValue(pet('new', { name: 'Final' }))
    repo.fetchFeedingStatus.mockResolvedValue([status('new')])
    await store.createPet({} as any)
    expect(store.pets).toHaveLength(1)
    expect(store.pets[0].name).toBe('Final')
    expect(store.feedingStatus).toHaveLength(1)
  })

  test('updatePet ersetzt das Pet', async () => {
    const store = usePetsStore()
    store.pets = [pet()]
    repo.update.mockResolvedValue(pet('p1', { name: 'Neu' }))
    await store.updatePet('p1', { name: 'Neu' } as any)
    expect(store.pets[0].name).toBe('Neu')
  })

  test('removePet: optimistisch inkl. Feeding-Status, Rollback + Status-Refetch bei Fehler', async () => {
    const store = usePetsStore()
    store.pets = [pet('a'), pet('b')]
    store.feedingStatus = [status('a'), status('b')]
    repo.remove.mockRejectedValue(new Error('x'))
    repo.fetchFeedingStatus.mockResolvedValue([status('a'), status('b')])
    const p = store.removePet('a')
    expect(store.pets.map(x => x.id)).toEqual(['b'])
    expect(store.feedingStatus.map(x => x.pet_id)).toEqual(['b'])
    await expect(p).rejects.toThrow('x')
    expect(store.pets.map(x => x.id)).toEqual(['a', 'b'])
    expect(store.feedingStatus).toHaveLength(2)
  })
})

describe('Archiv (PD-P2)', () => {
  test('archivePet entfernt das Tier aus dem Fütterungsstatus, unarchivePet lädt ihn neu', async () => {
    const store = usePetsStore()
    store.pets = [pet('p1', { archived: false }), pet('p2', { archived: false })]
    store.feedingStatus = [status('p1'), status('p2')]
    repo.archive.mockResolvedValue(pet('p1', { archived: true }))
    await store.archivePet('p1')
    expect(store.pets[0].archived).toBe(true)
    expect(store.feedingStatus.map(s => s.pet_id)).toEqual(['p2'])

    repo.unarchive.mockResolvedValue(pet('p1', { archived: false }))
    repo.fetchFeedingStatus.mockResolvedValue([status('p1'), status('p2')])
    await store.unarchivePet('p1')
    await vi.waitFor(() => expect(store.feedingStatus).toHaveLength(2))
    expect(store.pets[0].archived).toBe(false)
  })

  test('Socket pet_updated mit archived=true entfernt den Fütterungsstatus', () => {
    const store = usePetsStore()
    store.pets = [pet('p1', { archived: false })]
    store.feedingStatus = [status('p1')]
    store.handlePetUpdated(pet('p1', { archived: true }))
    expect(store.feedingStatus).toEqual([])
    expect(repo.fetchFeedingStatus).not.toHaveBeenCalled()
  })

  test('fetchPetHistory liefert die Zahlen für die Lösch-Warnung', async () => {
    const store = usePetsStore()
    const history = { feedings: 3, medications: 1, medication_logs: 2, care_tasks: 0 }
    repo.fetchHistory.mockResolvedValue(history)
    await expect(store.fetchPetHistory('p1')).resolves.toEqual(history)
    expect(repo.fetchHistory).toHaveBeenCalledWith(HOUSEHOLD_ID, 'p1')
  })
})

describe('toggleFeeding', () => {
  test('Füttern: Temp sofort, danach Server-Log', async () => {
    const store = usePetsStore()
    store.feedingStatus = [status()]
    const pending = deferred<any>()
    repo.createFeeding.mockReturnValue(pending.promise)
    const p = store.toggleFeeding('p1', 'morning')
    expect(store.feedingStatus[0].morning).toMatchObject({ id: 'temp', fed_by_user_id: USER_ID })
    pending.resolve(feeding('real'))
    await p
    expect(store.feedingStatus[0].morning?.id).toBe('real')
  })

  test('Füttern: Rollback + Fehler weiterreichen; bei 409 Status neu laden und „duplicate“', async () => {
    const store = usePetsStore()
    store.feedingStatus = [status()]
    repo.createFeeding.mockRejectedValue(new Error('500'))
    await expect(store.toggleFeeding('p1', 'morning')).rejects.toThrow('500')
    expect(store.feedingStatus[0].morning).toBeNull()
    expect(repo.fetchFeedingStatus).not.toHaveBeenCalled()

    repo.createFeeding.mockRejectedValue(axios409)
    repo.fetchFeedingStatus.mockResolvedValue([status('p1', { morning: feeding('srv') })])
    await expect(store.toggleFeeding('p1', 'morning')).resolves.toBe('duplicate')
    expect(store.feedingStatus[0].morning?.id).toBe('srv')
  })

  test('Füttern liefert „fed“, Entfernen „unfed“; Datum ist lokal', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2024, 2, 10, 0, 30, 0)) // lokal kurz nach Mitternacht
    try {
      const store = usePetsStore()
      store.feedingStatus = [status()]
      const pending = deferred<any>()
      repo.createFeeding.mockReturnValue(pending.promise)
      const p = store.toggleFeeding('p1', 'morning')
      expect(store.feedingStatus[0].morning?.date).toBe('2024-03-10')
      pending.resolve(feeding('real'))
      await expect(p).resolves.toBe('fed')
      repo.deleteFeeding.mockResolvedValue(undefined)
      await expect(store.toggleFeeding('p1', 'morning')).resolves.toBe('unfed')
    } finally {
      vi.useRealTimers()
    }
  })

  test('Rückgängig: sofort entfernt, Rollback bei Fehler', async () => {
    const store = usePetsStore()
    const f = feeding('f1')
    store.feedingStatus = [status('p1', { morning: f })]
    repo.deleteFeeding.mockRejectedValue(new Error('x'))
    const p = store.toggleFeeding('p1', 'morning')
    expect(store.feedingStatus[0].morning).toBeNull()
    await expect(p).rejects.toThrow('x')
    expect(store.feedingStatus[0].morning).toEqual(f)
    repo.deleteFeeding.mockResolvedValue(undefined)
    await store.toggleFeeding('p1', 'morning')
    expect(repo.deleteFeeding).toHaveBeenLastCalledWith(HOUSEHOLD_ID, 'p1', 'f1')
    expect(store.feedingStatus[0].morning).toBeNull()
  })

  test('Mutex: zweiter Klick während Request wird ignoriert; Slot danach wieder frei', async () => {
    const store = usePetsStore()
    store.feedingStatus = [status()]
    const pending = deferred<any>()
    repo.createFeeding.mockReturnValue(pending.promise)
    const p1 = store.toggleFeeding('p1', 'morning')
    await store.toggleFeeding('p1', 'morning')
    expect(repo.createFeeding).toHaveBeenCalledTimes(1)
    pending.resolve(feeding('real'))
    await p1
    repo.deleteFeeding.mockResolvedValue(undefined)
    await store.toggleFeeding('p1', 'morning')
    expect(repo.deleteFeeding).toHaveBeenCalledTimes(1)
  })

  test('unbekanntes Pet gibt den Mutex wieder frei', async () => {
    const store = usePetsStore()
    await store.toggleFeeding('ghost', 'morning')
    store.feedingStatus = [status('ghost')]
    repo.createFeeding.mockResolvedValue(feeding('r', 'morning', 'ghost'))
    await store.toggleFeeding('ghost', 'morning')
    expect(repo.createFeeding).toHaveBeenCalledTimes(1)
  })

  test('feedAll lädt den Status danach neu — auch bei Fehler, und reicht den Fehler weiter', async () => {
    const store = usePetsStore()
    repo.feedAll.mockResolvedValue([feeding('f1')])
    repo.fetchFeedingStatus.mockResolvedValue([status('p1', { morning: feeding('f1') })])
    await expect(store.feedAll('morning')).resolves.toEqual({ created: [feeding('f1')], allFed: true, fed: 1, total: 1 })
    repo.feedAll.mockRejectedValue(new Error('x'))
    await expect(store.feedAll('evening')).rejects.toThrow('x')
    expect(repo.fetchFeedingStatus).toHaveBeenCalledTimes(2)
  })

  test('feedAll: „alle gefüttert“ nur, wenn der neu geladene Status das bestätigt (CASA-13)', async () => {
    const store = usePetsStore()
    // Race: Server legte nichts an (andere Person war schneller), Status zeigt aber 1 von 2
    repo.feedAll.mockResolvedValue([])
    repo.fetchFeedingStatus.mockResolvedValue([status('p1', { evening: feeding('x', 'evening') }), status('p2')])
    await expect(store.feedAll('evening')).resolves.toMatchObject({ created: [], allFed: false, fed: 1, total: 2 })

    // Status-Refetch scheitert: eigene Fütterungen sind trotzdem im Status
    store.feedingStatus = [status('p1'), status('p2')]
    repo.feedAll.mockResolvedValue([feeding('a', 'morning', 'p1'), feeding('b', 'morning', 'p2')])
    repo.fetchFeedingStatus.mockRejectedValue(new Error('offline'))
    await expect(store.feedAll('morning')).resolves.toMatchObject({ allFed: true, fed: 2, total: 2 })
  })

  test('undoFeedings löscht die angelegten Fütterungen und lädt den Status neu', async () => {
    const store = usePetsStore()
    repo.deleteFeeding.mockResolvedValue(undefined)
    repo.fetchFeedingStatus.mockResolvedValue([status()])
    await store.undoFeedings([feeding('f1'), feeding('f2', 'morning', 'p2')])
    expect(repo.deleteFeeding).toHaveBeenCalledWith(HOUSEHOLD_ID, 'p1', 'f1')
    expect(repo.deleteFeeding).toHaveBeenCalledWith(HOUSEHOLD_ID, 'p2', 'f2')
    expect(repo.fetchFeedingStatus).toHaveBeenCalledTimes(1)
  })
})

describe('Medikation', () => {
  test('fetch/create/update/remove', async () => {
    const store = usePetsStore()
    repo.fetchMedications.mockResolvedValue([med()])
    await store.fetchMedications('p1')
    expect(store.medications).toHaveLength(1)
    repo.fetchMedications.mockRejectedValue(new Error('x'))
    await expect(store.fetchMedications('p1')).rejects.toThrow('x')
    expect(store.medications).toHaveLength(1) // gleiches Tier: Liste bleibt

    repo.createMedication.mockResolvedValue(med('m2'))
    await store.createMedication('p1', {} as any)
    expect(store.medications.map(m => m.id)).toEqual(['m1', 'm2'])
    repo.updateMedication.mockResolvedValue(med('m1', { name: 'Neu' }))
    await store.updateMedication('p1', 'm1', {} as any)
    expect(store.medications[0].name).toBe('Neu')

    store.medicationLogs = { m1: [{ id: 'l' } as any] }
    repo.removeMedication.mockResolvedValue(undefined)
    await store.removeMedication('p1', 'm1')
    expect(store.medications.map(m => m.id)).toEqual(['m2'])
    expect(store.medicationLogs.m1).toBeUndefined()
  })

  test('giveMedication/handleMedicationGiven behalten nur die letzten 10 Logs, neueste zuerst', async () => {
    const store = usePetsStore()
    store.medicationLogs = { m1: Array.from({ length: 10 }, (_, i) => ({ id: `old${i}`, medication_id: 'm1' }) as any) }
    repo.giveMedication.mockResolvedValue({ id: 'new', medication_id: 'm1' })
    await store.giveMedication('p1', 'm1')
    expect(store.medicationLogs.m1).toHaveLength(10)
    expect(store.medicationLogs.m1[0].id).toBe('new')
    store.handleMedicationGiven({ id: 'sock', medication_id: 'm1' } as any)
    store.handleMedicationGiven({ id: 'x', medication_id: 'm2' } as any)
    expect(store.medicationLogs.m1[0].id).toBe('sock')
    expect(store.medicationLogs.m2).toHaveLength(1)
  })

  test('giveMedication sendet eine Client-ID (Idempotenz bei Retry, CASA-14)', async () => {
    const store = usePetsStore()
    repo.giveMedication.mockResolvedValue({ id: 'g', medication_id: 'm1' })
    await store.giveMedication('p1', 'm1')
    await store.giveMedication('p1', 'm1')
    const ids = repo.giveMedication.mock.calls.map(call => call[3])
    expect(ids[0]).toMatch(/^[0-9a-f-]{36}$/)
    // Jede bewusste Gabe ist eine neue Gabe (nie still zusammenführen)
    expect(ids[1]).not.toBe(ids[0])
  })

  test('fetchMedicationLog kürzt auf 10 und schluckt Fehler', async () => {
    const store = usePetsStore()
    repo.fetchMedicationLog.mockResolvedValue(Array.from({ length: 15 }, (_, i) => ({ id: `${i}` })))
    await store.fetchMedicationLog('p1', 'm1')
    expect(store.medicationLogs.m1).toHaveLength(10)
    repo.fetchMedicationLog.mockRejectedValue(new Error('x'))
    await store.fetchMedicationLog('p1', 'm1')
    expect(store.medicationLogs.m1).toHaveLength(10)
  })
})

describe('Pflegeaufgaben', () => {
  test('fetch/create/update', async () => {
    const store = usePetsStore()
    repo.fetchCareTasks.mockResolvedValue([task()])
    await store.fetchCareTasks('p1')
    repo.fetchCareTasks.mockRejectedValue(new Error('x'))
    await expect(store.fetchCareTasks('p1')).rejects.toThrow('x')
    expect(store.careTasks).toHaveLength(1)
    repo.createCareTask.mockResolvedValue(task('t2'))
    await store.createCareTask('p1', {} as any)
    repo.updateCareTask.mockResolvedValue(task('t1', { interval_days: 3 }))
    await store.updateCareTask('p1', 't1', {} as any)
    expect(store.careTasks.map(t => t.interval_days)).toEqual([3, 7])
  })

  test('completeCareTask: optimistisch (last_done/next_due), dann Server-Wahrheit', async () => {
    const store = usePetsStore()
    store.careTasks = [task()]
    const pending = deferred<any>()
    repo.completeCareTask.mockReturnValue(pending.promise)
    const p = store.completeCareTask('p1', 't1')
    const now = new Date()
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
    expect(store.careTasks[0].last_done_at).toBe(today)
    expect(store.careTasks[0].notified_at).toBeNull()
    expect(store.careTasks[0].next_due_at).not.toBe('2026-01-01')
    pending.resolve(task('t1', { last_done_at: 'server' }))
    await p
    expect(store.careTasks[0].last_done_at).toBe('server')
  })

  test('Tierwechsel leert Medikamente, Logs und Pflegeaufgaben – auch wenn das Laden scheitert', async () => {
    const store = usePetsStore()
    repo.fetchMedications.mockResolvedValue([med()])
    repo.fetchCareTasks.mockResolvedValue([task()])
    await store.fetchMedications('p1')
    await store.fetchCareTasks('p1')
    store.medicationLogs = { m1: [{ id: 'l' } as any] }
    repo.fetchMedications.mockRejectedValue(new Error('x'))
    repo.fetchCareTasks.mockRejectedValue(new Error('x'))
    await expect(store.fetchMedications('p2')).rejects.toThrow()
    await expect(store.fetchCareTasks('p2')).rejects.toThrow()
    expect(store.medications).toEqual([])
    expect(store.medicationLogs).toEqual({})
    expect(store.careTasks).toEqual([])
  })

  test('späte Antwort eines verlassenen Tiers wird verworfen', async () => {
    const store = usePetsStore()
    const slow = deferred<any>()
    repo.fetchMedications.mockReturnValueOnce(slow.promise).mockResolvedValueOnce([med('m2')])
    const p = store.fetchMedications('p1')
    await store.fetchMedications('p2')
    slow.resolve([med('m1')])
    await p
    expect(store.medications.map(m => m.id)).toEqual(['m2'])
  })

  test('completeCareTask rechnet die nächste Fälligkeit im lokalen Datum', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2024, 2, 10, 0, 30, 0))
    try {
      const store = usePetsStore()
      store.careTasks = [task()]
      repo.completeCareTask.mockReturnValue(new Promise(() => {}))
      store.completeCareTask('p1', 't1')
      expect(store.careTasks[0].last_done_at).toBe('2024-03-10')
      expect(store.careTasks[0].next_due_at).toBe('2024-03-17')
    } finally {
      vi.useRealTimers()
    }
  })

  test('completeCareTask: Rollback auf Snapshot bei Fehler', async () => {
    const store = usePetsStore()
    store.careTasks = [task()]
    repo.completeCareTask.mockRejectedValue(new Error('x'))
    await expect(store.completeCareTask('p1', 't1')).rejects.toThrow('x')
    expect(store.careTasks[0]).toEqual(task())
  })

  test('removeCareTask: optimistisch, Rollback bei Fehler', async () => {
    const store = usePetsStore()
    store.careTasks = [task('a'), task('b')]
    repo.removeCareTask.mockRejectedValue(new Error('x'))
    const p = store.removeCareTask('p1', 'a')
    expect(store.careTasks.map(t => t.id)).toEqual(['b'])
    await expect(p).rejects.toThrow('x')
    expect(store.careTasks.map(t => t.id)).toEqual(['a', 'b'])
  })
})

describe('Socket-Handler', () => {
  test('Pet created/updated/deleted (deleted räumt Feeding-Status auf)', () => {
    const store = usePetsStore()
    store.handlePetCreated(pet())
    store.handlePetCreated(pet('p1', { name: 'B' }))
    expect(store.pets).toHaveLength(1)
    store.handlePetUpdated(pet('p1', { name: 'C' }))
    store.handlePetUpdated(pet('unknown'))
    expect(store.pets.map(p => p.name)).toEqual(['C'])
    store.feedingStatus = [status('p1')]
    store.handlePetDeleted({ id: 'p1' })
    expect(store.pets).toEqual([])
    expect(store.feedingStatus).toEqual([])
  })

  test('Feeding created/deleted aktualisieren nur den passenden Slot', () => {
    const store = usePetsStore()
    store.feedingStatus = [status()]
    store.handleFeedingCreated(feeding('f1', 'evening'))
    store.handleFeedingCreated(feeding('fx', 'morning', 'unknown'))
    expect(store.feedingStatus[0].evening?.id).toBe('f1')
    expect(store.feedingStatus[0].morning).toBeNull()
    store.handleFeedingDeleted({ id: 'other', pet_id: 'p1' })
    expect(store.feedingStatus[0].evening).not.toBeNull()
    store.handleFeedingDeleted({ id: 'f1', pet_id: 'p1' })
    expect(store.feedingStatus[0].evening).toBeNull()
  })

  test('Medication und CareTask Handler (nur für das geöffnete Tier)', async () => {
    const store = usePetsStore()
    repo.fetchMedications.mockResolvedValue([])
    repo.fetchCareTasks.mockResolvedValue([])
    await store.fetchMedications('p1')
    await store.fetchCareTasks('p1')
    store.handleMedicationCreated(med('other', { pet_id: 'p2' }))
    store.handleCareTaskCreated(task('other', { pet_id: 'p2' }))
    expect(store.medications).toEqual([])
    expect(store.careTasks).toEqual([])
    store.handleMedicationCreated(med()); store.handleMedicationCreated(med('m1', { name: 'B' }))
    store.handleMedicationUpdated(med('m1', { name: 'C' })); store.handleMedicationUpdated(med('x'))
    expect(store.medications.map(m => m.name)).toEqual(['C'])
    store.medicationLogs = { m1: [{ id: 'l' } as any] }
    store.handleMedicationDeleted({ id: 'm1' })
    expect(store.medications).toEqual([])
    expect(store.medicationLogs.m1).toBeUndefined()

    store.handleCareTaskCreated(task()); store.handleCareTaskCreated(task('t1', { interval_days: 1 }))
    store.handleCareTaskUpdated(task('t1', { interval_days: 2 })); store.handleCareTaskUpdated(task('x'))
    expect(store.careTasks.map(t => t.interval_days)).toEqual([2])
    store.handleCareTaskDeleted({ id: 't1' })
    expect(store.careTasks).toEqual([])
  })
})

test('ohne Haushalt: alle Aktionen sind No-Ops', async () => {
  auth.currentHouseholdId = null
  const s = usePetsStore()
  await s.fetchPets(); await s.fetchFeedingStatus(); await s.fetchMembers()
  await s.createPet({} as any); await s.updatePet('p', {} as any); await s.removePet('p')
  await s.toggleFeeding('p', 'morning'); await s.feedAll('morning')
  await s.fetchMedications('p'); await s.createMedication('p', {} as any)
  await s.updateMedication('p', 'm', {} as any); await s.removeMedication('p', 'm')
  await s.giveMedication('p', 'm'); await s.fetchMedicationLog('p', 'm')
  await s.fetchCareTasks('p'); await s.createCareTask('p', {} as any)
  await s.updateCareTask('p', 't', {} as any); await s.completeCareTask('p', 't'); await s.removeCareTask('p', 't')
  for (const fn of [...Object.values(repo), householdRepo.fetchMembers]) expect(fn).not.toHaveBeenCalled()
})

describe('regressions: late responses and medication logs', () => {
  test('a medication GET preserves newer socket doses, deduplicates and sorts by time', async () => {
    const store = usePetsStore()
    const response = deferred<any>()
    repo.fetchMedicationLog.mockReturnValue(response.promise)
    const loading = store.fetchMedicationLog('p1', 'm1')
    const recent = { id: 'recent', medication_id: 'm1', given_at: '2026-10-07T10:00:00Z' } as any
    store.handleMedicationGiven(recent)
    store.handleMedicationGiven({ id: 'socket-only', medication_id: 'm1', given_at: '2026-10-07T11:00:00Z' } as any)
    response.resolve([
      { id: 'older', medication_id: 'm1', given_at: '2026-10-07T09:00:00Z' },
      recent,
    ])
    await loading
    expect(store.medicationLogs.m1.map(entry => entry.id)).toEqual(['socket-only', 'recent', 'older'])
  })

  test.each(['switch', 'socket'])('care deletion rollback preserves a concurrent %s change', async change => {
    const store = usePetsStore()
    repo.fetchCareTasks.mockResolvedValueOnce([task()])
    await store.fetchCareTasks('p1')
    const response = deferred<void>()
    repo.removeCareTask.mockReturnValue(response.promise)
    const removal = store.removeCareTask('p1', 't1')
    if (change === 'switch') {
      repo.fetchCareTasks.mockResolvedValueOnce([task('b', { pet_id: 'p2' })])
      await store.fetchCareTasks('p2')
    } else store.handleCareTaskCreated(task('new'))
    const rejected = expect(removal).rejects.toThrow('late failure')
    response.reject(new Error('late failure'))
    await rejected
    expect(store.careTasks.map(item => item.id)).toEqual(change === 'switch' ? ['b'] : ['t1', 'new'])
  })

  test.each(['socket-first', 'http-first'])('one dose remains one entry (%s)', async (order) => {
    const store = usePetsStore()
    repo.fetchMedications.mockResolvedValue([med()])
    await store.fetchMedications('p1')
    const log = { id: 'dose', medication_id: 'm1', household_id: HOUSEHOLD_ID } as any
    const response = deferred<any>()
    repo.giveMedication.mockReturnValue(response.promise)
    const giving = store.giveMedication('p1', 'm1')
    if (order === 'socket-first') store.handleMedicationGiven(log)
    response.resolve(log)
    await giving
    store.handleMedicationGiven(log)
    expect(store.medicationLogs.m1.map(entry => entry.id)).toEqual(['dose'])
  })

  test('reset prevents an old household request from repopulating care tasks', async () => {
    const store = usePetsStore()
    const response = deferred<any>()
    repo.fetchCareTasks.mockReturnValueOnce(response.promise)
    const loading = store.fetchCareTasks('p1')
    store.reset()
    auth.currentHouseholdId = 'household-b'
    response.resolve([task()])
    await loading
    expect(store.careTasks).toEqual([])
    store.handleCareTaskCreated(task())
    expect(store.careTasks).toEqual([])
  })

  test('a failed completion for cat A does not restore its tasks over cat B', async () => {
    const store = usePetsStore()
    repo.fetchCareTasks.mockResolvedValueOnce([task()])
    await store.fetchCareTasks('p1')
    const response = deferred<any>()
    repo.completeCareTask.mockReturnValueOnce(response.promise)
    const completion = store.completeCareTask('p1', 't1')
    repo.fetchCareTasks.mockResolvedValueOnce([task('b', { pet_id: 'p2' })])
    await store.fetchCareTasks('p2')
    const rejected = expect(completion).rejects.toThrow('late failure')
    response.reject(new Error('late failure'))
    await rejected
    expect(store.careTasks.map(item => item.id)).toEqual(['b'])
  })

  test('rollback restores only the failed task and keeps concurrent socket additions', async () => {
    const store = usePetsStore()
    repo.fetchCareTasks.mockResolvedValueOnce([task()])
    await store.fetchCareTasks('p1')
    const response = deferred<any>()
    repo.completeCareTask.mockReturnValueOnce(response.promise)
    const completion = store.completeCareTask('p1', 't1')
    store.handleCareTaskCreated(task('new'))
    const rejected = expect(completion).rejects.toThrow('failure')
    response.reject(new Error('failure'))
    await rejected
    expect(store.careTasks.map(item => item.id)).toEqual(['t1', 'new'])
    expect(store.careTasks[0].last_done_at).toBeNull()
  })

  test('latest list request wins, even when the previous request finishes last', async () => {
    const store = usePetsStore()
    const old = deferred<any>()
    repo.fetchAll.mockReturnValueOnce(old.promise).mockResolvedValueOnce([pet('new')])
    const previous = store.fetchPets()
    await store.fetchPets()
    old.resolve([pet('old')])
    await previous
    expect(store.pets.map(item => item.id)).toEqual(['new'])
  })

  test('late medication responses cannot repopulate another household', async () => {
    const store = usePetsStore()
    const response = deferred<any>()
    repo.giveMedication.mockReturnValueOnce(response.promise)
    const giving = store.giveMedication('p1', 'm1')
    store.reset()
    auth.currentHouseholdId = 'household-b'
    response.resolve({ id: 'dose', medication_id: 'm1' })
    await giving
    expect(store.medicationLogs).toEqual({})
  })

  test('undo stays bound to the household of the original feedings', async () => {
    const store = usePetsStore()
    auth.currentHouseholdId = 'household-b'
    repo.deleteFeeding.mockResolvedValue(undefined)
    await store.undoFeedings([feeding('original')])
    expect(repo.deleteFeeding).toHaveBeenCalledWith(HOUSEHOLD_ID, 'p1', 'original')
    expect(repo.fetchFeedingStatus).not.toHaveBeenCalled()
  })
})
