import { describe, it, expect } from 'vitest'
import type { TagResolveResult } from '../../types'
import {
  moduleRouteFor,
  nextScanStep,
  safeInternalPath,
  scanErrorKind,
  suggestedSlot,
  tagUrl,
} from '../tagScan'
import { qrSvg, qrSvgDataUrl } from '../qr'

function result(over: Partial<TagResolveResult> = {}): TagResolveResult {
  return {
    tag_id: 't1',
    label: 'Futternapf',
    household_id: 'h1',
    household_name: 'WG',
    action: 'pet.feed',
    target_type: 'pet',
    target_id: 'p1',
    target_name: 'Mia',
    navigate_only: false,
    navigate_to: null,
    description: 'Feed Mia',
    details: { slot: 'morning' },
    can_execute: true,
    reason: null,
    ...over,
  }
}

function axiosError(status: number, code?: string) {
  return { response: { status, data: code ? { detail: { code, message: '' } } : {} } }
}

describe('nextScanStep', () => {
  it('ausführbare Aktion → Bestätigung', () => {
    expect(nextScanStep(result(), 'h1')).toEqual({ kind: 'confirm', switchHouseholdTo: null })
  })

  it('Tag aus anderem eigenen Haushalt → Wechsel vormerken', () => {
    expect(nextScanStep(result(), 'h2')).toEqual({ kind: 'confirm', switchHouseholdTo: 'h1' })
  })

  it('Navigations-Tag → direkt navigieren', () => {
    const r = result({ action: 'shopping_list.open', navigate_only: true, navigate_to: '/shopping?list=l1', can_execute: false })
    expect(nextScanStep(r, 'h1')).toEqual({ kind: 'navigate', to: '/shopping?list=l1', switchHouseholdTo: null })
  })

  it('Navigations-Tag mit unsicherem Ziel → Startseite', () => {
    const r = result({ navigate_only: true, navigate_to: '//evil.example/x' })
    expect(nextScanStep(r, 'h1')).toMatchObject({ kind: 'navigate', to: '/dashboard' })
  })

  it('nichts zu tun → blockiert mit Grund', () => {
    expect(nextScanStep(result({ can_execute: false, reason: 'ALREADY_FED' }), 'h1')).toEqual({
      kind: 'blocked',
      reason: 'ALREADY_FED',
    })
    expect(nextScanStep(result({ can_execute: false, reason: null }), 'h1')).toEqual({
      kind: 'blocked',
      reason: 'UNKNOWN',
    })
  })
})

describe('safeInternalPath', () => {
  it.each([
    ['/shopping', '/shopping'],
    ['/shopping?list=1', '/shopping?list=1'],
    ['//evil.example', null],
    ['/\\evil.example', null],
    ['https://evil.example', null],
    ['javascript:alert(1)', null],
    ['', null],
    [null, null],
  ])('%s → %s', (input, expected) => {
    expect(safeInternalPath(input as string | null)).toBe(expected)
  })
})

describe('scanErrorKind', () => {
  it.each([
    [axiosError(404, 'TAG_NOT_FOUND'), 'not_found'],
    [axiosError(404, 'TAG_TARGET_NOT_FOUND'), 'target_missing'],
    [axiosError(403, 'NOT_HOUSEHOLD_MEMBER'), 'forbidden'],
    [axiosError(410, 'TAG_DISABLED'), 'disabled'],
    [axiosError(409, 'FEEDING_DUPLICATE'), 'already_done'],
    [axiosError(409, 'TAG_NOTHING_TO_DO'), 'nothing_to_do'],
    [axiosError(422, 'TAG_ACTION_INVALID'), 'unsupported'],
    [axiosError(422, 'TAG_NOT_EXECUTABLE'), 'unsupported'],
    [axiosError(422), 'unknown'],
    [axiosError(429, 'RATE_LIMITED'), 'rate_limited'],
    [axiosError(500), 'unknown'],
    [new Error('Network Error'), 'offline'],
  ])('%#', (err, kind) => {
    expect(scanErrorKind(err)).toBe(kind)
  })
})

describe('Hilfsfunktionen', () => {
  it('tagUrl', () => {
    expect(tagUrl('abc_-1', 'https://casa.example')).toBe('https://casa.example/t/abc_-1')
    expect(tagUrl('abc', 'https://casa.example/')).toBe('https://casa.example/t/abc')
  })

  it('suggestedSlot', () => {
    expect(suggestedSlot(result({ details: { slot: 'evening' } }))).toBe('evening')
    expect(suggestedSlot(result({ details: {} }))).toBe('morning')
  })

  it('moduleRouteFor', () => {
    expect(moduleRouteFor(result())).toBe('/pets')
    expect(moduleRouteFor(result({ action: 'pet.care_task.done', details: { pet_id: 'p9' } }))).toBe('/pets/p9')
    expect(moduleRouteFor(result({ action: 'pet.care_task.done', details: {} }))).toBe('/pets')
    expect(moduleRouteFor(result({ action: 'chore.assignment.done' }))).toBe('/chores')
    expect(moduleRouteFor(result({ action: 'todo.done' }))).toBe('/todos')
    expect(moduleRouteFor(result({ action: 'plant.water' }))).toBe('/dashboard')
  })
})

describe('QR-Code', () => {
  it('erzeugt ein SVG, das die URL kodiert', () => {
    const svg = qrSvg('https://casa.example/t/abc')
    expect(svg.startsWith('<svg')).toBe(true)
    expect(svg).toContain('<path')
    // Gleiche Eingabe → gleiches Bild
    expect(qrSvg('https://casa.example/t/abc')).toBe(svg)
    expect(qrSvg('https://casa.example/t/abd')).not.toBe(svg)
  })

  it('liefert eine Data-URL (CSP: img-src data:)', () => {
    expect(qrSvgDataUrl('x').startsWith('data:image/svg+xml;charset=utf-8,')).toBe(true)
  })
})
