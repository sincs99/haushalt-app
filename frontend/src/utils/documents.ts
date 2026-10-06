/** Ab wie vielen Tagen vor Ablauf ein Dokument als "läuft bald ab" gilt */
export const EXPIRY_SOON_DAYS = 30

export type ExpiryState = 'expired' | 'soon' | 'ok'

export interface ExpiryStatus {
  state: ExpiryState
  /** Tage bis zum Ablauf (negativ = abgelaufen, 0 = heute) */
  days: number
}

function toLocalMidnight(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

/**
 * Berechnet den Ablauf-Status eines Dokuments anhand von expiry_date (YYYY-MM-DD).
 * Gibt null zurück, wenn kein Ablaufdatum gesetzt ist.
 */
export function getExpiryStatus(expiryDate: string | null, today: Date = new Date()): ExpiryStatus | null {
  if (!expiryDate) return null
  const expiry = new Date(expiryDate + 'T00:00:00')
  const days = Math.round((toLocalMidnight(expiry) - toLocalMidnight(today)) / (1000 * 60 * 60 * 24))
  if (days < 0) return { state: 'expired', days }
  if (days <= EXPIRY_SOON_DAYS) return { state: 'soon', days }
  return { state: 'ok', days }
}

/** Formatiert Bytes kompakt: 512 B, 1.4 KB, 3.2 MB, 1.0 GB */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value.toFixed(1)} ${units[unit]}`
}

export function isPreviewable(mimeType: string): boolean {
  return mimeType.startsWith('image/') || mimeType === 'application/pdf'
}
