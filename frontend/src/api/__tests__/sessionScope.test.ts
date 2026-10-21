import { beforeEach, expect, test, vi } from 'vitest'
import type { InternalAxiosRequestConfig } from 'axios'
import { deferred } from '../../stores/__tests__/helpers'
import { invalidateSessionScope, invalidateDataScope } from '../../services/sessionScope'

const { auth } = vi.hoisted(() => ({ auth: { token: 'token-A', isAuthenticated: true, refresh: vi.fn(), logout: vi.fn() } }))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => auth }))
import api from '../client'

beforeEach(() => {
  invalidateSessionScope()
  auth.token = 'token-A'
  auth.refresh.mockReset()
  auth.logout.mockReset()
})

test('does not replay an A mutation as B after a delayed 401', async () => {
  const pending = deferred<any>()
  let sent!: InternalAxiosRequestConfig
  const adapter = vi.fn((config: InternalAxiosRequestConfig) => { sent = config; return pending.promise })
  const request = api.post('/api/households/shared/notes', { title: 'A private note' }, { adapter })
  const rejected = expect(request).rejects.toMatchObject({ code: 'ERR_CANCELED' })
  invalidateSessionScope()
  auth.token = 'token-B'
  pending.reject({ config: sent, response: { status: 401 } })
  await rejected
  expect(adapter).toHaveBeenCalledTimes(1)
  expect(auth.refresh).not.toHaveBeenCalled()
  expect(auth.logout).not.toHaveBeenCalled()
})

test('same-principal refresh retries once using the renewed access token', async () => {
  auth.refresh.mockImplementation(async () => { auth.token = 'token-A-renewed' })
  const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
    if (!config._retried) throw { config, response: { status: 401 } }
    return { config, data: { saved: true }, status: 200, statusText: 'OK', headers: {} }
  })
  const result = await api.post('/api/households/shared/notes', {}, { adapter })
  expect(result.data).toEqual({ saved: true })
  expect(adapter).toHaveBeenCalledTimes(2)
  expect(adapter.mock.calls[1][0].headers.Authorization).toBe('Bearer token-A-renewed')
})

test('a household transition rejects a late successful response', async () => {
  const pending = deferred<any>()
  let sent!: InternalAxiosRequestConfig
  const request = api.get('/api/households/A/notes', {
    adapter: (config) => { sent = config; return pending.promise },
  })
  const rejected = expect(request).rejects.toMatchObject({ code: 'ERR_CANCELED' })
  invalidateDataScope()
  pending.resolve({ config: sent, data: ['private A data'], status: 200, statusText: 'OK', headers: {} })
  await rejected
})

test('identity change during refresh never dispatches the retry', async () => {
  auth.refresh.mockImplementation(async () => {
    invalidateSessionScope()
    auth.token = 'token-B'
  })
  const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
    throw { config, response: { status: 401 } }
  })
  await expect(api.post('/api/households/shared/notes', {}, { adapter }))
    .rejects.toMatchObject({ code: 'ERR_CANCELED' })
  expect(adapter).toHaveBeenCalledTimes(1)
  expect(auth.logout).not.toHaveBeenCalled()
})
