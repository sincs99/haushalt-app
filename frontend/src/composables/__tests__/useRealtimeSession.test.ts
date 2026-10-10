/**
 * useRealtimeSession (App-Rahmen): Nachladen nur bei Anmeldung, Haushaltswechsel und
 * Reconnect — NICHT bei einem reinen Token-Refresh (CASA-44, races.test.ts R7).
 */
import type {} from 'vitest'
import { nextTick, reactive } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const mocks = vi.hoisted(() => ({
  auth: null as unknown as { token: string | null; currentHouseholdId: string | null; user: { id: string } | null; revalidateMembership: () => Promise<void> },
  get: vi.fn(),
  socket: {
    updateToken: vi.fn(),
    joinHousehold: vi.fn(),
    leaveHousehold: vi.fn(),
    on: vi.fn(),
    off: vi.fn(),
    onReconnect: vi.fn(),
    offReconnect: vi.fn(),
    disconnect: vi.fn(),
  },
  badge: { setAppBadgeHousehold: vi.fn(), refreshAppBadge: vi.fn(), refreshAppBadgeSoon: vi.fn() },
}))

vi.mock('../../api/client', () => ({
  default: { get: mocks.get, post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  API_BASE: '',
  authRequestConfig: () => ({}),
}))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => mocks.auth }))
vi.mock('../useSocket', () => ({ useSocket: () => mocks.socket }))
vi.mock('../useAppBadge', () => ({ BADGE_EVENTS: ['todo_created'], ...mocks.badge }))

import { useRealtimeSession } from '../useRealtimeSession'

const { socket } = mocks

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  mocks.get.mockResolvedValue({ data: [] })
  mocks.auth = reactive({ token: 't1', currentHouseholdId: 'hh-A', user: { id: 'u1' }, revalidateMembership: vi.fn(async () => {}) })
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

test('Start: verbinden, Room betreten, Stores laden', () => {
  const session = useRealtimeSession()
  expect(socket.updateToken).toHaveBeenCalledWith('t1')
  expect(socket.joinHousehold).toHaveBeenCalledWith('hh-A')
  expect(mocks.get).toHaveBeenCalled()
  session.stop()
})

test('Token-Refresh: nur reauth, kein Nachladen und kein erneuter Room-Beitritt (CASA-44)', async () => {
  const session = useRealtimeSession()
  mocks.get.mockClear()
  socket.joinHousehold.mockClear()

  mocks.auth.token = 't2'
  await nextTick()

  expect(socket.updateToken).toHaveBeenLastCalledWith('t2')
  expect(mocks.get).not.toHaveBeenCalled()
  expect(socket.joinHousehold).not.toHaveBeenCalled()
  session.stop()
})

test('Haushaltswechsel: alten Room verlassen, neuen betreten, nachladen', async () => {
  const session = useRealtimeSession()
  mocks.get.mockClear()

  mocks.auth.currentHouseholdId = 'hh-B'
  await nextTick()

  expect(socket.leaveHousehold).toHaveBeenCalledWith('hh-A')
  expect(socket.joinHousehold).toHaveBeenLastCalledWith('hh-B')
  expect(mocks.get.mock.calls.some(([url]) => String(url).includes('hh-B'))).toBe(true)
  session.stop()
})

test('Reconnect: Room neu betreten und nachladen', () => {
  const session = useRealtimeSession()
  mocks.get.mockClear()
  const handler = socket.onReconnect.mock.calls[0][0] as () => void

  handler()

  expect(socket.joinHousehold).toHaveBeenLastCalledWith('hh-A')
  expect(mocks.get).toHaveBeenCalled()
  // Verpasste Entfernung während der Trennung (CASA-49)
  expect(mocks.auth.revalidateMembership).toHaveBeenCalled()
  session.stop()
})

test('Logout: Socket trennen, kein Laden', async () => {
  const session = useRealtimeSession()
  mocks.get.mockClear()

  mocks.auth.token = null
  mocks.auth.currentHouseholdId = null
  await nextTick()

  expect(socket.disconnect).toHaveBeenCalled()
  expect(mocks.badge.setAppBadgeHousehold).toHaveBeenLastCalledWith(null)
  expect(mocks.get).not.toHaveBeenCalled()
  session.stop()
})
