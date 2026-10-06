/**
 * Unit-Tests für useSocket: Token-Übergabe nach Refresh (reauth) und Verhalten nach
 * serverseitigem Sitzungsende (Ablauf → Refresh + Reconnect, Logout → kein Refresh).
 *
 * socket.io-client ist durch einen Fake ersetzt, der nur den genutzten Teil abbildet.
 */
import type {} from 'vitest'

type Handler = (...args: any[]) => void

class FakeSocket {
  connected = false
  active = false
  handlers = new Map<string, Set<Handler>>()
  emitted: Array<[string, unknown]> = []
  connectCalls = 0

  constructor(public auth: (cb: (data: { token: string | null }) => void) => void) {
    this.active = true // io() verbindet sofort
  }

  on(event: string, handler: Handler) {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set())
    this.handlers.get(event)!.add(handler)
    return this
  }

  off(event: string, handler: Handler) {
    this.handlers.get(event)?.delete(handler)
    return this
  }

  emit(event: string, data?: unknown) {
    this.emitted.push([event, data])
    return this
  }

  connect() {
    this.connectCalls++
    this.active = true
    return this
  }

  disconnect() {
    const wasConnected = this.connected
    this.connected = false
    this.active = false
    if (wasConnected) this.fire('disconnect', 'io client disconnect')
    return this
  }

  /** Token, das der Client beim nächsten (Re-)Connect schicken würde. */
  authToken(): string | null {
    let token: string | null = null
    this.auth((data) => {
      token = data.token
    })
    return token
  }

  // ── Server-Seite simulieren ──

  fire(event: string, ...args: unknown[]) {
    this.handlers.get(event)?.forEach((h) => h(...args))
  }

  serverAccepts() {
    this.connected = true
    this.active = true
    this.fire('connect')
  }

  serverEnds(reason: string) {
    this.fire('session_ended', { reason })
    this.connected = false
    this.active = false
    this.fire('disconnect', 'io server disconnect')
  }

  serverRejects() {
    this.connected = false
    this.active = false
    this.fire('connect_error', new Error('rejected'))
  }
}

const sockets: FakeSocket[] = []

vi.mock('socket.io-client', () => ({
  io: (_url: unknown, opts: { auth: ConstructorParameters<typeof FakeSocket>[0] }) => {
    const s = new FakeSocket(opts.auth)
    sockets.push(s)
    return s
  },
}))
vi.mock('../../api/client', () => ({ API_BASE: 'http://api.test' }))

async function setup() {
  vi.resetModules()
  sockets.length = 0
  const { useSocket } = await import('../useSocket')
  return useSocket()
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('useSocket', () => {
  test('neues Token bei bestehender Verbindung: reauth statt Neuaufbau', async () => {
    const socket = await setup()
    socket.updateToken('t1')
    const s = sockets[0]
    s.serverAccepts()

    socket.updateToken('t2')

    expect(sockets).toHaveLength(1)
    expect(s.emitted).toContainEqual(['reauth', { token: 't2' }])
    expect(s.authToken()).toBe('t2') // auch spätere Auto-Reconnects nutzen das neue Token
  })

  test('gleiches Token (z.B. Haushaltswechsel): kein reauth', async () => {
    const socket = await setup()
    socket.updateToken('t1')
    sockets[0].serverAccepts()

    socket.updateToken('t1')

    expect(sockets[0].emitted).toEqual([])
  })

  test('Server trennt wegen Ablauf: Refresh, dann Reconnect mit frischem Token', async () => {
    const socket = await setup()
    const refresher = vi.fn().mockResolvedValue('fresh')
    socket.setTokenRefresher(refresher)
    socket.updateToken('t1')
    const s = sockets[0]
    s.serverAccepts()
    const onReconnect = vi.fn()
    socket.onReconnect(onReconnect)

    s.serverEnds('expired')
    await flush()

    expect(refresher).toHaveBeenCalledTimes(1)
    expect(s.connectCalls).toBe(1)
    expect(s.authToken()).toBe('fresh')
    s.serverAccepts()
    expect(onReconnect).toHaveBeenCalledTimes(1) // Raum neu betreten, Daten nachladen
    expect(socket.isConnected.value).toBe(true)
  })

  test('Ablauf, aber Refresh liefert kein Token (ausgeloggt): kein Reconnect', async () => {
    const socket = await setup()
    socket.setTokenRefresher(vi.fn().mockResolvedValue(null))
    socket.updateToken('t1')
    const s = sockets[0]
    s.serverAccepts()

    s.serverEnds('expired')
    await flush()

    expect(s.connectCalls).toBe(0)
    expect(socket.isConnected.value).toBe(false)
  })

  test('Server trennt wegen Logout (anderes Gerät): Reconnect mit aktuellem Token, ohne Refresh', async () => {
    const socket = await setup()
    const refresher = vi.fn().mockResolvedValue('fresh')
    socket.setTokenRefresher(refresher)
    socket.updateToken('t1')
    const s = sockets[0]
    s.serverAccepts()

    s.serverEnds('logout')
    await flush()

    expect(s.connectCalls).toBe(1)
    expect(s.authToken()).toBe('t1')
    // Auch wenn der Server diesen Reconnect ablehnt: kein Refresh mit evtl. widerrufenem Token
    s.serverRejects()
    await flush()
    expect(refresher).not.toHaveBeenCalled()
  })

  test('abgelehnter Connect: genau ein Refresh-Versuch, kein Endlos-Loop', async () => {
    const socket = await setup()
    const refresher = vi.fn().mockResolvedValue('fresh')
    socket.setTokenRefresher(refresher)
    socket.updateToken('stale')
    const s = sockets[0]

    s.serverRejects()
    await flush()
    expect(refresher).toHaveBeenCalledTimes(1)
    expect(s.connectCalls).toBe(1)

    s.serverRejects()
    await flush()
    expect(refresher).toHaveBeenCalledTimes(1)
    expect(s.connectCalls).toBe(1)
  })

  test('nach disconnect() (Logout): kein Reconnect bei späteren Server-Events', async () => {
    const socket = await setup()
    const refresher = vi.fn().mockResolvedValue('fresh')
    socket.setTokenRefresher(refresher)
    socket.updateToken('t1')
    const s = sockets[0]
    s.serverAccepts()

    socket.disconnect()
    s.serverEnds('logout')
    s.serverEnds('expired')
    await flush()

    expect(refresher).not.toHaveBeenCalled()
    expect(s.connectCalls).toBe(0)
  })

  test('nach Logout und erneutem Login: neue Verbindung mit neuem Token', async () => {
    const socket = await setup()
    socket.updateToken('t1')
    sockets[0].serverAccepts()
    socket.disconnect()

    socket.updateToken('t2')

    expect(sockets).toHaveLength(2)
    expect(sockets[1].authToken()).toBe('t2')
  })
})
