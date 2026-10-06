import type { PlantCareStatus, PlantCareStatusTask, PlantCareTask } from '../types'

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
