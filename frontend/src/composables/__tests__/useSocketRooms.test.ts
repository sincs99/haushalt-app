/**
 * useSocket: Room-Beitritt (CASA-46) und Haushaltsfilter für Events (CASA-12).
 *
 * - `join_household` scheitert serverseitig nur mit einem `error`-Event → Status 'failed',
 *   erneuter Versuch mit Wartezeit; erst das Ack ohne vorheriges `error` heisst 'joined'.
 * - Payloads mit `household_id` eines anderen Haushalts erreichen die Handler nicht.
 */
import type {} from 'vitest'

type Handler = (...args: any[]) => void

class FakeSocket {
  connected = false
  active = true
  handlers = new Map<string, Set<Handler>>()
  emitted: Array<{ event: string; data: unknown; ack?: Handler }> = []

  on(event: string, handler: Handler) {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set())
    this.handlers.get(event)!.add(handler)
    return this
  }

  off(event: string, handler: Handler) {
    this.handlers.get(event)?.delete(handler)
    return this
  }

  emit(event: string, data?: unknown, ack?: Handler) {
    this.emitted.push({ event, data, ack })
    return this
  }

  connect() {
    this.active = true
    return this
  }

  disconnect() {
    const was = this.connected
    this.connected = false
    this.active = false
    if (was) this.fire('disconnect', 'io client disconnect')
    return this
  }

  fire(event: string, ...args: unknown[]) {
    this.handlers.get(event)?.forEach((h) => h(...args))
  }

  serverAccepts() {
    this.connected = true
    this.fire('connect')
  }

  joins() {
    return this.emitted.filter((e) => e.event === 'join_household')
  }
}

const sockets: FakeSocket[] = []

vi.mock('socket.io-client', () => ({
  io: () => {
    const s = new FakeSocket()
    sockets.push(s)
    return s
  },
}))
vi.mock('../../api/client', () => ({ API_BASE: 'http://api.test' }))
// householdGuard importiert den Auth-Store; hier nicht gebraucht
vi.mock('../../stores/auth', () => ({ useAuthStore: () => ({ currentHouseholdId: null }) }))

async function setup() {
  vi.resetModules()
  sockets.length = 0
  const { useSocket } = await import('../useSocket')
  const socket = useSocket()
  socket.updateToken('t1')
  sockets[0].serverAccepts()
  return { socket, s: sockets[0] }
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('join_household', () => {
  test('Ack ohne vorheriges error → joined', async () => {
    const { socket, s } = await setup()
    socket.joinHousehold('hh-A')
    expect(socket.roomStatus.value).toBe('joining')
    s.joins()[0].ack!()
    expect(socket.roomStatus.value).toBe('joined')
  })

  test('error vom Server → failed (nicht „verbunden“), dann erneuter Beitritt', async () => {
    const { socket, s } = await setup()
    socket.joinHousehold('hh-A')
    s.fire('error', { message: 'Internal server error' })
    s.joins()[0].ack!() // Ack nach dem error ändert nichts mehr
    expect(socket.roomStatus.value).toBe('failed')

    vi.advanceTimersByTime(2_000)
    expect(s.joins()).toHaveLength(2)
    expect(s.joins()[1].data).toEqual({ household_id: 'hh-A' })
    expect(socket.roomStatus.value).toBe('joining')
    s.joins()[1].ack!()
    expect(socket.roomStatus.value).toBe('joined')
  })

  test('Wiederholungen sind begrenzt', async () => {
    const { socket, s } = await setup()
    socket.joinHousehold('hh-A')
    for (let i = 0; i < 10; i++) {
      s.fire('error', { message: 'Not a member of this household' })
      vi.advanceTimersByTime(120_000)
    }
    expect(s.joins().length).toBe(6) // erster Versuch + 5 Wiederholungen
    expect(socket.roomStatus.value).toBe('failed')
  })

  test('kein Retry mehr nach Haushaltswechsel', async () => {
    const { socket, s } = await setup()
    socket.joinHousehold('hh-A')
    s.fire('error', { message: 'x' })
    socket.leaveHousehold('hh-A')
    socket.joinHousehold('hh-B')
    vi.advanceTimersByTime(60_000)
    expect(s.joins().map((j) => (j.data as any).household_id)).toEqual(['hh-A', 'hh-B'])
  })

  test('Verbindungsabbruch: Status zurück auf none (Reconnect tritt neu bei)', async () => {
    const { socket, s } = await setup()
    socket.joinHousehold('hh-A')
    s.joins()[0].ack!()
    s.connected = false
    s.fire('disconnect', 'transport close')
    expect(socket.roomStatus.value).toBe('none')
  })
})

describe('Haushaltsfilter', () => {
  test('Payload eines anderen Haushalts wird verworfen, eigener und ohne household_id durchgelassen', async () => {
    const { socket, s } = await setup()
    socket.joinHousehold('hh-B')
    const handler = vi.fn()
    socket.on('todo_created', handler)

    s.fire('todo_created', { id: 't1', household_id: 'hh-A' })
    s.fire('todo_created', { id: 't2', household_id: 'hh-B' })
    s.fire('todo_deleted', { id: 't3' })
    s.fire('todo_created', { id: 't4' })

    expect(handler.mock.calls.map((c) => c[0].id)).toEqual(['t2', 't4'])
  })

  test('nach leaveHousehold kommen Events des alten Haushalts nicht mehr an', async () => {
    const { socket, s } = await setup()
    socket.joinHousehold('hh-A')
    const handler = vi.fn()
    socket.on('todo_created', handler)
    socket.leaveHousehold('hh-A')
    s.fire('todo_created', { id: 't1', household_id: 'hh-A' })
    expect(handler).not.toHaveBeenCalled()
  })

  test('off entfernt genau eine Registrierung (gleicher Handler an mehreren Stellen)', async () => {
    const { socket, s } = await setup()
    socket.joinHousehold('hh-A')
    const handler = vi.fn()
    socket.on('todo_created', handler)
    socket.on('todo_created', handler)
    socket.off('todo_created', handler)
    s.fire('todo_created', { id: 't1', household_id: 'hh-A' })
    expect(handler).toHaveBeenCalledTimes(1)
    socket.off('todo_created', handler)
    s.fire('todo_created', { id: 't2', household_id: 'hh-A' })
    expect(handler).toHaveBeenCalledTimes(1)
  })
})
