/**
 * Foto-Upload: Zielgrösse beim Verkleinern und lesbare Fehlergründe.
 */
import { afterEach, describe, expect, test, vi } from 'vitest'
import { ImageUnreadableError, imageUploadErrorReason, prepareImageForUpload, scaledSize } from '../imageUpload'

describe('scaledSize', () => {
  test('keeps the narrow edge at least one pixel', () => {
    expect(scaledSize(10000, 1)).toEqual({ width: 1600, height: 1 })
    expect(scaledSize(1, 10000)).toEqual({ width: 1, height: 1600 })
  })
  test('keeps small images', () => {
    expect(scaledSize(800, 600)).toEqual({ width: 800, height: 600 })
    expect(scaledSize(1600, 1200)).toEqual({ width: 1600, height: 1200 })
  })

  test('scales the longest edge to 1600 (48 MP iPhone photo)', () => {
    expect(scaledSize(8064, 6048)).toEqual({ width: 1600, height: 1200 })
    expect(scaledSize(6048, 8064)).toEqual({ width: 1200, height: 1600 })
  })
})

describe('imageUploadErrorReason', () => {
  test('unreadable image', () => {
    expect(imageUploadErrorReason(new ImageUnreadableError())).toContain('HEIC')
  })

  test('backend error code', () => {
    const error = { response: { data: { detail: { code: 'IMAGE_TOO_MANY_PIXELS', message: 'x' } } } }
    expect(imageUploadErrorReason(error)).toContain('25')
  })

  test('file too large', () => {
    const error = { response: { data: { detail: { code: 'FILE_TOO_LARGE', message: 'x' } } } }
    expect(imageUploadErrorReason(error)).toContain('10 MB')
  })

  test('network error', () => {
    expect(imageUploadErrorReason({ message: 'Network Error' })).not.toBe('Network Error')
  })
})

test('returns the file unchanged without browser image APIs', async () => {
  const file = { name: 'a.jpg', type: 'image/jpeg', size: 1 } as File
  expect(await prepareImageForUpload(file)).toBe(file)
})

describe('browser decoders and HEIC server fallback', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

  function browser(imageReadable: boolean) {
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:photo')
    vi.stubGlobal('createImageBitmap', vi.fn().mockRejectedValue(new Error('bitmap decoder failed')))
    const draw = vi.fn()
    vi.stubGlobal('document', { createElement: () => ({
      getContext: () => ({ drawImage: draw }),
      toBlob: (callback: (blob: Blob) => void) => callback(new Blob(['converted'], { type: 'image/jpeg' })),
    }) })
    vi.stubGlobal('Image', class {
      naturalWidth = 8064
      naturalHeight = 6048
      onload?: () => void
      onerror?: () => void
      set src(_url: string) { queueMicrotask(() => imageReadable ? this.onload?.() : this.onerror?.()) }
    })
    return { revoke, draw }
  }

  test('uses the image element when bitmap decoding fails and emits a scaled JPEG', async () => {
    const { revoke, draw } = browser(true)
    const result = await prepareImageForUpload(new File(['heic'], 'iphone.heic', { type: 'image/heic' }))
    expect(result.type).toBe('image/jpeg')
    expect(result.name).toBe('iphone.jpg')
    expect(draw.mock.calls[0].slice(1)).toEqual([0, 0, 1600, 1200])
    expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:photo')
  })

  test('uses the image element even when createImageBitmap is unavailable', async () => {
    const { draw } = browser(true)
    vi.stubGlobal('createImageBitmap', undefined)
    expect((await prepareImageForUpload(new File(['image'], 'photo.jpg', { type: 'image/jpeg' }))).type).toBe('image/jpeg')
    expect(draw).toHaveBeenCalledOnce()
  })

  test.each(['image/heic', 'image/heif', '', 'application/octet-stream'])('passes undecodable HEIC to the server with a supported MIME (%s)', async type => {
    const { revoke } = browser(false)
    const original = new File(['HEIC contents'], 'iphone.HEIC', { type })
    const result = await prepareImageForUpload(original)
    expect(result.type).toBe('image/heic')
    expect(await result.text()).toBe(await original.text())
    expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:photo')
  })

  test('does not send an unreadable non-HEIC file to the server', async () => {
    browser(false)
    await expect(prepareImageForUpload(new File(['bad'], 'broken.jpg', { type: 'image/jpeg' }))).rejects.toBeInstanceOf(ImageUnreadableError)
  })

  test.each(['no-context', 'no-blob'])('normalizes HEIC for the server when canvas conversion fails (%s)', async failure => {
    browser(true)
    vi.stubGlobal('document', { createElement: () => ({
      getContext: () => failure === 'no-context' ? null : { drawImage: vi.fn() },
      toBlob: (callback: (blob: Blob | null) => void) => callback(null),
    }) })
    const original = new File(['heic'], 'photo.heic', { type: '' })
    const result = await prepareImageForUpload(original)
    expect(result.type).toBe('image/heic')
    expect(await result.text()).toBe('heic')
  })

  test('rejects a HEIC file larger than the raw upload limit', async () => {
    browser(false)
    const error = await prepareImageForUpload({ name: 'large.heic', type: 'image/heic', size: 11 * 1024 * 1024 } as File).catch(error => error)
    expect(imageUploadErrorReason(error)).toContain('10 MB')
  })
})
