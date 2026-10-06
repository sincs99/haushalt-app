/**
 * Unit-Tests für den Calendar-Store: Laden, Optimistic CRUD mit Rollback,
 * Wochennavigation und Socket-Handler. Repositories + Auth-Store gemockt.
 */
import type {} from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { CalendarEvent, CalendarInfo } from '../../types'
import { deferred, HOUSEHOLD_ID, USER_ID } from './helpers'

const { repo, householdRepo, auth } = vi.hoisted(() => ({
  repo: {
    fetchCalendars: vi.fn(),
    createCalendar: vi.fn(),
    updateCalendar: vi.fn(),
    deleteCalendar: vi.fn(),
    fetchByRange: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
  householdRepo: { fetchMembers: vi.fn() },
  auth: { currentHouseholdId: null as string | null, user: null as { id: string } | null },
}))

vi.mock('../../repositories/calendarRepository', () => ({ createOnlineCalendarRepository: () => repo }))
vi.mock('../../repositories/householdsRepository', () => ({ createOnlineHouseholdsRepository: () => householdRepo }))
vi.mock('../auth', () => ({ useAuthStore: () => auth }))

import { useCalendarStore } from '../calendar'

const makeEvent = (o: Partial<CalendarEvent> = {}): CalendarEvent => ({
  id: 'e1', household_id: HOUSEHOLD_ID, title: 'Zahnarzt', starts_at: '2026-03-02T10:00:00Z',
  ends_at: null, all_day: false, calendar_id: 'c1', participant_ids: [], note: null,
  created_by_user_id: USER_ID, created_at: '2026-01-01T00:00:00Z', ...o,
})
const makeCal = (o: Partial<CalendarInfo> = {}): CalendarInfo => ({
  id: 'c1', household_id: HOUSEHOLD_ID, name: 'Familie', color: '#ff0000', position: 0,
  created_at: '2026-01-01T00:00:00Z', ...o,
})

beforeEach(() => {
  setActivePinia(createPinia())
  vi.resetAllMocks()
  auth.currentHouseholdId = HOUSEHOLD_ID
  auth.user = { id: USER_ID }
})

describe('Laden', () => {
  test('fetchEvents lädt die aktuelle Woche (Mo–So) und setzt loading zurück', async () => {
    const store = useCalendarStore()
    store.currentWeekStart = '2026-03-02'
    const pending = deferred<CalendarEvent[]>()
    repo.fetchByRange.mockReturnValue(pending.promise)

    const p = store.fetchEvents()
    expect(store.loading).toBe(true)
    pending.resolve([makeEvent()])
    await p

    expect(repo.fetchByRange).toHaveBeenCalledWith(HOUSEHOLD_ID, '2026-03-02', '2026-03-08')
    expect(store.events).toHaveLength(1)
    expect(store.loading).toBe(false)
  })

  test('loading wird auch bei Fehler zurückgesetzt', async () => {
    const store = useCalendarStore()
    repo.fetchByRange.mockRejectedValue(new Error('x'))
    await expect(store.fetchEvents()).rejects.toThrow('x')
    expect(store.loading).toBe(false)
  })

  test('ohne Haushalt wird nichts geladen', async () => {
    auth.currentHouseholdId = null
    const store = useCalendarStore()
    await store.fetchEvents()
    await store.fetchCalendars()
    await store.fetchMembers()
    await store.addEvent({ title: 'x', starts_at: 'y', calendar_id: 'c1' })
    expect(repo.fetchByRange).not.toHaveBeenCalled()
    expect(repo.fetchCalendars).not.toHaveBeenCalled()
    expect(householdRepo.fetchMembers).not.toHaveBeenCalled()
    expect(repo.create).not.toHaveBeenCalled()
  })

  test('fetchCalendars/fetchMembers befüllen den State; Helper liefern Farbe/Name mit Fallback', async () => {
    const store = useCalendarStore()
    repo.fetchCalendars.mockResolvedValue([makeCal()])
    householdRepo.fetchMembers.mockResolvedValue([{ user_id: USER_ID }])
    await store.fetchCalendars()
    await store.fetchMembers()
    expect(store.members).toHaveLength(1)
    expect(store.getCalendarColor('c1')).toBe('#ff0000')
    expect(store.getCalendarName('c1')).toBe('Familie')
    expect(store.getCalendarColor('nope')).toBe('#8B8B8B')
    expect(store.getCalendarName('nope')).toBe('?')
  })

  test('navigateWeek verschiebt um ganze Wochen und lädt neu', async () => {
    const store = useCalendarStore()
    store.currentWeekStart = '2026-03-02'
    repo.fetchByRange.mockResolvedValue([])
    store.navigateWeek(1)
    expect(store.currentWeekStart).toBe('2026-03-09')
    store.navigateWeek(-2)
    expect(store.currentWeekStart).toBe('2026-02-23')
    expect(repo.fetchByRange).toHaveBeenLastCalledWith(HOUSEHOLD_ID, '2026-02-23', '2026-03-01')
  })
})

describe('Events: Optimistic CRUD', () => {
  test('addEvent zeigt Temp-Event und ersetzt es durch das Server-Event', async () => {
    const store = useCalendarStore()
    const pending = deferred<CalendarEvent>()
    repo.create.mockReturnValue(pending.promise)

    const p = store.addEvent({ title: 'Kino', starts_at: '2026-03-03T20:00:00Z', calendar_id: 'c1' })
    expect(store.events).toHaveLength(1)
    expect(store.events[0]).toMatchObject({ title: 'Kino', created_by_user_id: USER_ID, all_day: false })

    const server = makeEvent({ id: 'srv', title: 'Kino' })
    pending.resolve(server)
    await p
    expect(store.events).toEqual([server])
  })

  test('addEvent: Rollback bei Fehler', async () => {
    const store = useCalendarStore()
    const existing = makeEvent()
    store.events.push(existing)
    repo.create.mockRejectedValue(new Error('500'))
    await expect(store.addEvent({ title: 'x', starts_at: 'y', calendar_id: 'c1' })).rejects.toThrow('500')
    expect(store.events).toEqual([existing])
  })

  test('kein Duplikat, wenn das Socket-Event vor der REST-Antwort ankommt', async () => {
    const store = useCalendarStore()
    const pending = deferred<CalendarEvent>()
    repo.create.mockReturnValue(pending.promise)
    const server = makeEvent({ id: 'srv' })

    const p = store.addEvent({ title: 'x', starts_at: 'y', calendar_id: 'c1' })
    store.handleEventCreated(server)
    pending.resolve(server)
    await p
    expect(store.events).toEqual([server])
  })

  test('Event eines anderen Mitglieds geht während eines eigenen Creates nicht verloren', async () => {
    const store = useCalendarStore()
    const pending = deferred<CalendarEvent>()
    repo.create.mockReturnValue(pending.promise)

    const p = store.addEvent({ title: 'mein', starts_at: 'y', calendar_id: 'c1' })
    store.handleEventCreated(makeEvent({ id: 'other', title: 'fremd' }))
    pending.resolve(makeEvent({ id: 'mine', title: 'mein' }))
    await p
    expect(store.events.map(e => e.id).sort()).toEqual(['mine', 'other'])
  })

  test('updateEvent: optimistisch, Rollback auf Snapshot bei Fehler', async () => {
    const store = useCalendarStore()
    store.events.push(makeEvent())
    const pending = deferred<void>()
    repo.update.mockReturnValue(pending.promise)

    const p = store.updateEvent('e1', { title: 'Neu' })
    expect(store.events[0].title).toBe('Neu')
    pending.reject(new Error('x'))
    await expect(p).rejects.toThrow('x')
    expect(store.events[0].title).toBe('Zahnarzt')
  })

  test('updateEvent auf unbekannte ID ruft das Repository nicht auf', async () => {
    const store = useCalendarStore()
    await store.updateEvent('missing', { title: 'x' })
    expect(repo.update).not.toHaveBeenCalled()
  })

  test('deleteEvent entfernt sofort; bei Fehler zurück an alter Position', async () => {
    const store = useCalendarStore()
    store.events.push(makeEvent({ id: 'a' }), makeEvent({ id: 'b' }), makeEvent({ id: 'c' }))
    repo.remove.mockRejectedValue(new Error('x'))
    const p = store.deleteEvent('b')
    expect(store.events.map(e => e.id)).toEqual(['a', 'c'])
    await expect(p).rejects.toThrow('x')
    expect(store.events.map(e => e.id)).toEqual(['a', 'b', 'c'])
  })

  test('deleteEvent Erfolg und unbekannte ID', async () => {
    const store = useCalendarStore()
    store.events.push(makeEvent())
    repo.remove.mockResolvedValue(undefined)
    await store.deleteEvent('nope')
    expect(repo.remove).not.toHaveBeenCalled()
    await store.deleteEvent('e1')
    expect(repo.remove).toHaveBeenCalledWith(HOUSEHOLD_ID, 'e1')
    expect(store.events).toEqual([])
  })
})

describe('Kalender: Optimistic CRUD', () => {
  test('addCalendar ersetzt Temp durch Server-Kalender', async () => {
    const store = useCalendarStore()
    const server = makeCal({ id: 'srv' })
    repo.createCalendar.mockResolvedValue(server)
    await store.addCalendar({ name: 'Familie', color: '#ff0000' })
    expect(store.calendars).toEqual([server])
  })

  test('addCalendar: kein Duplikat bei schnellerem Socket; Rollback bei Fehler', async () => {
    const store = useCalendarStore()
    const pending = deferred<CalendarInfo>()
    repo.createCalendar.mockReturnValue(pending.promise)
    const server = makeCal({ id: 'srv' })
    const p = store.addCalendar({ name: 'Familie', color: '#ff0000' })
    store.handleCalendarCreated(server)
    pending.resolve(server)
    await p
    expect(store.calendars).toEqual([server])

    repo.createCalendar.mockRejectedValue(new Error('x'))
    await expect(store.addCalendar({ name: 'B', color: '#000' })).rejects.toThrow('x')
    expect(store.calendars).toEqual([server])
  })

  test('updateCalendar: Rollback bei Fehler', async () => {
    const store = useCalendarStore()
    store.calendars.push(makeCal())
    repo.updateCalendar.mockRejectedValue(new Error('x'))
    await expect(store.updateCalendar('c1', { name: 'Neu' })).rejects.toThrow('x')
    expect(store.calendars[0].name).toBe('Familie')
    repo.updateCalendar.mockResolvedValue(undefined)
    await store.updateCalendar('c1', { name: 'Neu' })
    expect(store.calendars[0].name).toBe('Neu')
    await store.updateCalendar('missing', { name: 'x' })
    expect(repo.updateCalendar).toHaveBeenCalledTimes(2)
  })

  test('deleteCalendar: Rollback an alter Position', async () => {
    const store = useCalendarStore()
    store.calendars.push(makeCal({ id: 'a' }), makeCal({ id: 'b' }))
    repo.deleteCalendar.mockRejectedValue(new Error('x'))
    await expect(store.deleteCalendar('a')).rejects.toThrow('x')
    expect(store.calendars.map(c => c.id)).toEqual(['a', 'b'])
    repo.deleteCalendar.mockResolvedValue(undefined)
    await store.deleteCalendar('a')
    await store.deleteCalendar('missing')
    expect(store.calendars.map(c => c.id)).toEqual(['b'])
  })
})

describe('Socket-Handler', () => {
  test('Event created/updated/deleted sind idempotent, Server gewinnt', () => {
    const store = useCalendarStore()
    store.handleEventCreated(makeEvent())
    store.handleEventCreated(makeEvent({ title: 'Doppelt' }))
    expect(store.events).toHaveLength(1)
    expect(store.events[0].title).toBe('Doppelt')
    store.handleEventUpdated(makeEvent({ title: 'Upd' }))
    store.handleEventUpdated(makeEvent({ id: 'unknown' }))
    expect(store.events).toHaveLength(1)
    expect(store.events[0].title).toBe('Upd')
    store.handleEventDeleted({ id: 'e1' })
    store.handleEventDeleted({ id: 'e1' })
    expect(store.events).toEqual([])
  })

  test('Calendar created/updated/deleted', () => {
    const store = useCalendarStore()
    store.handleCalendarCreated(makeCal())
    store.handleCalendarCreated(makeCal({ name: 'B' }))
    expect(store.calendars).toHaveLength(1)
    store.handleCalendarUpdated(makeCal({ name: 'C' }))
    store.handleCalendarUpdated(makeCal({ id: 'unknown' }))
    expect(store.calendars.map(c => c.name)).toEqual(['C'])
    store.handleCalendarDeleted({ id: 'c1' })
    expect(store.calendars).toEqual([])
  })
})
