/**
 * Unit-Tests für Ablauf-Status und Grössenformatierung der Dokumente.
 */
import type {} from 'vitest'
import { EXPIRY_SOON_DAYS, formatBytes, getExpiryStatus, isPreviewable } from '../documents'

describe('getExpiryStatus', () => {
  const today = new Date(2026, 9, 5, 15, 30) // 05.10.2026, Uhrzeit egal

  test('kein Ablaufdatum → null', () => {
    expect(getExpiryStatus(null, today)).toBeNull()
  })

  test('gestern → expired', () => {
    expect(getExpiryStatus('2026-10-04', today)).toEqual({ state: 'expired', days: -1 })
  })

  test('heute → soon mit 0 Tagen', () => {
    expect(getExpiryStatus('2026-10-05', today)).toEqual({ state: 'soon', days: 0 })
  })

  test(`genau ${EXPIRY_SOON_DAYS} Tage → soon`, () => {
    expect(getExpiryStatus('2026-11-04', today)).toEqual({ state: 'soon', days: EXPIRY_SOON_DAYS })
  })

  test(`${EXPIRY_SOON_DAYS + 1} Tage → ok`, () => {
    expect(getExpiryStatus('2026-11-05', today)?.state).toBe('ok')
  })

  test('über Monats- und Jahresgrenzen', () => {
    expect(getExpiryStatus('2027-01-01', new Date(2026, 11, 31))).toEqual({ state: 'soon', days: 1 })
  })
})

describe('formatBytes', () => {
  test('Bytes', () => expect(formatBytes(512)).toBe('512 B'))
  test('Kilobytes', () => expect(formatBytes(1536)).toBe('1.5 KB'))
  test('Megabytes', () => expect(formatBytes(10 * 1024 * 1024)).toBe('10.0 MB'))
  test('Gigabytes', () => expect(formatBytes(1024 * 1024 * 1024)).toBe('1.0 GB'))
})

describe('isPreviewable', () => {
  test('Bilder und PDFs', () => {
    expect(isPreviewable('image/jpeg')).toBe(true)
    expect(isPreviewable('application/pdf')).toBe(true)
    expect(isPreviewable('application/zip')).toBe(false)
  })
})
