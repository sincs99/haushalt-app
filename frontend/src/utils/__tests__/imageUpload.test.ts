/**
 * Foto-Upload: Zielgrösse beim Verkleinern und lesbare Fehlergründe.
 */
import type {} from 'vitest'
import { ImageUnreadableError, imageUploadErrorReason, prepareImageForUpload, scaledSize } from '../imageUpload'

describe('scaledSize', () => {
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
