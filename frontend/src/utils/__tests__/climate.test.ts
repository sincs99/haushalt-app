import { describe, expect, it } from 'vitest'
import {
  chartPath,
  chartPosition,
  chartScale,
  groupByRoom,
  humidityLevel,
  isBatteryLow,
  isOffline,
  nearestPoint,
  OFFLINE_AFTER_MS,
} from '../climate'
import type { SensorDevice } from '../../types'

function device(name: string, room: string | null): SensorDevice {
  return {
    id: name, household_id: 'h', external_id: name, name, room,
    temperature: 20, humidity: 50, battery: 90, last_seen_at: null, created_at: '2026-01-01T00:00:00Z',
  }
}

describe('climate status', () => {
  it('treats missing or old readings as offline', () => {
    const now = Date.parse('2026-11-10T12:00:00Z')
    expect(isOffline(null, now)).toBe(true)
    expect(isOffline(new Date(now - OFFLINE_AFTER_MS - 1).toISOString(), now)).toBe(true)
    expect(isOffline(new Date(now - 60_000).toISOString(), now)).toBe(false)
  })

  it('classifies humidity', () => {
    expect(humidityLevel(null)).toBeNull()
    expect(humidityLevel(25)).toBe('dry')
    expect(humidityLevel(30)).toBe('ok')
    expect(humidityLevel(65)).toBe('ok')
    expect(humidityLevel(66)).toBe('high')
  })

  it('flags a low battery', () => {
    expect(isBatteryLow(null)).toBe(false)
    expect(isBatteryLow(15)).toBe(true)
    expect(isBatteryLow(16)).toBe(false)
  })
})

describe('groupByRoom', () => {
  it('sorts rooms and devices, devices without a room last', () => {
    const groups = groupByRoom([device('b', null), device('z', 'Bad'), device('a', 'Bad'), device('c', 'Küche')], 'de')
    expect(groups.map((g) => g.room)).toEqual(['Bad', 'Küche', null])
    expect(groups[0].devices.map((d) => d.name)).toEqual(['a', 'z'])
  })
})

describe('chart geometry', () => {
  it('pads a narrow range to the minimum span', () => {
    expect(chartScale([{ time: 0, value: 20.2 }, { time: 1, value: 20.6 }])).toEqual({ low: 20, high: 22 })
    expect(chartScale([{ time: 0, value: 18.4 }, { time: 1, value: 23.1 }])).toEqual({ low: 18, high: 24 })
    expect(chartScale([])).toEqual({ low: 0, high: 2 })
  })

  it('maps time to x and value to y (top = high)', () => {
    const scale = { low: 10, high: 20 }
    expect(chartPosition({ time: 50, value: 20 }, 0, 100, scale)).toEqual({ x: 50, y: 0 })
    expect(chartPosition({ time: 100, value: 10 }, 0, 100, scale)).toEqual({ x: 100, y: 100 })
  })

  it('breaks the line across a gap', () => {
    const points = [{ time: 0, value: 10 }, { time: 10, value: 20 }, { time: 90, value: 10 }]
    const path = chartPath(points, 0, 100, { low: 10, high: 20 }, 20)
    expect(path).toBe('M0.00 100.00 L10.00 0.00 M90.00 100.00')
  })

  it('finds the nearest point', () => {
    const points = [{ time: 0, value: 1 }, { time: 10, value: 2 }]
    expect(nearestPoint(points, 6)).toEqual({ time: 10, value: 2 })
    expect(nearestPoint([], 6)).toBeNull()
  })
})
