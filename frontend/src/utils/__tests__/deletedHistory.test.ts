import { beforeEach, describe, expect, test, vi } from 'vitest'
import { createDeletedHistory } from '../deletedHistory'
import { deferred } from '../../stores/__tests__/helpers'
import { bumpHouseholdGeneration } from '../householdGuard'

const { auth } = vi.hoisted(() => ({ auth: { currentHouseholdId: 'h1' } }))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => auth }))

const records = (count: number) => Array.from({ length: count }, (_, i) => ({ id: `record-${i}` }))

beforeEach(() => { auth.currentHouseholdId = 'h1' })

describe('deleted history pagination', () => {
  test('loads beyond 50 and preserves all loaded pages on refresh after a deletion', async () => {
    let server = records(151)
    const fetch = vi.fn(async (_hid, { offset = 0, limit }) => server.slice(offset, offset + limit))
    const history = createDeletedHistory(fetch, 50)
    await history.fetch()
    expect(history.items.value).toHaveLength(50)
    expect(history.hasMore.value).toBe(true)
    await history.loadMore()
    expect(history.items.value).toHaveLength(100)
    server = [{ id: 'new' }, ...server]
    await history.fetch()
    expect(history.items.value).toHaveLength(100)
    expect(history.items.value[0].id).toBe('new')
    await history.loadMore()
    await history.loadMore()
    expect(history.items.value).toEqual(server)
    expect(history.hasMore.value).toBe(false)
  })

  test('restores shift offsets without hiding the next older record', async () => {
    let server = records(101)
    const fetch = vi.fn(async (_hid, { offset = 0, limit }) => server.slice(offset, offset + limit))
    const history = createDeletedHistory(fetch, 50)
    await history.fetch()
    await history.loadMore()
    server = server.filter(row => row.id !== 'record-0')
    history.drop('record-0')
    await vi.waitFor(() => expect(history.loading.value).toBe(false))
    expect(history.items.value.map(row => row.id)).toContain('record-100')
    await history.loadMore()
    expect(history.items.value).toEqual(server)
    expect(history.hasMore.value).toBe(false)
  })

  test('failed load-more preserves visible rows and can be retried', async () => {
    const server = records(51)
    const fetch = vi.fn(async (_hid, { offset = 0, limit }) => server.slice(offset, offset + limit))
    const history = createDeletedHistory(fetch, 50)
    await history.fetch()
    fetch.mockRejectedValueOnce(new Error('offline'))
    await expect(history.loadMore()).rejects.toThrow('offline')
    expect(history.items.value).toHaveLength(50)
    expect(history.error.value).toBe(true)
    expect(history.loading.value).toBe(false)
    await history.fetch()
    expect(history.items.value).toEqual(server)
    expect(history.error.value).toBe(false)
  })

  test('reset and household changes reject stale results and stale loading flags', async () => {
    const pending = deferred<{ id: string }[]>()
    const fetch = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue([{ id: 'household-b' }])
    const history = createDeletedHistory<{ id: string }>(fetch, 50)
    const old = history.fetch()
    bumpHouseholdGeneration()
    auth.currentHouseholdId = 'h2'
    history.reset()
    await history.fetch()
    pending.resolve([{ id: 'household-a' }])
    await old
    expect(history.items.value).toEqual([{ id: 'household-b' }])
    expect(history.loading.value).toBe(false)
    expect(history.error.value).toBe(false)
  })

  test('a newer refresh wins over a slow previous refresh', async () => {
    const pending = deferred<{ id: string }[]>()
    const fetch = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue([{ id: 'new' }])
    const history = createDeletedHistory<{ id: string }>(fetch, 50)
    const old = history.fetch()
    await history.fetch()
    pending.resolve([{ id: 'old' }])
    await old
    expect(history.items.value).toEqual([{ id: 'new' }])
  })
})
