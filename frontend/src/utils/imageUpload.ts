import i18n from '../i18n'
import { translateApiError } from './apiErrors'

/**
 * Fotos vor dem Upload verkleinern (längste Kante 1600 px, JPEG).
 *
 * Der Server verkleinert ohnehin auf 1600 px, lehnt aber Dateien über 10 MB
 * und Bilder über 25 Megapixel ab. Handy-Fotos (z.B. 48 MP auf dem iPhone)
 * scheitern sonst, obwohl am Ende nur 1600 px gespeichert werden. Nebeneffekt:
 * iPhone-Fotos im HEIC-Format werden zu JPEG, weil Safari HEIC dekodieren kann.
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

/** Ziel-Grösse bei längster Kante maxEdge (nie vergrössern). */
export function scaledSize(width: number, height: number, maxEdge = MAX_IMAGE_EDGE) {
  const longest = Math.max(width, height)
  if (longest <= maxEdge) return { width, height }
  const ratio = maxEdge / longest
  return { width: Math.round(width * ratio), height: Math.round(height * ratio) }
}

async function decode(file: File): Promise<ImageBitmap> {
  try {
    // EXIF-Drehung übernehmen, damit Hochformat-Fotos nicht liegen
    return await createImageBitmap(file, { imageOrientation: 'from-image' })
  } catch {
    throw new ImageUnreadableError()
  }
}

/**
 * Gibt eine Datei zurück, die der Server annimmt: unverändert, wenn sie schon
 * passt; sonst verkleinert als JPEG. Wirft ImageUnreadableError, wenn der
 * Browser das Bild nicht öffnen kann.
 */
export async function prepareImageForUpload(file: File): Promise<File> {
  if (typeof createImageBitmap !== 'function' || typeof document === 'undefined') return file

  const bitmap = await decode(file)
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
    if (!ctx) return file
    ctx.drawImage(bitmap, 0, 0, target.width, target.height)

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob(resolve, 'image/jpeg', JPEG_QUALITY),
    )
    if (!blob) return file
    const name = file.name.replace(/\.[^.]+$/, '') + '.jpg'
    return new File([blob], name, { type: 'image/jpeg', lastModified: Date.now() })
  } finally {
    bitmap.close()
  }
}

/** Lesbarer Grund für einen fehlgeschlagenen Foto-Upload (für Toasts). */
export function imageUploadErrorReason(error: unknown): string {
  if (error instanceof ImageUnreadableError) return i18n.global.t('errors.imageUnreadable')
  return translateApiError(error)
}
