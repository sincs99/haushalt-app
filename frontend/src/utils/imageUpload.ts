import i18n from '../i18n'
import { translateApiError } from './apiErrors'

/**
 * Fotos vor dem Upload verkleinern (längste Kante 1600 px, JPEG).
 *
 * Der Server verkleinert ohnehin auf 1600 px, lehnt aber Dateien über 10 MB
 * und Bilder über 25 Megapixel ab. Handy-Fotos (z.B. 48 MP auf dem iPhone)
 * scheitern sonst, obwohl am Ende nur 1600 px gespeichert werden. Nebeneffekt:
 * HEIC wird im Browser zu JPEG; fehlt der Decoder, konvertiert der Server
 * die Originaldatei unter seinen Upload- und Pixel-Limits.
 */

export const MAX_IMAGE_EDGE = 1600
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024
const SERVER_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const JPEG_QUALITY = 0.88

/** Bild liess sich im Browser nicht öffnen (Format unbekannt oder Datei kaputt). */
export class ImageUnreadableError extends Error {
  constructor() {
    super('image unreadable')
    this.name = 'ImageUnreadableError'
  }
}

export class ImageTooLargeError extends Error {}

/** HEIC often arrives without a MIME type from a photo picker. */
export function isHeic(file: File): boolean {
  return ['image/heic', 'image/heif'].includes(file.type.toLowerCase()) ||
    (!file.type || file.type === 'application/octet-stream') && /\.(heic|heif)$/i.test(file.name)
}

function serverFile(file: File): File {
  return isHeic(file) ? new File([file], file.name, { type: 'image/heic', lastModified: file.lastModified }) : file
}

/** Ziel-Grösse bei längster Kante maxEdge (nie vergrössern). */
export function scaledSize(width: number, height: number, maxEdge = MAX_IMAGE_EDGE) {
  const longest = Math.max(width, height)
  if (longest <= maxEdge) return { width, height }
  const ratio = maxEdge / longest
  return { width: Math.max(1, Math.round(width * ratio)), height: Math.max(1, Math.round(height * ratio)) }
}

type DecodedImage = { source: CanvasImageSource; width: number; height: number; close: () => void }

async function decode(file: File): Promise<DecodedImage> {
  try {
    if (typeof createImageBitmap === 'function') {
      const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
      return { source: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close() }
    }
  } catch { /* Safari's image element can support formats its bitmap decoder cannot. */ }

  const url = URL.createObjectURL(file)
  try {
    const img = new Image()
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve()
      img.onerror = () => reject(new ImageUnreadableError())
      img.src = url
    })
    return { source: img, width: img.naturalWidth, height: img.naturalHeight, close: () => URL.revokeObjectURL(url) }
  } catch {
    URL.revokeObjectURL(url)
    throw new ImageUnreadableError()
  }
}

/**
 * Gibt eine Datei zurück, die der Server annimmt: unverändert, wenn sie schon
 * passt; sonst verkleinert als JPEG. Wirft ImageUnreadableError, wenn der
 * Browser das Bild nicht öffnen kann.
 */
export async function prepareImageForUpload(file: File): Promise<File> {
  if (typeof document === 'undefined') return file

  let bitmap: DecodedImage
  try {
    bitmap = await decode(file)
  } catch (error) {
    if (!isHeic(file)) throw error
    // Server validates the bytes and converts HEIC when neither browser decoder can.
    if (file.size > MAX_UPLOAD_BYTES) throw new ImageTooLargeError()
    return serverFile(file)
  }
  try {
    const target = scaledSize(bitmap.width, bitmap.height)
    const fits =
      SERVER_IMAGE_TYPES.includes(file.type) &&
      file.size <= MAX_UPLOAD_BYTES &&
      target.width === bitmap.width &&
      target.height === bitmap.height
    if (fits) return file

    const canvas = document.createElement('canvas')
    canvas.width = target.width
    canvas.height = target.height
    const ctx = canvas.getContext('2d')
    if (!ctx) return serverFile(file)
    ctx.drawImage(bitmap.source, 0, 0, target.width, target.height)

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY),
    )
    if (!blob) return serverFile(file)
    const name = file.name.replace(/\.[^.]+$/, '') + '.jpg'
    return new File([blob], name, { type: 'image/jpeg', lastModified: Date.now() })
  } finally {
    bitmap.close()
  }
}

/** Lesbarer Grund für einen fehlgeschlagenen Foto-Upload (für Toasts). */
export function imageUploadErrorReason(error: unknown): string {
  if (error instanceof ImageTooLargeError) return i18n.global.t('errors.FILE_TOO_LARGE')
  if (error instanceof ImageUnreadableError) return i18n.global.t('errors.imageUnreadable')
  return translateApiError(error)
}
