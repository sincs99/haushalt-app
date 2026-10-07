import { describe, expect, test, vi } from 'vitest'
import { useLoader } from '../useLoader'
import { deferred } from '../../stores/__tests__/helpers'

test('a reload during loading queues the newest context and all callers await it', async () => {
  const first = deferred<void>()
  const second = deferred<void>()
  const load = vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
  const loader = useLoader(load)
  const initial = loader.reload()
  await Promise.resolve()
  const switched = loader.reload()
  loader.reload()
  first.resolve()
  await Promise.resolve()
  expect(load).toHaveBeenCalledTimes(2)
  expect(loader.reloading.value).toBe(true)
  second.resolve()
  await Promise.all([initial, switched])
  expect(loader.reloading.value).toBe(false)
  expect(load).toHaveBeenCalledTimes(2)
})

describe('errors', () => {
  test('a new context succeeds after an old request fails', async () => {
    const first = deferred<void>()
    const load = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(undefined)
    const loader = useLoader(load)
    const initial = loader.reload()
    await Promise.resolve()
    loader.reload()
    first.reject(new Error('old context'))
    await initial
    expect(loader.loadError.value).toBe(false)
    expect(load).toHaveBeenCalledTimes(2)
  })

  test('a synchronous failure does not leave future reloads blocked', async () => {
    const load = vi.fn().mockImplementationOnce(() => { throw new Error('failure') }).mockResolvedValueOnce(undefined)
    const loader = useLoader(load)
    await loader.reload()
    expect(loader.loadError.value).toBe(true)
    await loader.reload()
    expect(loader.loadError.value).toBe(false)
  })
})
