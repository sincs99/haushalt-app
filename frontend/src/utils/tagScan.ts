/**
 * Ablauf-Logik für gescannte Tags (Route /t/:token), ohne Vue-Abhängigkeiten.
 *
 * TagScanView ruft resolve auf und entscheidet hier, ob direkt navigiert,
 * eine Bestätigung gezeigt oder ein Hinweis angezeigt wird.
 */
import type { TagExecuteParams, TagResolveResult, TagTargetOption } from '../types'

export type ScanErrorKind =
  | 'not_found'
  | 'target_missing'
  | 'forbidden'
  | 'disabled'
  | 'unsupported'
  | 'already_done'
  | 'nothing_to_do'
  | 'stale'
  | 'rate_limited'
  | 'offline'
  | 'unknown'

export type ScanStep =
  | { kind: 'navigate'; to: string; switchHouseholdTo: string | null }
  | { kind: 'confirm'; switchHouseholdTo: string | null }
  | { kind: 'blocked'; reason: string }

/** Nur App-interne Pfade zulassen (kein //host, kein Schema) — Schutz vor Open Redirects. */
export function safeInternalPath(path: string | null | undefined): string | null {
  if (!path || !path.startsWith('/')) return null
  if (path.startsWith('//') || path.startsWith('/\\')) return null
  return path
}

export function nextScanStep(result: TagResolveResult, currentHouseholdId: string | null): ScanStep {
  const switchHouseholdTo = result.household_id !== currentHouseholdId ? result.household_id : null
  if (result.navigate_only) {
    return {
      kind: 'navigate',
      to: safeInternalPath(result.navigate_to) ?? '/dashboard',
      switchHouseholdTo,
    }
  }
  if (!result.can_execute) {
    return { kind: 'blocked', reason: result.reason ?? 'UNKNOWN' }
  }
  return { kind: 'confirm', switchHouseholdTo }
}

export function scanErrorKind(err: any): ScanErrorKind {
  const response = err?.response
  if (!response) return 'offline'
  const code: string | undefined = response.data?.detail?.code
  switch (response.status) {
    case 404:
      return code === 'TAG_TARGET_NOT_FOUND' ? 'target_missing' : 'not_found'
    case 403:
      return 'forbidden'
    case 410:
      return 'disabled'
    case 409:
      if (code === 'TAG_CONFIRMATION_STALE') return 'stale'
      return code === 'FEEDING_DUPLICATE' ? 'already_done' : 'nothing_to_do'
    case 422:
      return code === 'TAG_ACTION_INVALID' || code === 'TAG_NOT_EXECUTABLE' ? 'unsupported' : 'unknown'
    case 429:
      return 'rate_limited'
    default:
      return 'unknown'
  }
}

/**
 * Parameter für execute: die Bestätigung aus resolve (welche Zuweisung bzw.
 * welche Gießaufgaben angezeigt wurden, CASA-18) und beim Füttern der Slot.
 */
export function executeParams(result: TagResolveResult, slot: 'morning' | 'evening'): TagExecuteParams {
  const params: TagExecuteParams = {}
  if (result.action === 'pet.feed') params.slot = slot
  if (result.confirm) params.confirm = result.confirm
  return params
}

/** URL, die auf Chip bzw. QR-Code kommt. */
export function tagUrl(token: string, origin: string): string {
  return `${origin.replace(/\/+$/, '')}/t/${token}`
}

/** Fütterungs-Slot, den die Bestätigungsseite vorschlägt (vom Server nach Tageszeit). */
export function suggestedSlot(result: TagResolveResult): 'morning' | 'evening' {
  return result.details?.slot === 'evening' ? 'evening' : 'morning'
}

/** Zeilen der Gieß-Bestätigung: aus den care-status-Daten des Servers (ein Ziel oder alle). */
export function plantWaterLines(
  details: Record<string, any>,
  single: boolean,
): { kind: 'lastWatered' | 'neverWatered' | 'plantDue' | 'dueCount'; value?: string | number }[] {
  if (single) {
    const lines: ReturnType<typeof plantWaterLines> = [
      details.last_watered_at
        ? { kind: 'lastWatered', value: details.last_watered_at }
        : { kind: 'neverWatered' },
    ]
    if (details.next_due_at) lines.push({ kind: 'plantDue', value: details.next_due_at })
    return lines
  }
  return typeof details.due_count === 'number' ? [{ kind: 'dueCount', value: details.due_count }] : []
}

/** Wohin „Ansehen“ nach erfolgreicher Aktion führt. */
export function moduleRouteFor(result: Pick<TagResolveResult, 'action' | 'details'>): string {
  switch (result.action) {
    case 'pet.feed':
      return '/pets'
    case 'pet.care_task.done':
      return result.details?.pet_id ? `/pets/${result.details.pet_id}` : '/pets'
    case 'plant.water':
      // Ein Ziel → Pflanze; ohne Ziel (alle fälligen) → Übersicht
      return result.details?.plant_id ? `/plants/${result.details.plant_id}` : '/plants'
    case 'plant.care_task.done':
      return result.details?.plant_id ? `/plants/${result.details.plant_id}` : '/plants'
    case 'chore.assignment.done':
      return '/chores'
    case 'todo.done':
      return '/todos'
    default:
      return '/dashboard'
  }
}

type Translate = (key: string) => string

/**
 * Anzeigename eines Tag-Ziels (Liste, Scan, Ergebnis). Pflegeaufgaben ohne eigene
 * Bezeichnung liefert das Backend als Schlüssel ``target_care_type`` — übersetzt wie in
 * der Pflanzenansicht; ``target_name`` (deutsch) bleibt Fallback für ältere Clients (CASA-59).
 */
export function localizedTargetName(
  r: { target_name: string | null; target_care_type?: string | null },
  t: Translate,
): string | null {
  if (r.target_care_type) return t(`plants.careTypes.${r.target_care_type}`)
  return r.target_name
}

/** Eintrag im Ziel-Dropdown: „Pflanze – Pflegeart“ übersetzt, sonst ``name`` */
export function localizedTargetOption(opt: TagTargetOption, t: Translate): string {
  if (opt.care_type && opt.plant_name) return `${opt.plant_name} – ${t(`plants.careTypes.${opt.care_type}`)}`
  return opt.name
}
