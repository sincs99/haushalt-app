import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { effectScope, ref, type EffectScope } from 'vue'
import { deferred } from '../../stores/__tests__/helpers'

const { repo, prepare, dispose } = vi.hoisted(() => ({
  repo: { fetchFileAsObjectUrl: vi.fn(), revokeObjectUrl: vi.fn(), uploadFile: vi.fn(), deleteFile: vi.fn() },
  prepare: vi.fn(),
  dispose: [] as Array<() => void>,
}))
vi.mock('vue', async importOriginal => ({
  ...await importOriginal<typeof import('vue')>(),
  onUnmounted: (fn: () => void) => { dispose.push(fn) },
}))
vi.mock('../../repositories/filesRepository', () => ({ createOnlineFilesRepository: () => repo }))
vi.mock('../../utils/imageUpload', async importOriginal => ({
  ...await importOriginal<typeof import('../../utils/imageUpload')>(),
  prepareImageForUpload: prepare,
}))
import { useProtectedImage } from '../useProtectedImage'
import { usePhotoUpload } from '../usePhotoUpload'

let scope: EffectScope
beforeEach(() => {
  vi.resetAllMocks()
  dispose.length = 0
  scope = effectScope()
})
afterEach(() => {
  dispose.forEach(fn => fn())
  scope.stop()
})

describe('protected images', () => {
  test('current download errors clear loading and a subsequent photo recovers', async () => {
    repo.fetchFileAsObjectUrl.mockRejectedValueOnce(new Error('download failed')).mockResolvedValueOnce('blob:recovered')
    const file = ref('photo-a')
    const image = scope.run(() => useProtectedImage(ref('hh'), file))!
    await Promise.resolve()
    expect(image.error.value).toBe(true)
    expect(image.loading.value).toBe(false)
    file.value = 'photo-b'
    await Promise.resolve()
    expect(image.error.value).toBe(false)
    expect(image.objectUrl.value).toBe('blob:recovered')
  })

  test('an old response never replaces the new image and its URL is revoked', async () => {
    const first = deferred<string>()
    const second = deferred<string>()
    repo.fetchFileAsObjectUrl.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)
    const household = ref<string | null>('household-a')
    const file = ref<string | null>('photo-a')
    const image = scope.run(() => useProtectedImage(household, file))!
    file.value = 'photo-b'
    second.resolve('blob:new')
    await Promise.resolve()
    first.resolve('blob:old')
    await Promise.resolve()
    expect(image.objectUrl.value).toBe('blob:new')
    expect(repo.revokeObjectUrl).toHaveBeenCalledWith('blob:old')
  })

  test('a response after unmount is revoked instead of leaking', async () => {
    const response = deferred<string>()
    repo.fetchFileAsObjectUrl.mockReturnValue(response.promise)
    const image = scope.run(() => useProtectedImage(ref('hh'), ref('photo')))!
    dispose.forEach(fn => fn())
    response.resolve('blob:late')
    await Promise.resolve()
    expect(image.objectUrl.value).toBeNull()
    expect(repo.revokeObjectUrl).toHaveBeenCalledWith('blob:late')
  })

  test('clearing an image invalidates pending work and clears loading', async () => {
    const response = deferred<string>()
    repo.fetchFileAsObjectUrl.mockReturnValue(response.promise)
    const file = ref<string | null>('photo')
    const image = scope.run(() => useProtectedImage(ref('hh'), file))!
    file.value = null
    expect(image.loading.value).toBe(false)
    response.reject(new Error('old failure'))
    await Promise.resolve()
    expect(image.error.value).toBe(false)
  })
})

describe('photo uploads', () => {
  const file = new File(['photo'], 'photo.jpg', { type: 'image/jpeg' })
  function setup() {
    const householdId = ref<string | null>('household-a')
    const entityId = ref('cat-a')
    const fileId = ref<string | null>('old-photo')
    const update = vi.fn().mockResolvedValue({})
    prepare.mockResolvedValue(file)
    repo.uploadFile.mockResolvedValue({ id: 'new-photo' })
    repo.deleteFile.mockResolvedValue(undefined)
    const uploader = scope.run(() => usePhotoUpload({ householdId, entityId, fileId, update }))!
    return { householdId, entityId, update, uploader }
  }

  test('associates and cleans up within the original household', async () => {
    const { update, uploader } = setup()
    expect(await uploader.upload(file)).toBe(true)
    expect(update).toHaveBeenCalledWith('household-a', 'cat-a', 'new-photo')
    expect(repo.deleteFile).toHaveBeenCalledWith('household-a', 'old-photo')
  })

  test('unmount during an upload discards association and cleans up the late file', async () => {
    const { update, uploader } = setup()
    const response = deferred<any>()
    repo.uploadFile.mockReturnValue(response.promise)
    const uploading = uploader.upload(file)
    await Promise.resolve()
    dispose.forEach(fn => fn())
    response.resolve({ id: 'new-photo' })
    expect(await uploading).toBe(false)
    expect(update).not.toHaveBeenCalled()
    expect(repo.deleteFile).toHaveBeenCalledExactlyOnceWith('household-a', 'new-photo')
  })

  test('an old photo still in use does not undo a successful association', async () => {
    const { update, uploader } = setup()
    repo.deleteFile.mockRejectedValue(new Error('FILE_IN_USE'))
    expect(await uploader.upload(file)).toBe(true)
    expect(update).toHaveBeenCalledWith('household-a', 'cat-a', 'new-photo')
    expect(repo.deleteFile).toHaveBeenCalledExactlyOnceWith('household-a', 'old-photo')
    expect(uploader.uploading.value).toBe(false)
  })

  test.each(['household', 'entity'])('a %s switch during upload cancels association and cleans up in the original household', async change => {
    const { householdId, entityId, update, uploader } = setup()
    const response = deferred<any>()
    repo.uploadFile.mockReturnValue(response.promise)
    const uploading = uploader.upload(file)
    await Promise.resolve()
    if (change === 'household') householdId.value = 'household-b'
    else entityId.value = 'cat-b'
    response.resolve({ id: 'new-photo' })
    expect(await uploading).toBe(false)
    expect(update).not.toHaveBeenCalled()
    expect(repo.deleteFile).toHaveBeenCalledWith('household-a', 'new-photo')
    expect(repo.deleteFile).not.toHaveBeenCalledWith('household-b', expect.anything())
  })

  test('a switch during preprocessing prevents the upload entirely', async () => {
    const { entityId, update, uploader } = setup()
    const response = deferred<File>()
    prepare.mockReturnValue(response.promise)
    const uploading = uploader.upload(file)
    entityId.value = 'cat-b'
    response.resolve(file)
    expect(await uploading).toBe(false)
    expect(repo.uploadFile).not.toHaveBeenCalled()
    expect(update).not.toHaveBeenCalled()
  })

  test('failed association deletes only the newly uploaded file', async () => {
    const { update, uploader } = setup()
    update.mockRejectedValue(new Error('patch failed'))
    await expect(uploader.upload(file)).rejects.toThrow('patch failed')
    expect(repo.deleteFile).toHaveBeenCalledExactlyOnceWith('household-a', 'new-photo')
    expect(uploader.uploading.value).toBe(false)
  })

  test('changing household during a successful PATCH preserves the new photo and suppresses the old-screen success', async () => {
    const { update, householdId, uploader } = setup()
    const response = deferred<void>()
    update.mockReturnValue(response.promise)
    const uploading = uploader.upload(file)
    await Promise.resolve()
    await Promise.resolve()
    expect(update).toHaveBeenCalledWith('household-a', 'cat-a', 'new-photo')
    householdId.value = 'household-b'
    response.resolve()
    expect(await uploading).toBe(false)
    expect(repo.deleteFile).toHaveBeenCalledExactlyOnceWith('household-a', 'old-photo')
  })
})
