import type { SensorDevice } from '../types'

/** Ohne Messwert in dieser Zeit gilt ein Sensor als offline (Batteriesensoren melden selten). */
export const OFFLINE_AFTER_MS = 3 * 60 * 60 * 1000
export const BATTERY_LOW_PERCENT = 15
/** Wohnräume: unter 30 % trocken, über 65 % steigt die Schimmelgefahr. */
export const HUMIDITY_DRY_BELOW = 30
export const HUMIDITY_HIGH_ABOVE = 65

export type HumidityLevel = 'dry' | 'ok' | 'high'

export function isOffline(lastSeenAt: string | null, now: number = Date.now()): boolean {
  if (!lastSeenAt) return true
  return now - new Date(lastSeenAt).getTime() > OFFLINE_AFTER_MS
}

export function humidityLevel(humidity: number | null): HumidityLevel | null {
  if (humidity === null) return null
  if (humidity < HUMIDITY_DRY_BELOW) return 'dry'
  if (humidity > HUMIDITY_HIGH_ABOVE) return 'high'
  return 'ok'
}

export function isBatteryLow(battery: number | null): boolean {
  return battery !== null && battery <= BATTERY_LOW_PERCENT
}

export interface RoomGroup {
  room: string | null
  devices: SensorDevice[]
}

/** Nach Raum gruppiert, Räume und Sensoren alphabetisch; Sensoren ohne Raum zuletzt. */
export function groupByRoom(devices: SensorDevice[], locale?: string): RoomGroup[] {
  const groups = new Map<string, RoomGroup>()
  for (const device of devices) {
    const key = device.room ?? ''
    if (!groups.has(key)) groups.set(key, { room: device.room, devices: [] })
    groups.get(key)!.devices.push(device)
  }
  const result = [...groups.values()]
  for (const group of result) group.devices.sort((a, b) => a.name.localeCompare(b.name, locale))
  return result.sort((a, b) => {
    if (a.room === null) return 1
    if (b.room === null) return -1
    return a.room.localeCompare(b.room, locale)
  })
}

export interface ChartPoint {
  time: number
  value: number
}

export interface ChartScale {
  low: number
  high: number
}

/** Ganzzahlige Achsengrenzen mit etwas Luft; mindestens `minSpan` breit, damit Rauschen flach bleibt. */
export function chartScale(points: ChartPoint[], minSpan = 2): ChartScale {
  if (points.length === 0) return { low: 0, high: minSpan }
  let low = Math.floor(Math.min(...points.map((p) => p.value)))
  let high = Math.ceil(Math.max(...points.map((p) => p.value)))
  if (high - low < minSpan) {
    const extra = minSpan - (high - low)
    low -= Math.floor(extra / 2)
    high += Math.ceil(extra / 2)
  }
  return { low, high }
}

/** Position eines Punkts im Diagramm in Prozent (x: Zeitfenster, y: 0 = oben). */
export function chartPosition(point: ChartPoint, from: number, to: number, scale: ChartScale): { x: number; y: number } {
  const x = to > from ? ((point.time - from) / (to - from)) * 100 : 0
  const y = (1 - (point.value - scale.low) / (scale.high - scale.low)) * 100
  return { x: Math.min(100, Math.max(0, x)), y }
}

/**
 * SVG-Pfad (Koordinaten 0–100). Liegen zwei Punkte weiter als `maxGapMs` auseinander,
 * wird die Linie unterbrochen: Ein Ausfall soll als Lücke sichtbar sein, nicht als Gerade.
 */
export function chartPath(points: ChartPoint[], from: number, to: number, scale: ChartScale, maxGapMs: number): string {
  let path = ''
  let previous: ChartPoint | null = null
  for (const point of points) {
    const { x, y } = chartPosition(point, from, to, scale)
    const connect = previous !== null && point.time - previous.time <= maxGapMs
    path += `${connect ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)} `
    previous = point
  }
  return path.trim()
}

/** Punkt, dessen Zeit am nächsten an `time` liegt. */
export function nearestPoint(points: ChartPoint[], time: number): ChartPoint | null {
  let best: ChartPoint | null = null
  for (const point of points) {
    if (best === null || Math.abs(point.time - time) < Math.abs(best.time - time)) best = point
  }
  return best
}
