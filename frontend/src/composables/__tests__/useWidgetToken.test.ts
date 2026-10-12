/**
 * Widget-Karte: Antworten für einen inzwischen gewechselten Haushalt werden verworfen (CASA-50).
 */
import { nextTick, ref } from 'vue'
import { useWidgetToken } from '../useWidgetToken'
import { deferred } from '../../stores/__tests__/helpers'
import type { WidgetTokenCreated, WidgetTokenStatus } from '../../repositories/widgetRepository'

const statusA: WidgetTokenStatus = { exists: true, token_prefix: 'hw_AAAA', created_at: '2026-01-01T00:00:00Z', last_used_at: null }
const statusB: WidgetTokenStatus = { exists: false, token_prefix: null, created_at: null, last_used_at: null }

function setup() {
  const householdId = ref<string | null>('hh-a')
  const repo = { fetchStatus: vi.fn(), create: vi.fn(), revoke: vi.fn() }
  const onError = vi.fn()
  const widget = useWidgetToken(householdId, repo, (token) => `script(${token})`, onError)
  return { householdId, repo, onError, widget }
}

test('Status von Haushalt A, der nach dem Wechsel zu B ankommt, wird verworfen', async () => {
  const { householdId, repo, widget } = setup()
  const slowA = deferred<WidgetTokenStatus>()
  repo.fetchStatus.mockReturnValueOnce(slowA.promise).mockResolvedValueOnce(statusB)

  const loadingA = widget.load()
  householdId.value = 'hh-b'
  await nextTick()
  await vi.waitFor(() => expect(widget.status.value).toEqual(statusB))
  slowA.resolve(statusA)
  await loadingA

  expect(widget.status.value).toEqual(statusB)
})

test('Erzeugen für A, Wechsel zu B während des Requests: kein Skript mit A-Schlüssel in B', async () => {
  const { householdId, repo, widget, onError } = setup()
  const slowCreate = deferred<WidgetTokenCreated>()
  repo.create.mockReturnValueOnce(slowCreate.promise)
  repo.fetchStatus.mockResolvedValue(statusB)

  const creating = widget.create()
  householdId.value = 'hh-b'
  await nextTick()
  slowCreate.resolve({ token: 'hw_secretA', token_prefix: 'hw_secret', created_at: '2026-01-01T00:00:00Z' })

  expect(await creating).toBe(false)
  expect(widget.script.value).toBeNull()
  expect(repo.create).toHaveBeenCalledWith('hh-a')
  expect(onError).not.toHaveBeenCalled()
})

test('ohne Wechsel: Skript und Status werden übernommen, Fehler gemeldet', async () => {
  const { repo, widget, onError } = setup()
  repo.create.mockResolvedValueOnce({ token: 'hw_x', token_prefix: 'hw_x', created_at: '2026-01-01T00:00:00Z' })
  repo.fetchStatus.mockResolvedValue(statusA)

  expect(await widget.create()).toBe(true)
  expect(widget.script.value).toBe('script(hw_x)')
  expect(widget.status.value).toEqual(statusA)

  repo.revoke.mockRejectedValueOnce(new Error('boom'))
  expect(await widget.revoke()).toBe(false)
  expect(onError).toHaveBeenCalledTimes(1)
})

test('Haushaltswechsel leert Skript und Status sofort', async () => {
  const { householdId, repo, widget } = setup()
  repo.create.mockResolvedValueOnce({ token: 'hw_x', token_prefix: 'hw_x', created_at: '2026-01-01T00:00:00Z' })
  repo.fetchStatus.mockResolvedValueOnce(statusA).mockReturnValueOnce(new Promise(() => {}))
  await widget.create()

  householdId.value = 'hh-b'
  await nextTick()

  expect(widget.script.value).toBeNull()
  expect(widget.status.value).toBeNull()
})
