import type { AiPlantCareAdvice, PlantCareStatus, PlantCareStatusTask, PlantCareTask } from '../types'

type Translate = (key: string, params?: Record<string, unknown>) => string

/** Anzeigename einer Pflegeaufgabe: Freitext-Label, sonst die lokalisierte Pflegeart. */
export function careTaskName(task: Pick<PlantCareTask | PlantCareStatusTask, 'care_type' | 'label'>, t: Translate): string {
  return task.label?.trim() || t(`plants.careTypes.${task.care_type}`)
}

/** Ganze Tage von heute (lokal) bis zum Datum "YYYY-MM-DD"; negativ = überfällig. */
export function daysUntil(dateStr: string, now: Date = new Date()): number {
  const [y, m, d] = dateStr.split('-').map(Number)
  const target = Date.UTC(y, m - 1, d)
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.round((target - today) / 86_400_000)
}

/** Fälligkeitstext: "Überfällig" / "Heute fällig" / "in n Tagen". */
export function dueText(dateStr: string, t: Translate, now: Date = new Date()): string {
  const diff = daysUntil(dateStr, now)
  if (diff < 0) return t('plants.overdue')
  if (diff === 0) return t('plants.dueToday')
  return t('plants.dueIn', { n: diff })
}

export function waterTasks(item: PlantCareStatus): PlantCareStatusTask[] {
  return item.tasks.filter(task => task.care_type === 'water')
}

export function isWaterDue(item: PlantCareStatus): boolean {
  return waterTasks(item).some(task => task.due_today || task.overdue)
}

// ── KI-Pflegevorschlag → Pflegeaufgaben ──

/** Umtopf-Intervall der KI kommt in Monaten, Pflegeaufgaben rechnen in Tagen. */
export const DAYS_PER_MONTH = 30
const MAX_INTERVAL_DAYS = 3650
const MAX_CARE_NOTES = 2000

export interface AdviceTask {
  care_type: 'water' | 'fertilize' | 'repot'
  interval_days: number
}

/** Bestehende Aufgabe, deren Intervall der Vorschlag ändert (alt → neu, PD-P5). */
export interface AdviceUpdate {
  id: string
  care_type: AdviceTask['care_type']
  from: number
  interval_days: number
}

export interface AdvicePlan {
  create: AdviceTask[]
  update: AdviceUpdate[]
}

function validDays(value: number | null | undefined): number | null {
  if (value == null || !Number.isFinite(value)) return null
  const days = Math.round(value)
  return days >= 1 && days <= MAX_INTERVAL_DAYS ? days : null
}

/** Aufgaben, die der Vorschlag hergibt. `null`-Intervalle ("nicht nötig") ergeben keine Aufgabe. */
export function adviceTasks(advice: Pick<AiPlantCareAdvice, 'watering_interval_days' | 'fertilizing_interval_days' | 'repotting_interval_months'>): AdviceTask[] {
  const months = advice.repotting_interval_months
  const candidates: [AdviceTask['care_type'], number | null][] = [
    ['water', validDays(advice.watering_interval_days)],
    ['fertilize', validDays(advice.fertilizing_interval_days)],
    ['repot', validDays(months == null ? null : months * DAYS_PER_MONTH)],
  ]
  return candidates
    .filter((c): c is [AdviceTask['care_type'], number] => c[1] !== null)
    .map(([care_type, interval_days]) => ({ care_type, interval_days }))
}

/**
 * Vorschlag gegen bestehende Aufgaben abgleichen: gleiche Pflegeart (ohne eigenes
 * Label) wird aktualisiert, falls das Intervall abweicht, sonst neu angelegt.
 */
export function planAdvice(
  advice: Parameters<typeof adviceTasks>[0],
  existing: Pick<PlantCareTask, 'id' | 'care_type' | 'label' | 'interval_days'>[],
): AdvicePlan {
  const plan: AdvicePlan = { create: [], update: [] }
  for (const task of adviceTasks(advice)) {
    const match = existing.find(e => e.care_type === task.care_type && !e.label?.trim())
    if (!match) plan.create.push(task)
    else if (match.interval_days !== task.interval_days) {
      plan.update.push({
        id: match.id, care_type: task.care_type, from: match.interval_days, interval_days: task.interval_days,
      })
    }
  }
  return plan
}

/** Stabiler Schlüssel eines Plan-Eintrags — für die Auswahl in der Vorschau (PD-P5). */
export function adviceKey(item: AdviceTask | AdviceUpdate): string {
  return 'id' in item ? `update:${item.id}` : `create:${item.care_type}`
}

/** Alle Einträge des Plans in Anzeigereihenfolge (Anpassungen zuerst). */
export function planItems(plan: AdvicePlan): (AdviceTask | AdviceUpdate)[] {
  return [...plan.update, ...plan.create]
}

/**
 * Nur die ausgewählten Einträge übernehmen (`selected` = Schlüssel aus `adviceKey`).
 * Ohne Auswahl → alles. Ein Eintrag, der sich seit der Vorschau geändert hat
 * (z. B. inzwischen angelegte Aufgabe), hat einen anderen Schlüssel und wird nicht übernommen.
 */
export function selectPlan(plan: AdvicePlan, selected?: Iterable<string> | null): AdvicePlan {
  if (!selected) return plan
  const keys = new Set(selected)
  return {
    create: plan.create.filter(item => keys.has(adviceKey(item))),
    update: plan.update.filter(item => keys.has(adviceKey(item))),
  }
}

/** Pflegehinweise an bestehenden Text anhängen (nie überschreiben), auf das Feldlimit gekürzt. */
export function mergeCareNotes(existing: string | null | undefined, adviceNotes: string): string {
  const current = existing?.trim() ?? ''
  const addition = adviceNotes.trim()
  if (!addition || current.includes(addition)) return current
  const merged = current ? `${current}\n\n${addition}` : addition
  return merged.slice(0, MAX_CARE_NOTES)
}
