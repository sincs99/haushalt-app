<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCalendarStore } from '../stores/calendar'
import { usePollsStore } from '../stores/polls'
import { useAuthStore } from '../stores/auth'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import { DEFAULT_CALENDAR_PALETTE } from '../utils/categoryColors'
import { expandEventToDays, eventTime, eventDate } from '../utils/dates'
import type { ExpandedEventDay } from '../utils/dates'
import type { CalendarEvent, CalendarEventCreatePayload, CalendarInfo, EventPoll } from '../types'
import CalendarMonthGrid from '../components/CalendarMonthGrid.vue'

interface DisplayEvent extends CalendarEvent {
  /** Nur gesetzt bei mehrtägigen Events: "Tag 2/3" */
  spanBadge?: string
}

import BasePillTabs from '../components/ui/BasePillTabs.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseAvatar from '../components/ui/BaseAvatar.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import {
  PhPlus,
  PhCaretLeft,
  PhCaretRight,
  PhCalendarBlank,
  PhTrash,
  PhGear,
} from '@phosphor-icons/vue'

const { t, locale } = useI18n()
const store = useCalendarStore()
const pollsStore = usePollsStore()
const authStore = useAuthStore()
const { on, off, onReconnect, offReconnect } = useSocket()
const { notifyError, notifySuccess } = useToast()
const { run, isPending } = useAsyncAction()

// ── Tabs ──
const activeTab = ref<'week' | 'month' | 'list'>('week')
const tabs = computed(() => [
  { key: 'week', label: t('calendar.viewWeek') },
  { key: 'month', label: t('calendar.viewMonth') },
  { key: 'list', label: t('calendar.list') },
])

// ── Tab Persistence ──
const VIEW_STORAGE_KEY = computed(() => `calendar-view-${authStore.currentHouseholdId}`)

// ── Month State ──
const currentMonthDate = ref(new Date())

function getMonthGridRange(year: number, month: number): { from: string; to: string } {
  const firstOfMonth = new Date(year, month, 1)
  const dayOfWeek = firstOfMonth.getDay()
  const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek
  const gridStart = new Date(firstOfMonth)
  gridStart.setDate(gridStart.getDate() + diffToMonday)

  const lastOfMonth = new Date(year, month + 1, 0)
  const lastDow = lastOfMonth.getDay()
  const diffToSunday = lastDow === 0 ? 0 : 7 - lastDow
  const gridEnd = new Date(lastOfMonth)
  gridEnd.setDate(gridEnd.getDate() + diffToSunday)

  return { from: formatDateLocal(gridStart), to: formatDateLocal(gridEnd) }
}

// Welcher Bereich zuletzt geladen wurde (die Liste zeigt diesen Bereich)
const loadedRange = ref<'week' | 'month'>('week')

function loadMonthEvents() {
  const range = getMonthGridRange(currentMonthDate.value.getFullYear(), currentMonthDate.value.getMonth())
  loadedRange.value = 'month'
  return store.fetchEvents(range.from, range.to)
}

function loadWeekEvents() {
  loadedRange.value = 'week'
  return store.fetchEvents()
}

/** Termine passend zur aktiven Ansicht neu laden (Monat nicht mit der Woche überschreiben) */
function reloadVisibleEvents() {
  if (activeTab.value === 'month') return loadMonthEvents()
  if (activeTab.value === 'week') return loadWeekEvents()
  return loadedRange.value === 'month' ? loadMonthEvents() : loadWeekEvents()
}

/** Nachladen im Hintergrund (Navigation, Tabwechsel): Fehler als Toast statt still */
function refreshEvents(load: () => Promise<unknown>) {
  load().catch((err) => notifyError(t('common.loadError'), err))
}

function handleMonthNavigate(offset: number) {
  const d = new Date(currentMonthDate.value)
  d.setMonth(d.getMonth() + offset)
  currentMonthDate.value = d
  refreshEvents(loadMonthEvents)
}

function handleGoToday() {
  currentMonthDate.value = new Date()
  refreshEvents(loadMonthEvents)
}

function handleWeekNavigate(offset: number) {
  // Statt store.navigateWeek (lädt ohne Fehlerbehandlung) selbst nachladen
  store.currentWeekStart = addDaysToDate(store.currentWeekStart, offset * 7)
  refreshEvents(loadWeekEvents)
}

watch(activeTab, (newTab) => {
  localStorage.setItem(VIEW_STORAGE_KEY.value, newTab)
  if (newTab === 'month') {
    refreshEvents(loadMonthEvents)
  } else if (newTab === 'week') {
    refreshEvents(loadWeekEvents)
  }
})

/** Liegt ein Termin (Startdatum, Kalender) in der aktuell sichtbaren Ansicht? */
function isVisibleInView(dateStr: string, calendarId: string): boolean {
  if (!activeCalendarIds.value.includes(calendarId)) return false
  const range = activeTab.value === 'month' || (activeTab.value === 'list' && loadedRange.value === 'month')
    ? getMonthGridRange(currentMonthDate.value.getFullYear(), currentMonthDate.value.getMonth())
    : { from: store.currentWeekStart, to: addDaysToDate(store.currentWeekStart, 6) }
  return dateStr >= range.from && dateStr <= range.to
}

// ── Calendar Filter ──
const STORAGE_KEY = computed(() => `calendar-filter-${authStore.currentHouseholdId}`)
const activeCalendarIds = ref<string[]>([])

function initCalendarFilter() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY.value)
    if (stored) {
      activeCalendarIds.value = JSON.parse(stored)
    } else {
      // Default: alle aktiv
      activeCalendarIds.value = store.calendars.map((c: CalendarInfo) => c.id)
    }
  } catch {
    activeCalendarIds.value = store.calendars.map((c: CalendarInfo) => c.id)
  }
}

// Watcher: Stale Calendar-IDs entfernen + neue IDs automatisch aktivieren (BUG-2 / BUG-6)
watch(
  () => store.calendars,
  (newCalendars) => {
    const validIds = new Set(newCalendars.map((c: CalendarInfo) => c.id))

    // 1. Gelöschte IDs entfernen
    const cleaned = activeCalendarIds.value.filter(id => validIds.has(id))

    // 2. Neue IDs automatisch hinzufügen (die noch nicht im Filter sind)
    const currentSet = new Set(cleaned)
    for (const cal of newCalendars) {
      if (!currentSet.has(cal.id)) {
        cleaned.push(cal.id)
      }
    }

    // 3. Falls leer, alle aktivieren
    if (cleaned.length === 0 && newCalendars.length > 0) {
      activeCalendarIds.value = newCalendars.map((c: CalendarInfo) => c.id)
    } else {
      activeCalendarIds.value = cleaned
    }

    localStorage.setItem(STORAGE_KEY.value, JSON.stringify(activeCalendarIds.value))
  },
  { deep: true },
)

function toggleCalendarFilter(calId: string) {
  const idx = activeCalendarIds.value.indexOf(calId)
  if (idx !== -1) {
    // Nicht den letzten deaktivieren
    if (activeCalendarIds.value.length > 1) {
      activeCalendarIds.value.splice(idx, 1)
    }
  } else {
    activeCalendarIds.value.push(calId)
  }
  localStorage.setItem(STORAGE_KEY.value, JSON.stringify(activeCalendarIds.value))
}

// ── Selected Day ──
const selectedDay = ref<string>('')

// ── Filtered events helper ──
const filteredEvents = computed(() =>
  store.events.filter((e: CalendarEvent) => activeCalendarIds.value.includes(e.calendar_id)),
)

// ── Wochenstreifen ──
const weekDays = computed(() => {
  const start = store.currentWeekStart
  const days: { date: string; short: string; num: number; isToday: boolean }[] = []
  const todayStr = formatDateLocal(new Date())
  const dayLabels = locale.value === 'de'
    ? ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    : ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

  for (let i = 0; i < 7; i++) {
    const d = addDaysToDate(start, i)
    const dateObj = new Date(d + 'T00:00:00')
    days.push({
      date: d,
      short: dayLabels[i],
      num: dateObj.getDate(),
      isToday: d === todayStr,
    })
  }
  return days
})

// ── Week Header ──
const weekLabel = computed(() => {
  if (weekDays.value.length === 0) return ''
  const first = weekDays.value[0]
  const last = weekDays.value[6]
  const fDate = new Date(first.date + 'T00:00:00')
  const lDate = new Date(last.date + 'T00:00:00')
  const fMonth = fDate.toLocaleDateString(locale.value === 'de' ? 'de-CH' : 'en-US', { month: 'short' })
  const lMonth = lDate.toLocaleDateString(locale.value === 'de' ? 'de-CH' : 'en-US', { month: 'short' })
  if (fMonth === lMonth) {
    return `${first.num}.–${last.num}. ${fMonth} ${fDate.getFullYear()}`
  }
  return `${first.num}. ${fMonth} – ${last.num}. ${lMonth} ${lDate.getFullYear()}`
})

// ── Calendar color dots for a day ──
function calendarDotsForDay(dateStr: string): string[] {
  const dayEvents = filteredEvents.value.filter((e: CalendarEvent) => {
    const days = expandEventToDays(e.starts_at, e.ends_at)
    return days.some((d: ExpandedEventDay) => d.date === dateStr)
  })
  const uniqueCalendarIds = [...new Set(dayEvents.map((e: CalendarEvent) => e.calendar_id))]
  return uniqueCalendarIds.slice(0, 3).map((calId: string) => store.getCalendarColor(calId))
}

// ── Events grouped by date (for week view) ──
const eventsGroupedByDate = computed(() => {
  const groups: { date: string; label: string; events: DisplayEvent[] }[] = []
  const todayStr = formatDateLocal(new Date())
  const tomorrowStr = addDaysToDate(todayStr, 1)

  for (const day of weekDays.value) {
    const dayEvents: DisplayEvent[] = []

    for (const event of filteredEvents.value) {
      const expandedDays = expandEventToDays(event.starts_at, event.ends_at)
      const match = expandedDays.find((d: ExpandedEventDay) => d.date === day.date)
      if (match) {
        const displayEvent: DisplayEvent = { ...event }
        if (match.totalDays > 1) {
          displayEvent.spanBadge = t('calendar.dayOfSpan', { current: match.dayIndex, total: match.totalDays })
        }
        dayEvents.push(displayEvent)
      }
    }

    // Sortierung: all_day zuerst, dann nach starts_at
    dayEvents.sort((a, b) => {
      if (a.all_day && !b.all_day) return -1
      if (!a.all_day && b.all_day) return 1
      return a.starts_at.localeCompare(b.starts_at)
    })

    if (dayEvents.length === 0) continue

    let label: string
    if (day.date === todayStr) {
      label = `${t('calendar.today')} — ${formatDayHeader(day.date)}`
    } else if (day.date === tomorrowStr) {
      label = `${t('calendar.tomorrow')} — ${formatDayHeader(day.date)}`
    } else {
      label = `${formatWeekdayShort(day.date)} — ${formatDayHeader(day.date)}`
    }

    groups.push({ date: day.date, label, events: dayEvents })
  }
  return groups
})

// ── All events chronologically (for list view) ──
const allEventsSorted = computed(() => {
  const result: DisplayEvent[] = []
  for (const event of filteredEvents.value) {
    const expandedDays = expandEventToDays(event.starts_at, event.ends_at)
    if (expandedDays.length <= 1) {
      result.push({ ...event })
    } else {
      // Mehrtägiges Event: nur einmal anzeigen, aber mit Badge
      const displayEvent: DisplayEvent = { ...event }
      displayEvent.spanBadge = t('calendar.dayOfSpan', { current: 1, total: expandedDays.length })
      result.push(displayEvent)
    }
  }
  return result.sort((a, b) => {
    if (a.all_day && !b.all_day) return -1
    if (!a.all_day && b.all_day) return 1
    return a.starts_at.localeCompare(b.starts_at)
  })
})

// ── Date formatting helpers ──
function formatDateLocal(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function addDaysToDate(dateStr: string, days: number): string {
  const d = new Date(dateStr + 'T00:00:00')
  d.setDate(d.getDate() + days)
  return formatDateLocal(d)
}

function formatDayHeader(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString(locale.value === 'de' ? 'de-CH' : 'en-US', {
    day: 'numeric',
    month: 'short',
  })
}

function formatWeekdayShort(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString(locale.value === 'de' ? 'de-CH' : 'en-US', {
    weekday: 'short',
  })
}

function formatTime(isoStr: string): string {
  // Haushaltszeit direkt aus dem String (siehe utils/dates eventTime)
  return eventTime(isoStr)
}

function getParticipantNames(event: CalendarEvent): string {
  if (event.participant_ids.length === 0) {
    return `${t('calendar.everyone')} (${store.members.length})`
  }
  const names = event.participant_ids
    .map((id: string) => {
      const member = store.members.find(m => m.id === id)
      return member?.display_name ?? t('common.unknown')
    })
    .slice(0, 3)
  if (event.participant_ids.length > 3) {
    return names.join(', ') + ` +${event.participant_ids.length - 3}`
  }
  return names.join(', ')
}

function getParticipantAvatars(event: CalendarEvent) {
  if (event.participant_ids.length === 0) {
    // Alle Mitglieder
    return {
      avatars: store.members.slice(0, 3).map(m => ({ id: m.id, name: m.display_name })),
      extra: store.members.length > 3 ? store.members.length - 3 : 0,
      isEveryone: true,
    }
  }
  const avatars = event.participant_ids.slice(0, 3).map((id: string) => {
    const member = store.members.find(m => m.id === id)
    return { id, name: member?.display_name ?? '?' }
  })
  return {
    avatars,
    extra: event.participant_ids.length > 3 ? event.participant_ids.length - 3 : 0,
    isEveryone: false,
  }
}

// ── Day refs for scroll ──
const dayRefs = ref<Record<string, HTMLElement | null>>({})

function setDayRef(date: string, el: HTMLElement | null) {
  dayRefs.value[date] = el
}

function scrollToDay(date: string) {
  selectedDay.value = date
  nextTick(() => {
    const el = dayRefs.value[date]
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  })
}

// ── Dialog State ──
const dialogOpen = ref(false)
const editingEvent = ref<CalendarEvent | null>(null)
const formTitle = ref('')
const formDate = ref('')
const formAllDay = ref(false)
const formStartTime = ref('09:00')
const formEndTime = ref('10:00')
const formCalendarId = ref<string>('')
const formParticipants = ref<string[]>([])
const formNote = ref('')
const formEndDate = ref('')
const formEndDateError = ref('')
const EVENT_FORM_ID = 'calendar-event-form'
const DECIDE_FORM_ID = 'calendar-decide-form'

function openCreateDialog() {
  editingEvent.value = null
  formTitle.value = ''
  // Default: heute oder selectedDay
  formDate.value = selectedDay.value || formatDateLocal(new Date())
  formEndDate.value = formDate.value  // Default: Enddatum = Startdatum
  formEndDateError.value = ''
  formAllDay.value = false
  formStartTime.value = '09:00'
  formEndTime.value = '10:00'
  formCalendarId.value = localStorage.getItem('last-calendar-' + authStore.currentHouseholdId) || store.calendars[0]?.id || ''
  formParticipants.value = []
  formNote.value = ''
  dialogOpen.value = true
}

function openEditDialog(event: CalendarEvent) {
  editingEvent.value = event
  formTitle.value = event.title
  formDate.value = eventDate(event.starts_at)
  formEndDate.value = event.ends_at ? eventDate(event.ends_at) : formDate.value
  formEndDateError.value = ''
  formAllDay.value = event.all_day
  if (!event.all_day) {
    formStartTime.value = formatTime(event.starts_at)
    formEndTime.value = event.ends_at ? formatTime(event.ends_at) : ''
  } else {
    formStartTime.value = '09:00'
    formEndTime.value = '10:00'
  }
  formCalendarId.value = event.calendar_id
  formParticipants.value = [...event.participant_ids]
  formNote.value = event.note ?? ''
  dialogOpen.value = true
}

function closeDialog() {
  dialogOpen.value = false
  editingEvent.value = null
}

function toggleParticipant(userId: string) {
  const idx = formParticipants.value.indexOf(userId)
  if (idx !== -1) {
    formParticipants.value.splice(idx, 1)
  } else {
    formParticipants.value.push(userId)
  }
}

async function submitForm() {
  if (!formTitle.value.trim() || !formCalendarId.value) return

  // Validierung: Enddatum >= Startdatum
  if (formEndDate.value && formEndDate.value < formDate.value) {
    formEndDateError.value = t('calendar.endBeforeStart')
    return
  }
  formEndDateError.value = ''

  const startsAt = formAllDay.value
    ? `${formDate.value}T00:00:00`
    : `${formDate.value}T${formStartTime.value}:00`

  const effectiveEndDate = formEndDate.value || formDate.value

  const endsAt = formAllDay.value
    ? (effectiveEndDate !== formDate.value ? `${effectiveEndDate}T23:59:00` : null)
    : formEndTime.value
      ? `${effectiveEndDate}T${formEndTime.value}:00`
      : null

  const payload: CalendarEventCreatePayload = {
    title: formTitle.value.trim(),
    starts_at: startsAt,
    ends_at: endsAt,
    all_day: formAllDay.value,
    calendar_id: formCalendarId.value,
    participant_ids: formParticipants.value,
    note: formNote.value.trim() || null,
  }
  const editing = editingEvent.value
  const ok = await run(
    () => editing ? store.updateEvent(editing.id, payload) : store.addEvent(payload),
    {
      key: 'event-form',
      // Termin ausserhalb der sichtbaren Woche/des Monats (oder im ausgeblendeten
      // Kalender): sonst passiert sichtbar nichts
      success: () => isVisibleInView(formDate.value, payload.calendar_id)
        ? undefined
        : t('calendar.savedOn', { date: formatDayHeader(formDate.value) }),
      error: editing ? t('calendar.updateError') : t('calendar.addError'),
    },
  )
  if (!ok) return
  // Letzten Kalender merken
  localStorage.setItem('last-calendar-' + authStore.currentHouseholdId, payload.calendar_id)
  closeDialog()
}

/** Termin löschen: sofort, mit „Rückgängig“ statt Bestätigungsdialog */
async function handleDelete() {
  const event = editingEvent.value
  if (!event) return
  closeDialog()
  await run(() => store.deleteEvent(event.id), {
    key: `event-delete-${event.id}`,
    success: t('calendar.deleted'),
    // Rückgängig legt den Termin neu an (Zeiten in Haushaltszeit, ohne Offset)
    undo: () => store.addEvent({
      title: event.title,
      starts_at: event.starts_at.substring(0, 19),
      ends_at: event.ends_at ? event.ends_at.substring(0, 19) : null,
      all_day: event.all_day,
      calendar_id: event.calendar_id,
      participant_ids: [...event.participant_ids],
      note: event.note,
    }),
    error: t('calendar.deleteError'),
  })
}

// ── Poll Helpers ──
function isMyVote(poll: EventPoll, optionId: string): boolean {
  const userId = authStore.user?.id
  if (!userId) return false
  return poll.options
    .find(o => o.id === optionId)
    ?.votes.some(v => v.user_id === userId) ?? false
}

function getMemberName(userId: string): string {
  const member = store.members.find(m => m.id === userId)
  return member?.display_name ?? '?'
}

// Termin-Abstimmungen; Essens-Abstimmungen gehören zum Wochenplan
const openEventPolls = computed(() => pollsStore.openPolls.filter(p => p.poll_type !== 'meal'))

async function handleVote(poll: EventPoll, optionId: string) {
  // Gleiche Option nochmals gewählt: nichts zu tun
  if (isMyVote(poll, optionId)) return
  await run(() => pollsStore.votePoll(poll.id, optionId), {
    key: `poll-${poll.id}`,
    error: t('polls.voteError'),
  })
}

// ── Decide-Dialog State ──
const decideDialogOpen = ref(false)
const decidingPoll = ref<EventPoll | null>(null)
const decideEventTitle = ref('')
const decideCalendarId = ref<string>('')
const decideOptionId = ref('')

function openDecideDialog(poll: EventPoll) {
  decidingPoll.value = poll
  decideEventTitle.value = poll.question

  // Die Option mit den meisten Stimmen vorselektieren
  let maxVotes = 0
  let bestOptionId = poll.options[0]?.id ?? ''
  for (const opt of poll.options) {
    if (opt.votes.length > maxVotes) {
      maxVotes = opt.votes.length
      bestOptionId = opt.id
    }
  }
  decideOptionId.value = bestOptionId
  decideCalendarId.value = localStorage.getItem('last-calendar-' + authStore.currentHouseholdId)
    || store.calendars[0]?.id || ''
  decideDialogOpen.value = true
}

function closeDecideDialog() {
  decideDialogOpen.value = false
  decidingPoll.value = null
}

async function submitDecide() {
  const poll = decidingPoll.value
  if (!poll || !decideOptionId.value || !decideEventTitle.value.trim() || !decideCalendarId.value) return

  // Ohne Startzeit legt das Backend den Termin auf jetzt
  const option = poll.options.find(o => o.id === decideOptionId.value)
  const date = option?.starts_at ? eventDate(option.starts_at) : formatDateLocal(new Date())
  const payload = {
    option_id: decideOptionId.value,
    event_title: decideEventTitle.value.trim(),
    calendar_id: decideCalendarId.value,
  }
  const ok = await run(() => pollsStore.decidePoll(poll.id, payload), {
    key: 'poll-decide',
    // Karte verschwindet, der Termin liegt oft ausserhalb der Ansicht → mit Datum melden
    success: t('polls.decidedOn', { date: formatDayHeader(date) }),
    error: t('polls.decideError'),
  })
  if (!ok) return
  closeDecideDialog()
  // Neuer Termin → passend zur aktiven Ansicht nachladen (Monat bleibt Monat)
  refreshEvents(reloadVisibleEvents)
}

// ── Manage Calendars Dialog ──
const manageDialogOpen = ref(false)
const newCalendarName = ref('')
const newCalendarColor = ref('#5B8DEF')

async function handleAddCalendar() {
  const name = newCalendarName.value.trim()
  if (!name) return
  const ok = await run(() => store.addCalendar({ name, color: newCalendarColor.value }), {
    key: 'calendar-add',
    error: t('calendars.saveError'),
  })
  // Name erst nach Erfolg leeren, sonst ist die Eingabe weg
  if (ok) newCalendarName.value = ''
  // Filter-Update wird automatisch vom Watcher auf store.calendars übernommen (BUG-6)
}

async function handleRename(cal: CalendarInfo, input: HTMLInputElement) {
  const newName = input.value.trim()
  if (!newName || newName === cal.name) {
    input.value = cal.name
    return
  }
  const ok = await run(() => store.updateCalendar(cal.id, { name: newName }), {
    key: `calendar-${cal.id}`,
    success: t('calendars.updated'),
    error: t('calendars.saveError'),
  })
  // Bei Fehler den gespeicherten Namen wieder anzeigen
  if (!ok) input.value = cal.name
}

async function handleColorChange(cal: CalendarInfo, event: Event) {
  const input = event.target as HTMLInputElement
  const ok = await run(() => store.updateCalendar(cal.id, { color: input.value }), {
    key: `calendar-color-${cal.id}`,
    error: t('calendars.saveError'),
  })
  if (!ok) input.value = cal.color
}

// Kalender löschen: Bestätigung als Dialog (statt confirm()); der Verwalten-Dialog
// wird solange ausgeblendet, damit nicht zwei Dialoge übereinander liegen
const calendarToDelete = ref<CalendarInfo | null>(null)

function askDeleteCalendar(cal: CalendarInfo) {
  manageDialogOpen.value = false
  calendarToDelete.value = cal
}

function closeDeleteCalendar() {
  calendarToDelete.value = null
  manageDialogOpen.value = true
}

async function confirmDeleteCalendar() {
  const cal = calendarToDelete.value
  if (!cal) return
  // LAST_CALENDAR / CALENDAR_NOT_EMPTY werden über errors.<CODE> übersetzt
  const ok = await run(() => store.deleteCalendar(cal.id), {
    key: `calendar-delete-${cal.id}`,
    error: t('calendars.deleteError'),
  })
  if (ok) {
    // Aus Filter entfernen
    activeCalendarIds.value = activeCalendarIds.value.filter(id => id !== cal.id)
    localStorage.setItem(STORAGE_KEY.value, JSON.stringify(activeCalendarIds.value))
  }
  closeDeleteCalendar()
}

// ── Laden ──
// Alle Requests laufen parallel; scheitert einer, zeigt die Ansicht einen Fehlerzustand
const { loadError, reloading, reload } = useLoader(() => Promise.all([
  reloadVisibleEvents(),
  store.fetchMembers(),
  store.fetchCalendars(),
  pollsStore.fetchPolls('offen'),
]))

// ── Socket-Listener Setup ──
function handleReconnect() {
  // Stilles Nachladen; Fehler zeigt der Fehlerzustand bzw. der nächste Versuch
  reload()
}

onMounted(async () => {
  selectedDay.value = formatDateLocal(new Date())

  // Tab aus localStorage wiederherstellen
  const savedView = localStorage.getItem(VIEW_STORAGE_KEY.value)
  if (savedView && ['week', 'month', 'list'].includes(savedView)) {
    activeTab.value = savedView as typeof activeTab.value
  }

  // Socket-Listener zuerst registrieren — auch wenn das Laden scheitert,
  // bleibt die Echtzeit-Aktualisierung aktiv
  on('event_created', store.handleEventCreated)
  on('event_updated', store.handleEventUpdated)
  on('event_deleted', store.handleEventDeleted)
  on('calendar_created', store.handleCalendarCreated)
  on('calendar_updated', store.handleCalendarUpdated)
  on('calendar_deleted', store.handleCalendarDeleted)
  on('poll_created', pollsStore.handleSocketCreated)
  on('poll_voted', pollsStore.handleSocketVoted)
  on('poll_decided', pollsStore.handleSocketDecided)
  on('poll_deleted', pollsStore.handleSocketDeleted)
  onReconnect(handleReconnect)

  // Events je nach aktiver Ansicht laden
  await reload()

  // Kalender-Filter initialisieren nachdem Kalender geladen
  initCalendarFilter()
})

onUnmounted(() => {
  off('event_created', store.handleEventCreated)
  off('event_updated', store.handleEventUpdated)
  off('event_deleted', store.handleEventDeleted)
  off('calendar_created', store.handleCalendarCreated)
  off('calendar_updated', store.handleCalendarUpdated)
  off('calendar_deleted', store.handleCalendarDeleted)
  off('poll_created', pollsStore.handleSocketCreated)
  off('poll_voted', pollsStore.handleSocketVoted)
  off('poll_decided', pollsStore.handleSocketDecided)
  off('poll_deleted', pollsStore.handleSocketDeleted)
  offReconnect(handleReconnect)
})

// Re-fetch bei Haushaltswechsel
watch(
  () => authStore.currentHouseholdId,
  async () => {
    await reload()
    initCalendarFilter()
  },
)
</script>

<template>
  <div class="calendar-view">
    <PageHeader :title="t('calendar.title')">
      <template #actions>
        <button class="manage-btn" @click="manageDialogOpen = true" :aria-label="t('calendars.manage')">
          <PhGear :size="20" />
        </button>
      </template>
    </PageHeader>

    <!-- PillTabs -->
    <div class="calendar-tabs">
      <BasePillTabs
        :tabs="tabs"
        :model-value="activeTab"
        @update:model-value="activeTab = $event as 'week' | 'month' | 'list'"
      />
    </div>

    <!-- Calendar Filter Chips -->
    <div v-if="store.calendars.length > 0" class="calendar-filter-chips">
      <button
        v-for="cal in store.calendars"
        :key="cal.id"
        class="filter-chip"
        :class="{ 'filter-chip--active': activeCalendarIds.includes(cal.id) }"
        :style="activeCalendarIds.includes(cal.id)
          ? { background: cal.color, color: '#fff', borderColor: cal.color }
          : { borderColor: cal.color, color: cal.color }"
        @click="toggleCalendarFilter(cal.id)"
      >
        {{ cal.name }}
      </button>
    </div>

    <!-- Week Strip (nur im Woche-Modus) -->
    <div v-if="activeTab === 'week'" class="week-nav">
      <div class="week-nav__header">
        <button class="week-nav__arrow" @click="handleWeekNavigate(-1)" :aria-label="t('calendar.prevWeek')">
          <PhCaretLeft :size="20" />
        </button>
        <span class="week-nav__label">{{ weekLabel }}</span>
        <button class="week-nav__arrow" @click="handleWeekNavigate(1)" :aria-label="t('calendar.nextWeek')">
          <PhCaretRight :size="20" />
        </button>
      </div>

      <div class="week-strip">
        <button
          v-for="day in weekDays"
          :key="day.date"
          class="week-strip__day"
          :class="{
            'week-strip__day--today': day.isToday,
            'week-strip__day--selected': selectedDay === day.date && !day.isToday,
          }"
          @click="scrollToDay(day.date)"
        >
          <span class="week-strip__short">{{ day.short }}</span>
          <span class="week-strip__num">{{ day.num }}</span>
          <span class="week-strip__dots">
            <span
              v-for="(color, idx) in calendarDotsForDay(day.date)"
              :key="idx"
              class="week-strip__dot"
              :style="{ background: color }"
            />
          </span>
        </button>
      </div>
    </div>

    <!-- Month Grid -->
    <CalendarMonthGrid
      v-if="activeTab === 'month'"
      :events="filteredEvents"
      :get-calendar-color="store.getCalendarColor"
      :get-calendar-name="store.getCalendarName"
      :members="store.members"
      :selected-date="formatDateLocal(currentMonthDate)"
      :loading="store.loading"
      @select-day="(d: string) => selectedDay = d"
      @create-event="(d: string) => { selectedDay = d; openCreateDialog() }"
      @edit-event="openEditDialog"
      @navigate="handleMonthNavigate"
      @go-today="handleGoToday"
    />

    <!-- Ladefehler: statt fälschlich „Noch keine Termine“ -->
    <BaseErrorState
      v-if="loadError && store.events.length === 0"
      :retrying="reloading"
      @retry="reload"
    />

    <!-- Offene Abstimmungen (nur Termin-Abstimmungen) -->
    <div v-if="openEventPolls.length > 0" class="poll-section">
      <BaseCard v-for="poll in openEventPolls" :key="poll.id" class="poll-card">
        <h3 class="poll-question">{{ poll.question }}</h3>
        <div class="poll-options">
          <button
            v-for="option in poll.options"
            :key="option.id"
            class="poll-option"
            :class="{ 'poll-option--selected': isMyVote(poll, option.id) }"
            :aria-pressed="isMyVote(poll, option.id)"
            :disabled="isPending(`poll-${poll.id}`)"
            @click="handleVote(poll, option.id)"
          >
            <span class="poll-option__label">{{ option.label }}</span>
            <span class="poll-option__votes">
              <BaseAvatar
                v-for="vote in option.votes"
                :key="vote.id"
                :name="getMemberName(vote.user_id)"
                :user-id="vote.user_id"
                size="sm"
              />
              <span v-if="option.votes.length > 0" class="poll-option__count">
                {{ option.votes.length }}
              </span>
            </span>
          </button>
        </div>
        <div class="poll-actions" v-if="poll.status === 'offen'">
          <BaseButton size="sm" variant="primary" @click="openDecideDialog(poll)">
            {{ t('polls.decide') }}
          </BaseButton>
        </div>
      </BaseCard>
    </div>

    <!-- Event List — Woche (gruppiert nach Tag) -->
    <div v-if="activeTab === 'week'" class="event-list">
      <!-- Skeleton beim ersten Laden -->
      <div v-if="store.loading && store.events.length === 0" class="event-list__cards" aria-hidden="true">
        <BaseSkeleton v-for="n in 3" :key="n" width="100%" height="64px" />
      </div>
      <template v-else-if="eventsGroupedByDate.length === 0 && !store.loading && !loadError">
        <BaseEmptyState
          :icon="PhCalendarBlank"
          :title="t('calendar.noEvents')"
        >
          <template #action>
            <BaseButton size="sm" variant="secondary" @click="openCreateDialog">
              {{ t('calendar.newEvent') }}
            </BaseButton>
          </template>
        </BaseEmptyState>
      </template>

      <div
        v-for="group in eventsGroupedByDate"
        :key="group.date"
        :ref="(el) => setDayRef(group.date, el as HTMLElement | null)"
      >
        <h3 class="event-list__date-header">{{ group.label }}</h3>
        <div class="event-list__cards">
          <BaseCard
            v-for="event in group.events"
            :key="event.id"
            padding="sm"
            class="event-card"
            role="button"
            tabindex="0"
            @click="openEditDialog(event)"
            @keydown.enter.prevent="openEditDialog(event)"
            @keydown.space.prevent="openEditDialog(event)"
          >
            <span
              class="event-card__bar"
              :style="{ background: store.getCalendarColor(event.calendar_id) }"
            />
            <div class="event-card__body">
              <div class="event-card__content">
                <span class="event-card__time">
                  {{ event.all_day ? t('calendar.allDay') : formatTime(event.starts_at) }}
                  <span v-if="event.spanBadge" class="event-card__span-badge">
                    {{ event.spanBadge }}
                  </span>
                </span>
                <span class="event-card__title">{{ event.title }}</span>
                <span class="event-card__meta">
                  {{ store.getCalendarName(event.calendar_id) }}
                  · {{ getParticipantNames(event) }}
                </span>
              </div>
              <div class="event-card__avatars">
                <template v-if="getParticipantAvatars(event).isEveryone">
                  <span class="event-card__everyone-chip">
                    {{ t('calendar.everyone') }}
                  </span>
                </template>
                <template v-else>
                  <BaseAvatar
                    v-for="av in getParticipantAvatars(event).avatars"
                    :key="av.id"
                    :name="av.name"
                    :user-id="av.id"
                    size="sm"
                  />
                  <span
                    v-if="getParticipantAvatars(event).extra > 0"
                    class="event-card__extra"
                  >
                    +{{ getParticipantAvatars(event).extra }}
                  </span>
                </template>
              </div>
            </div>
          </BaseCard>
        </div>
      </div>
    </div>

    <!-- Event List — Liste (chronologisch) -->
    <div v-if="activeTab === 'list'" class="event-list">
      <div v-if="store.loading && store.events.length === 0" class="event-list__cards" aria-hidden="true">
        <BaseSkeleton v-for="n in 3" :key="n" width="100%" height="64px" />
      </div>
      <template v-else-if="allEventsSorted.length === 0 && !store.loading && !loadError">
        <BaseEmptyState
          :icon="PhCalendarBlank"
          :title="t('calendar.emptyTitle')"
          :subtitle="t('calendar.emptySubtitle')"
        >
          <template #action>
            <BaseButton size="sm" variant="secondary" @click="openCreateDialog">
              {{ t('calendar.newEvent') }}
            </BaseButton>
          </template>
        </BaseEmptyState>
      </template>

      <div class="event-list__cards">
        <BaseCard
          v-for="event in allEventsSorted"
          :key="event.id"
          padding="sm"
          class="event-card"
          role="button"
          tabindex="0"
          @click="openEditDialog(event)"
          @keydown.enter.prevent="openEditDialog(event)"
          @keydown.space.prevent="openEditDialog(event)"
        >
          <span
            class="event-card__bar"
            :style="{ background: store.getCalendarColor(event.calendar_id) }"
          />
          <div class="event-card__body">
            <div class="event-card__content">
              <span class="event-card__time">
                {{ event.all_day ? t('calendar.allDay') : formatTime(event.starts_at) }}
                <span class="event-card__date-badge">
                  {{ formatDayHeader(eventDate(event.starts_at)) }}
                </span>
                <span v-if="event.spanBadge" class="event-card__span-badge">
                  {{ event.spanBadge }}
                </span>
              </span>
              <span class="event-card__title">{{ event.title }}</span>
              <span class="event-card__meta">
                {{ store.getCalendarName(event.calendar_id) }}
                · {{ getParticipantNames(event) }}
              </span>
            </div>
            <div class="event-card__avatars">
              <template v-if="getParticipantAvatars(event).isEveryone">
                <span class="event-card__everyone-chip">
                  {{ t('calendar.everyone') }}
                </span>
              </template>
              <template v-else>
                <BaseAvatar
                  v-for="av in getParticipantAvatars(event).avatars"
                  :key="av.id"
                  :name="av.name"
                  :user-id="av.id"
                  size="sm"
                />
                <span
                  v-if="getParticipantAvatars(event).extra > 0"
                  class="event-card__extra"
                >
                  +{{ getParticipantAvatars(event).extra }}
                </span>
              </template>
            </div>
          </div>
        </BaseCard>
      </div>
    </div>

    <!-- FAB -->
    <button class="fab" @click="openCreateDialog" :aria-label="t('calendar.newEvent')">
      <PhPlus :size="24" weight="bold" />
    </button>

    <!-- Create / Edit Dialog -->
    <BaseDialog
      :open="dialogOpen"
      :title="editingEvent ? t('calendar.editEvent') : t('calendar.newEvent')"
      @close="closeDialog"
    >
      <form :id="EVENT_FORM_ID" class="event-form" @submit.prevent="submitForm">
        <!-- Titel -->
        <BaseInput
          :model-value="formTitle"
          @update:model-value="formTitle = $event"
          :label="t('calendar.titleLabel')"
          :placeholder="t('calendar.titlePlaceholder')"
        />

        <!-- Datum -->
        <div class="form-field">
          <label class="form-label" for="event-date">{{ t('calendar.dateLabel') }}</label>
          <input
            id="event-date"
            v-model="formDate"
            type="date"
            class="form-input"
          />
        </div>

        <!-- Enddatum -->
        <div class="form-field">
          <label class="form-label" for="event-end-date">{{ t('calendar.endDate') }}</label>
          <input
            id="event-end-date"
            v-model="formEndDate"
            type="date"
            class="form-input"
            :class="{ 'form-input--error': formEndDateError }"
            :min="formDate"
          />
          <p v-if="formEndDateError" class="form-error">{{ formEndDateError }}</p>
        </div>

        <!-- Ganztägig Toggle -->
        <div class="form-field form-field--toggle">
          <label class="form-label">{{ t('calendar.allDayToggle') }}</label>
          <label class="toggle">
            <input v-model="formAllDay" type="checkbox" class="toggle__input" />
            <span class="toggle__slider" />
          </label>
        </div>

        <!-- Start / End Zeit (nur wenn nicht ganztägig) -->
        <div v-if="!formAllDay" class="form-row">
          <div class="form-field form-field--half">
            <label class="form-label" for="event-start-time">{{ t('calendar.startTime') }}</label>
            <input id="event-start-time" v-model="formStartTime" type="time" class="form-input" />
          </div>
          <div class="form-field form-field--half">
            <label class="form-label" for="event-end-time">{{ t('calendar.endTime') }}</label>
            <input id="event-end-time" v-model="formEndTime" type="time" class="form-input" />
          </div>
        </div>

        <!-- Kalender (Pflichtfeld) -->
        <div class="form-field">
          <label class="form-label">{{ t('calendar.calendarLabel') }}</label>
          <div class="category-chips">
            <button
              v-for="cal in store.calendars"
              :key="cal.id"
              type="button"
              class="category-chip"
              :class="{ 'category-chip--active': formCalendarId === cal.id }"
              @click="formCalendarId = cal.id"
            >
              <span class="category-chip__dot" :style="{ background: cal.color }" />
              {{ cal.name }}
            </button>
          </div>
        </div>

        <!-- Teilnehmer -->
        <div class="form-field">
          <label class="form-label">
            {{ t('calendar.participantsLabel') }}
            <span class="form-hint">
              ({{ formParticipants.length === 0 ? t('calendar.everyone') : formParticipants.length }})
            </span>
          </label>
          <div class="participant-chips">
            <button
              v-for="member in store.members"
              :key="member.id"
              type="button"
              class="participant-chip"
              :class="{ 'participant-chip--active': formParticipants.includes(member.id) }"
              @click="toggleParticipant(member.id)"
            >
              <BaseAvatar :name="member.display_name" :user-id="member.id" size="sm" />
              <span>{{ member.display_name }}</span>
            </button>
          </div>
        </div>

        <!-- Notiz -->
        <div class="form-field">
          <label class="form-label" for="event-note">{{ t('calendar.noteLabel') }}</label>
          <textarea
            id="event-note"
            v-model="formNote"
            class="form-textarea"
            :placeholder="t('calendar.notePlaceholder')"
            maxlength="500"
            rows="3"
          />
        </div>
      </form>

      <template #footer>
        <div class="dialog-actions">
          <BaseButton
            v-if="editingEvent"
            variant="danger"
            size="sm"
            :disabled="isPending('event-form')"
            @click="handleDelete"
          >
            <PhTrash :size="16" />
            {{ t('common.delete') }}
          </BaseButton>
          <span v-else class="dialog-actions__spacer" />
          <div class="dialog-actions__right">
            <BaseButton variant="secondary" @click="closeDialog">
              {{ t('common.cancel') }}
            </BaseButton>
            <BaseButton
              variant="primary"
              type="submit"
              :form="EVENT_FORM_ID"
              :loading="isPending('event-form')"
              :disabled="!formTitle.trim() || !formCalendarId"
            >
              {{ t('common.save') }}
            </BaseButton>
          </div>
        </div>
      </template>
    </BaseDialog>

    <!-- Decide-Dialog -->
    <BaseDialog
      :open="decideDialogOpen"
      :title="t('polls.decidePollTitle')"
      @close="closeDecideDialog"
    >
      <form :id="DECIDE_FORM_ID" class="event-form" @submit.prevent="submitDecide">
        <!-- Terminname -->
        <BaseInput
          :model-value="decideEventTitle"
          @update:model-value="decideEventTitle = $event"
          :label="t('polls.decideEventTitle')"
          :placeholder="t('calendar.titlePlaceholder')"
        />

        <!-- Gewählte Option -->
        <div v-if="decidingPoll" class="form-field">
          <label class="form-label">{{ t('polls.option') }}</label>
          <div class="poll-options">
            <button
              v-for="option in decidingPoll.options"
              :key="option.id"
              type="button"
              class="poll-option"
              :class="{ 'poll-option--selected': decideOptionId === option.id }"
              @click="decideOptionId = option.id"
            >
              <span class="poll-option__label">{{ option.label }}</span>
              <span class="poll-option__count" v-if="option.votes.length > 0">
                {{ option.votes.length }}
              </span>
            </button>
          </div>
        </div>

        <!-- Kalender -->
        <div class="form-field">
          <label class="form-label">{{ t('polls.decideCalendar') }}</label>
          <div class="category-chips">
            <button
              v-for="cal in store.calendars"
              :key="cal.id"
              type="button"
              class="category-chip"
              :class="{ 'category-chip--active': decideCalendarId === cal.id }"
              @click="decideCalendarId = cal.id"
            >
              <span class="category-chip__dot" :style="{ background: cal.color }" />
              {{ cal.name }}
            </button>
          </div>
        </div>
      </form>

      <template #footer>
        <div class="dialog-actions">
          <span class="dialog-actions__spacer" />
          <div class="dialog-actions__right">
            <BaseButton variant="secondary" @click="closeDecideDialog">
              {{ t('common.cancel') }}
            </BaseButton>
            <BaseButton
              variant="primary"
              type="submit"
              :form="DECIDE_FORM_ID"
              :loading="isPending('poll-decide')"
              :disabled="!decideEventTitle.trim() || !decideOptionId || !decideCalendarId"
            >
              {{ t('polls.decide') }}
            </BaseButton>
          </div>
        </div>
      </template>
    </BaseDialog>

    <!-- Manage Calendars Dialog -->
    <BaseDialog :open="manageDialogOpen" :title="t('calendars.manage')" @close="manageDialogOpen = false">
      <div class="calendar-manage-list">
        <div v-for="cal in store.calendars" :key="cal.id" class="calendar-manage-item">
          <input
            type="color"
            :value="cal.color"
            @change="handleColorChange(cal, $event)"
            class="color-picker"
            :aria-label="`${t('calendars.color')}: ${cal.name}`"
          />
          <input
            :value="cal.name"
            @blur="handleRename(cal, $event.target as HTMLInputElement)"
            @keydown.enter.prevent="($event.target as HTMLInputElement).blur()"
            class="calendar-name-input"
            maxlength="50"
            :aria-label="t('calendars.name')"
          />
          <button @click="askDeleteCalendar(cal)" class="delete-btn" :aria-label="`${t('calendars.delete')}: ${cal.name}`">
            <PhTrash :size="16" />
          </button>
        </div>
      </div>

      <!-- Neuer Kalender -->
      <div class="calendar-manage-add">
        <input
          v-model="newCalendarName"
          :placeholder="t('calendars.name')"
          :aria-label="t('calendars.add')"
          class="calendar-name-input"
          maxlength="50"
          @keydown.enter.prevent="handleAddCalendar"
        />
        <input type="color" v-model="newCalendarColor" class="color-picker" :aria-label="t('calendars.color')" />
        <BaseButton
          size="sm"
          variant="primary"
          :disabled="!newCalendarName.trim()"
          :loading="isPending('calendar-add')"
          :aria-label="t('calendars.add')"
          @click="handleAddCalendar"
        >
          <PhPlus :size="16" />
        </BaseButton>
      </div>

      <template #footer>
        <BaseButton variant="secondary" @click="manageDialogOpen = false">
          {{ t('common.close') }}
        </BaseButton>
      </template>
    </BaseDialog>

    <!-- Kalender löschen: Bestätigung -->
    <BaseDialog
      :open="!!calendarToDelete"
      :title="t('calendars.delete')"
      danger
      @close="closeDeleteCalendar"
    >
      <p class="confirm-text">{{ t('calendars.deleteConfirmNamed', { name: calendarToDelete?.name ?? '' }) }}</p>
      <template #footer>
        <BaseButton variant="secondary" @click="closeDeleteCalendar">
          {{ t('common.cancel') }}
        </BaseButton>
        <BaseButton
          variant="danger"
          :loading="!!calendarToDelete && isPending(`calendar-delete-${calendarToDelete.id}`)"
          @click="confirmDeleteCalendar"
        >
          {{ t('common.delete') }}
        </BaseButton>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.calendar-view {
  padding-bottom: 100px;
}

.calendar-tabs {
  padding: 0 var(--space-4) var(--space-3);
}

/* ── Manage Button ── */
.manage-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--sub);
  padding: var(--space-2);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color var(--transition-fast), background var(--transition-fast);
}

.manage-btn:hover {
  color: var(--ink);
  background: var(--chip);
}

/* ── Calendar Filter Chips ── */
.calendar-filter-chips {
  display: flex;
  gap: var(--space-2);
  padding: 0 var(--space-4) var(--space-3);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}

.calendar-filter-chips::-webkit-scrollbar {
  display: none;
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 14px;
  border: 2px solid;
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-family: var(--font-family);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  white-space: nowrap;
  transition: all var(--transition-fast);
  background: var(--card);
}

.filter-chip--active {
  font-weight: var(--font-weight-semibold);
}

/* ── Week Navigation ── */
.week-nav {
  padding: 0 var(--space-4);
  margin-bottom: var(--space-4);
}

.week-nav__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}

.week-nav__arrow {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--ink);
  padding: var(--space-2);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
}

.week-nav__arrow:active {
  background: var(--chip);
}

.week-nav__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

/* ── Week Strip ── */
.week-strip {
  display: flex;
  justify-content: space-between;
  gap: var(--space-1);
}

.week-strip__day {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: var(--space-2) 0;
  border: none;
  background: none;
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: background var(--transition-fast);
  font-family: var(--font-family);
}

.week-strip__day:active {
  background: var(--chip);
}

.week-strip__day--selected {
  background: var(--chip);
}

.week-strip__day--today .week-strip__num {
  background: var(--ink);
  color: var(--card);
  border-radius: var(--radius-full);
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.week-strip__short {
  font-size: var(--text-xs);
  color: var(--sub);
  font-weight: var(--font-weight-medium);
}

.week-strip__num {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  min-height: 28px;
}

.week-strip__dots {
  display: flex;
  gap: 2px;
  min-height: 6px;
  align-items: center;
}

.week-strip__dot {
  width: 4px;
  height: 4px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

/* ── Event List ── */
.event-list {
  padding: 0 var(--space-4);
}

.event-list__date-header {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
  margin: var(--space-4) 0 var(--space-2);
  font-family: var(--font-family);
}

.event-list__date-header:first-child {
  margin-top: 0;
}

.event-list__cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* ── Event Card ── */
.event-card {
  position: relative;
  overflow: hidden;
  cursor: pointer;
  transition: transform var(--transition-fast);
}

.event-card:active {
  transform: scale(0.98);
}

.event-card__bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: 3px 0 0 3px;
}

.event-card__body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-left: var(--space-3);
}

.event-card__content {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
}

.event-card__time {
  font-size: var(--text-xs);
  color: var(--sub);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.event-card__date-badge {
  font-size: var(--text-xs);
  color: var(--sub);
  background: var(--chip);
  padding: 1px 6px;
  border-radius: var(--radius-full);
}

.event-card__title {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.event-card__meta {
  font-size: var(--text-xs);
  color: var(--sub);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.event-card__avatars {
  display: flex;
  align-items: center;
  gap: -4px;
  flex-shrink: 0;
  margin-left: var(--space-3);
}

.event-card__avatars > *:not(:first-child) {
  margin-left: -4px;
}

.event-card__everyone-chip {
  font-size: var(--text-xs);
  color: var(--sub);
  background: var(--chip);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  white-space: nowrap;
}

.event-card__extra {
  font-size: var(--text-xs);
  color: var(--sub);
  margin-left: var(--space-1);
}

/* ── FAB ── */
.fab {
  position: fixed;
  right: var(--space-4);
  bottom: 80px;
  width: 52px;
  height: 52px;
  border-radius: var(--radius-full);
  background: var(--acc);
  color: var(--card);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-overlay);
  z-index: 100;
  transition: transform var(--transition-fast), filter var(--transition-fast);
}

.fab:active {
  transform: scale(0.92);
}

.fab:hover {
  filter: brightness(1.08);
}

/* ── Form ── */
.event-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.form-field--toggle {
  flex-direction: row;
  align-items: center;
  justify-content: space-between;
}

.form-field--half {
  flex: 1;
}

.form-row {
  display: flex;
  gap: var(--space-3);
}

.form-label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
}

.form-hint {
  font-weight: var(--font-weight-normal);
  color: var(--sub);
}

.form-input {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
  font-family: var(--font-family);
  font-size: var(--text-base);
  color: var(--ink);
  background-color: var(--card);
  transition: border-color var(--transition-fast);
}

.form-input:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}

.form-textarea {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
  font-family: var(--font-family);
  font-size: var(--text-base);
  color: var(--ink);
  background-color: var(--card);
  resize: vertical;
  min-height: 72px;
  transition: border-color var(--transition-fast);
}

.form-textarea:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}

/* ── Toggle Switch ── */
.toggle {
  position: relative;
  display: inline-block;
  width: 44px;
  height: 24px;
  flex-shrink: 0;
}

.toggle__input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle__slider {
  position: absolute;
  inset: 0;
  background: var(--line-strong);
  border-radius: var(--radius-full);
  transition: background var(--transition-fast);
  cursor: pointer;
}

.toggle__slider::before {
  content: '';
  position: absolute;
  width: 18px;
  height: 18px;
  left: 3px;
  bottom: 3px;
  background: var(--card);
  border-radius: var(--radius-full);
  transition: transform var(--transition-fast);
}

.toggle__input:checked + .toggle__slider {
  background: var(--acc);
}

.toggle__input:checked + .toggle__slider::before {
  transform: translateX(20px);
}

/* ── Category Chips (now Calendar Chips) ── */
.category-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.category-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 4px 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-full);
  background: var(--card);
  color: var(--ink);
  font-size: var(--text-sm);
  font-family: var(--font-family);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.category-chip--active {
  background: var(--chip);
  border-color: var(--ink);
  font-weight: var(--font-weight-semibold);
}

.category-chip__dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

/* ── Participant Chips ── */
.participant-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.participant-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 4px 12px 4px 4px;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-full);
  background: var(--card);
  color: var(--ink);
  font-size: var(--text-sm);
  font-family: var(--font-family);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.participant-chip--active {
  background: var(--chip);
  border-color: var(--ink);
  font-weight: var(--font-weight-semibold);
}

/* ── Dialog Footer Actions ── */
.dialog-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.dialog-actions__spacer {
  flex: 1;
}

.dialog-actions__right {
  display: flex;
  gap: var(--space-2);
}

/* ── Poll Section ── */
.poll-section {
  padding: 0 var(--space-4);
  margin-bottom: var(--space-4);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.poll-card {
  margin-bottom: 0;
}

.poll-question {
  font-family: var(--font-display);
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  margin: 0 0 var(--space-3);
}

.poll-options {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.poll-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
  background: var(--chip);
  border: 2px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: border-color var(--transition-fast);
  font-family: var(--font-family);
  font-size: var(--text-sm);
}

.poll-option--selected {
  border-color: var(--acc);
  background: var(--acc-soft);
}

.poll-option__label {
  font-weight: var(--font-weight-medium);
  color: var(--ink);
}

.poll-option__votes {
  display: flex;
  align-items: center;
  gap: 2px;
}

.poll-option__votes > *:not(:first-child) {
  margin-left: -4px;
}

.poll-option__count {
  font-size: var(--text-xs);
  color: var(--sub);
  margin-left: var(--space-1);
}

.poll-actions {
  margin-top: var(--space-3);
  display: flex;
  justify-content: flex-end;
}

/* ── Form Error ── */
.form-input--error {
  border-color: var(--color-danger);
}

.form-error {
  margin: 2px 0 0;
  font-size: var(--text-sm);
  color: var(--color-danger);
}

/* ── Span Badge ── */
.event-card__span-badge {
  font-size: var(--text-xs);
  color: var(--acc);
  background: var(--acc-soft);
  padding: 1px 6px;
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

/* ── Calendar Manage Dialog ── */
.calendar-manage-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.calendar-manage-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.color-picker {
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-md);
  cursor: pointer;
  background: none;
  flex-shrink: 0;
}

.color-picker::-webkit-color-swatch-wrapper {
  padding: 2px;
}

.color-picker::-webkit-color-swatch {
  border: none;
  border-radius: 4px;
}

.calendar-name-input {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
  font-family: var(--font-family);
  font-size: var(--text-base); /* 16px — verhindert iOS-Zoom */
  color: var(--ink);
  background-color: var(--card);
  min-width: 0;
}

.confirm-text {
  margin: 0;
  color: var(--ink);
}

.calendar-name-input:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}

.delete-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--sub);
  padding: var(--space-2);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: color var(--transition-fast), background var(--transition-fast);
}

.delete-btn:hover {
  color: var(--color-danger);
  background: var(--chip);
}

.calendar-manage-add {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}
</style>
