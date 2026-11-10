<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCalendarStore } from '../stores/calendar'
import { usePollsStore } from '../stores/polls'
import { useAuthStore } from '../stores/auth'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import { useLoader } from '../composables/useLoader'
import { localDateString } from '../utils/dates'
import { addDaysToDate, getMonthGridRange } from '../utils/calendarView'
import type { CalendarEvent, CalendarInfo } from '../types'
import type { WeekDay } from '../components/calendar/types'
import CalendarMonthGrid from '../components/CalendarMonthGrid.vue'
import CalendarWeekStrip from '../components/calendar/CalendarWeekStrip.vue'
import CalendarEventList from '../components/calendar/CalendarEventList.vue'
import CalendarPollSection from '../components/calendar/CalendarPollSection.vue'
import CalendarEventFormDialog from '../components/calendar/CalendarEventFormDialog.vue'
import CalendarManageDialog from '../components/calendar/CalendarManageDialog.vue'

import BasePillTabs from '../components/ui/BasePillTabs.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import { PhPlus, PhGear } from '@phosphor-icons/vue'

const { t, locale } = useI18n()
const store = useCalendarStore()
const pollsStore = usePollsStore()
const authStore = useAuthStore()
const { on, off, onReconnect, offReconnect } = useSocket()
const { notifyError } = useToast()

const eventList = ref<InstanceType<typeof CalendarEventList> | null>(null)
const eventFormDialog = ref<InstanceType<typeof CalendarEventFormDialog> | null>(null)
const manageDialog = ref<InstanceType<typeof CalendarManageDialog> | null>(null)

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

/** Gelöschten Kalender aus dem Filter entfernen (Verwalten-Dialog) */
function handleCalendarDeleted(calId: string) {
  activeCalendarIds.value = activeCalendarIds.value.filter(id => id !== calId)
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
  const days: WeekDay[] = []
  const todayStr = localDateString(new Date())
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

function scrollToDay(date: string) {
  selectedDay.value = date
  eventList.value?.scrollToDay(date)
}

// ── Dialoge ──
function openCreateDialog() {
  // Default: heute oder selectedDay
  eventFormDialog.value?.openCreate(selectedDay.value)
}

function openEditDialog(event: CalendarEvent) {
  eventFormDialog.value?.openEdit(event)
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
  selectedDay.value = localDateString(new Date())

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
        <button class="manage-btn tap-target" @click="manageDialog?.open()" :aria-label="t('calendars.manage')">
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
        class="filter-chip tap-target"
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
    <CalendarWeekStrip
      v-if="activeTab === 'week'"
      :week-days="weekDays"
      :selected-day="selectedDay"
      :events="filteredEvents"
      @navigate="handleWeekNavigate"
      @select-day="scrollToDay"
    />

    <!-- Month Grid -->
    <CalendarMonthGrid
      v-if="activeTab === 'month'"
      :events="filteredEvents"
      :get-calendar-color="store.getCalendarColor"
      :get-calendar-name="store.getCalendarName"
      :members="store.members"
      :selected-date="localDateString(currentMonthDate)"
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

    <!-- Offene Abstimmungen (nur Termin-Abstimmungen); nach „Übernehmen“ passend
         zur aktiven Ansicht nachladen (Monat bleibt Monat) -->
    <CalendarPollSection @decided="refreshEvents(reloadVisibleEvents)" />

    <!-- Event List — Woche (gruppiert nach Tag) bzw. Liste (chronologisch) -->
    <CalendarEventList
      v-if="activeTab !== 'month'"
      ref="eventList"
      :mode="activeTab"
      :events="filteredEvents"
      :week-days="weekDays"
      :load-error="loadError"
      @edit="openEditDialog"
      @create="openCreateDialog"
    />

    <!-- FAB -->
    <button class="fab" @click="openCreateDialog" :aria-label="t('calendar.newEvent')">
      <PhPlus :size="24" weight="bold" />
    </button>

    <!-- Create / Edit Dialog -->
    <CalendarEventFormDialog ref="eventFormDialog" :is-visible-in-view="isVisibleInView" />

    <!-- Kalender verwalten (inkl. Löschen-Bestätigung) -->
    <CalendarManageDialog ref="manageDialog" @calendar-deleted="handleCalendarDeleted" />
  </div>
</template>

<style scoped>
.calendar-view {
  /* Platz, damit der FAB den letzten Termin nicht verdeckt */
  padding-bottom: calc(var(--fab-size) + var(--space-6));
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
  /* oben Raum für die vergrösserte Tap-Fläche (Scroll-Container schneidet sonst ab) */
  padding: var(--space-2) var(--space-4) var(--space-3);
  margin-top: calc(-1 * var(--space-2));
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
  padding: var(--chip-padding-sm);
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

/* ── FAB ── */
.fab {
  position: fixed;
  right: var(--space-4);
  bottom: var(--fab-bottom);
  width: var(--fab-size);
  height: var(--fab-size);
  border-radius: var(--radius-full);
  background: var(--acc);
  color: var(--color-on-accent);
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-overlay);
  z-index: var(--z-fab);
  transition: transform var(--transition-fast), filter var(--transition-fast);
}

.fab:active {
  transform: scale(0.92);
}

.fab:hover {
  filter: brightness(1.08);
}
</style>
