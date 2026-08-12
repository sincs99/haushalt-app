/**
 * Unit-Tests für parseAmountToRappen und formatRappen.
 *
 * Vitest 4.x: globals via Config, kein expliziter Import von test/describe/expect.
 */
import type {} from 'vitest'
import { parseAmountToRappen, formatRappen } from '../money'

describe('parseAmountToRappen', () => {
  // --- Gültige Eingaben ---
  test('parst "12,50" (Schweizer/Deutsche Tastatur) zu 1250 Rappen', () => {
    expect(parseAmountToRappen('12,50')).toBe(1250)
  })

  test('parst "12.50" (englisches Format) zu 1250 Rappen', () => {
    expect(parseAmountToRappen('12.50')).toBe(1250)
  })

  test('parst "12" (ganzzahlig) zu 1200 Rappen', () => {
    expect(parseAmountToRappen('12')).toBe(1200)
  })

  test('parst "0.50" zu 50 Rappen', () => {
    expect(parseAmountToRappen('0.50')).toBe(50)
  })

  test('parst ".50" zu 50 Rappen', () => {
    expect(parseAmountToRappen('.50')).toBe(50)
  })

  test('parst "1.5" zu 150 Rappen (eine Nachkommastelle)', () => {
    expect(parseAmountToRappen('1.5')).toBe(150)
  })

  test('parst "100" zu 10000 Rappen', () => {
    expect(parseAmountToRappen('100')).toBe(10000)
  })

  test('ignoriert führende/nachfolgende Leerzeichen', () => {
    expect(parseAmountToRappen('  23.50  ')).toBe(2350)
  })

  // --- Ungültige Eingaben ---
  test('gibt null zurück bei Leerstring ""', () => {
    expect(parseAmountToRappen('')).toBeNull()
  })

  test('gibt null zurück bei "abc"', () => {
    expect(parseAmountToRappen('abc')).toBeNull()
  })

  test('gibt null zurück bei "1,2,3" (mehrere Trennzeichen)', () => {
    expect(parseAmountToRappen('1,2,3')).toBeNull()
  })

  test('gibt null zurück bei "12.555" (mehr als 2 Nachkommastellen)', () => {
    expect(parseAmountToRappen('12.555')).toBeNull()
  })

  test('gibt null zurück bei "0" (null Rappen)', () => {
    expect(parseAmountToRappen('0')).toBeNull()
  })

  test('gibt null zurück bei "0.00"', () => {
    expect(parseAmountToRappen('0.00')).toBeNull()
  })

  test('gibt null zurück bei nur Leerzeichen "   "', () => {
    expect(parseAmountToRappen('   ')).toBeNull()
  })

  test('gibt null zurück bei Sonderzeichen "12€"', () => {
    expect(parseAmountToRappen('12€')).toBeNull()
  })

  test('gibt null zurück bei negativen Werten "-5"', () => {
    expect(parseAmountToRappen('-5')).toBeNull()
  })
})

describe('formatRappen', () => {
  test('formatiert 2350 als CHF-String', () => {
    const result = formatRappen(2350, 'CHF', 'de')
    expect(result).toContain('23')
    expect(result).toContain('50')
  })

  test('formatiert 0 als CHF 0.00', () => {
    const result = formatRappen(0, 'CHF', 'de')
    expect(result).toContain('0')
  })
})
