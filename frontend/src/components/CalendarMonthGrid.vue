<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { expandEventToDays } from '../utils/dates'
import type { ExpandedEventDay } from '../utils/dates'
import type { CalendarEvent, HouseholdMemberInfo } from '../types'
import BaseCard from './ui/BaseCard.vue'
import BaseAvatar from './ui/BaseAvatar.vue'
import BaseEmptyState from './ui/BaseEmptyState.vue'
import {
  PhCaretLeft,
  PhCaretRight,
  PhCalendarBlank,
  PhPlus,
} from '@phosphor-icons/vue'

// ── Props & Emits ──

const props = defineProps<{
  events: CalendarEvent[]
  getCalendarColor: (calId: string) => string
  getCalendarName: (calId: string) => string
  members: HouseholdMemberInfo[]
  selectedDate: string
  loading: boolean
}>()

const emit = defineEmits<{
  'select-day': [dateStr: string]
  'create-event': [dateStr: string]
  'edit-event': [event: CalendarEvent]
  'navigate': [offset: number]
  'go-today': []
}>()

const { t, locale } = useI18n()

// ── Internal State ──

const currentYear = ref(new Date().getFullYear())
const currentMonth = ref(new Date().getMonth()) // 0-basiert
const expandedDay = ref<string | null>(null)

// Initialisierung aus selectedDate prop
watch(
  () => props.selectedDate,
  (val) => {
    if (val) {
      const d = new Date(val + 'T00:00:00')
      currentYear.value = d.getFullYear()
      currentMonth.value = d.getMonth()
    }
  },
  { immediate: true },
)

// ── Grid-Berechnung ──

interface GridDay {
  date: string
  num: number
  isCurrentMonth: boolean
  isToday: boolean
}

function formatLocal(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const todayStr = computed(() => formatLocal(new Date()))

const gridDays = computed<GridDay[]>(() => {
  const year = currentYear.value
  const month = currentMonth.value

  // Erster Tag des Monats → Montag der Woche finden
  const firstOfMonth = new Date(year, month, 1)
  const dayOfWeek = firstOfMonth.getDay() // 0=So
  const diffToMonday = dayOfWeek === 0 ? -6 : 1 - dayOfWeek
  const gridStart = new Date(firstOfMonth)
  gridStart.setDate(gridStart.getDate() + diffToMonday)

  // Letzter Tag des Monats → Sonntag der Woche finden
  const lastOfMonth = new Date(year, month + 1, 0)
  const lastDow = lastOfMonth.getDay()
  const diffToSunday = lastDow === 0 ? 0 : 7 - lastDow
  const gridEnd = new Date(lastOfMonth)
  gridEnd.setDate(gridEnd.getDate() + diffToSunday)

  // Array aller Tage im Raster (35 oder 42)
  const days: GridDay[] = []
  const cursor = new Date(gridStart)
  while (cursor <= gridEnd) {
    days.push({
      date: formatLocal(cursor),
      num: cursor.getDate(),
      isCurrentMonth: cursor.getMonth() === month,
      isToday: formatLocal(cursor) === todayStr.value,
    })
    cursor.setDate(cursor.getDate() + 1)
  }
  return days
})

// ── Wochentag-Header ──

const weekdayLabels = computed(() => {
  return locale.value === 'de'
    ? ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
    : ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
})

// ── Monatstitel ──

const monthTitle = computed(() => {
  const d = new Date(currentYear.value, currentMonth.value, 1)
  return d.toLocaleDateString(locale.value === 'de' ? 'de-CH' : 'en-US', {
    month: 'long',
    year: 'numeric',
  })
})

// ── Events pro Tag (gecached) ──

const eventsByDate = computed(() => {
  const map = new Map<string, CalendarEvent[]>()
  for (const event of props.events) {
    const days = expandEventToDays(event.starts_at, event.ends_at)
    for (const d of days) {
      const existing = map.get(d.date)
      if (existing) {
        existing.push(event)
      } else {
        map.set(d.date, [event])
      }
    }
  }
  return map
})

// ── Farbpunkte pro Tag ──

function dotsForDay(dateStr: string): { colors: string[]; extra: number } {
  const dayEvents = eventsByDate.value.get(dateStr)
  if (!dayEvents || dayEvents.length === 0) return { colors: [], extra: 0 }

  const uniqueColors: string[] = []
  const seenCalIds = new Set<string>()
  for (const e of dayEvents) {
    if (!seenCalIds.has(e.calendar_id)) {
      seenCalIds.add(e.calendar_id)
      uniqueColors.push(props.getCalendarColor(e.calendar_id))
    }
  }
  const extra = uniqueColors.length > 3 ? uniqueColors.length - 3 : 0
  return { colors: uniqueColors.slice(0, 3), extra }
}

const dotsMap = computed(() => {
  const map = new Map<string, { colors: string[]; extra: number }>()
  for (const day of gridDays.value) {
    map.set(day.date, dotsForDay(day.date))
  }
  return map
})

// ── Tages-Detail Events ──

const expandedDayEvents = computed(() => {
  if (!expandedDay.value) return []
  const dayEvents = eventsByDate.value.get(expandedDay.value) ?? []
  // Sortierung: all_day zuerst, dann nach starts_at
  return [...dayEvents].sort((a, b) => {
    if (a.all_day && !b.all_day) return -1
    if (!a.all_day && b.all_day) return 1
    return a.starts_at.localeCompare(b.starts_at)
  })
})

// ── Span-Badge für mehrtägige Events ──

function getSpanBadge(event: CalendarEvent, dateStr: string): string | null {
  const days = expandEventToDays(event.starts_at, event.ends_at)
  if (days.length <= 1) return null
  const match = days.find((d: ExpandedEventDay) => d.date === dateStr)
  if (!match) return null
  return t('calendar.dayOfSpan', { current: match.dayIndex, total: match.totalDays })
}

// ── Helpers ──

function formatTime(isoStr: string): string {
  const d = new Date(isoStr)
  return d.toLocaleTimeString(locale.value === 'de' ? 'de-CH' : 'en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function formatDayHeader(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString(locale.value === 'de' ? 'de-CH' : 'en-US', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
}

function getParticipantNames(event: CalendarEvent): string {
  if (event.participant_ids.length === 0) {
    return `${t('calendar.everyone')} (${props.members.length})`
  }
  const names = event.participant_ids
    .map((id: string) => {
      const member = props.members.find(m => m.id === id)
      return member?.display_name ?? t('common.unknown')
    })
    .slice(0, 3)
  if (event.participant_ids.length > 3) {
    return names.join(', ') + ` +${event.participant_ids.length - 3}`
  }
  return names.join(', ')
}

function getMemberName(userId: string): string {
  const member = props.members.find(m => m.id === userId)
  return member?.display_name ?? '?'
}

// ── Navigation ──

function handleNavigate(offset: number) {
  const d = new Date(currentYear.value, currentMonth.value + offset, 1)
  currentYear.value = d.getFullYear()
  currentMonth.value = d.getMonth()
  expandedDay.value = null
  emit('navigate', offset)
}

function handleGoToday() {
  const now = new Date()
  currentYear.value = now.getFullYear()
  currentMonth.value = now.getMonth()
  expandedDay.value = todayStr.value
  emit('go-today')
}

function handleDayClick(day: GridDay) {
  if (expandedDay.value === day.date) {
    expandedDay.value = null
  } else {
    expandedDay.value = day.date
  }
  emit('select-day', day.date)
}
</script>

<template>
  <div class="month-grid">
    <!-- Navigation Header -->
    <div class="month-grid__header">
      <button class="month-grid__arrow" @click="handleNavigate(-1)" :aria-label="t('calendar.prevMonth')">
        <PhCaretLeft :size="20" />
      </button>
      <button class="month-grid__title" @click="handleGoToday">
        {{ monthTitle }}
      </button>
      <button class="month-grid__arrow" @click="handleNavigate(1)" :aria-label="t('calendar.nextMonth')">
        <PhCaretRight :size="20" />
      </button>
    </div>

    <!-- Weekday Header -->
    <div class="month-grid__weekdays">
      <span v-for="label in weekdayLabels" :key="label" class="month-grid__weekday">
        {{ label }}
      </span>
    </div>

    <!-- Day Grid -->
    <div class="month-grid__days">
      <button
        v-for="day in gridDays"
        :key="day.date"
        class="month-grid__cell"
        :class="{
          'month-grid__cell--outside': !day.isCurrentMonth,
          'month-grid__cell--today': day.isToday,
          'month-grid__cell--selected': expandedDay === day.date,
        }"
        @click="handleDayClick(day)"
      >
        <span class="month-grid__num" :class="{ 'month-grid__num--today': day.isToday }">
          {{ day.num }}
        </span>
        <span class="month-grid__dots">
          <span
            v-for="(color, idx) in dotsMap.get(day.date)?.colors"
            :key="idx"
            class="month-grid__dot"
            :style="{ background: color }"
          />
          <span
            v-if="(dotsMap.get(day.date)?.extra ?? 0) > 0"
            class="month-grid__dot-extra"
          >
            +{{ dotsMap.get(day.date)?.extra }}
          </span>
        </span>
      </button>
    </div>

    <!-- Expanded Day Detail -->
    <div v-if="expandedDay" class="month-grid__detail">
      <h3 class="month-grid__detail-header">
        {{ formatDayHeader(expandedDay) }}
      </h3>

      <div v-if="expandedDayEvents.length === 0 && !loading" class="month-grid__detail-empty">
        <BaseEmptyState
          :icon="PhCalendarBlank"
          :title="t('calendar.noEventsToday')"
          subtitle=""
        />
      </div>

      <div v-else class="month-grid__detail-cards">
        <BaseCard
          v-for="event in expandedDayEvents"
          :key="event.id"
          padding="sm"
          class="month-event-card"
          @click="emit('edit-event', event)"
        >
          <span
            class="month-event-card__bar"
            :style="{ background: getCalendarColor(event.calendar_id) }"
          />
          <div class="month-event-card__body">
            <div class="month-event-card__content">
              <span class="month-event-card__time">
                {{ event.all_day ? t('calendar.allDay') : formatTime(event.starts_at) }}
                <span v-if="getSpanBadge(event, expandedDay!)" class="month-event-card__span-badge">
                  {{ getSpanBadge(event, expandedDay!) }}
                </span>
              </span>
              <span class="month-event-card__title">{{ event.title }}</span>
              <span class="month-event-card__meta">
                {{ getCalendarName(event.calendar_id) }}
                · {{ getParticipantNames(event) }}
              </span>
            </div>
            <div class="month-event-card__avatars">
              <template v-if="event.participant_ids.length === 0">
                <span class="month-event-card__everyone-chip">
                  {{ t('calendar.everyone') }}
                </span>
              </template>
              <template v-else>
                <BaseAvatar
                  v-for="pid in event.participant_ids.slice(0, 3)"
                  :key="pid"
                  :name="getMemberName(pid)"
                  :user-id="pid"
                  size="sm"
                />
                <span v-if="event.participant_ids.length > 3" class="month-event-card__extra">
                  +{{ event.participant_ids.length - 3 }}
                </span>
              </template>
            </div>
          </div>
        </BaseCard>
      </div>

      <!-- + Termin Button -->
      <button class="month-grid__add-btn" @click="emit('create-event', expandedDay!)">
        <PhPlus :size="16" />
        {{ t('calendar.newEvent') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.month-grid {
  padding: 0 var(--space-4);
  margin-bottom: var(--space-4);
}

/* ── Header ── */
.month-grid__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}

.month-grid__arrow {
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

.month-grid__arrow:active {
  background: var(--chip);
}

.month-grid__title {
  background: none;
  border: none;
  cursor: pointer;
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  font-family: var(--font-family);
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  transition: background var(--transition-fast);
}

.month-grid__title:active {
  background: var(--chip);
}

/* ── Weekday Labels ── */
.month-grid__weekdays {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  margin-bottom: var(--space-1);
}

.month-grid__weekday {
  text-align: center;
  font-size: var(--text-xs);
  font-weight: var(--font-weight-medium);
  color: var(--sub);
}

/* ── Day Cells ── */
.month-grid__days {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 1px;
}

.month-grid__cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  gap: 2px;
  padding: var(--space-1) 0;
  min-height: 40px;
  border: none;
  background: none;
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: background var(--transition-fast);
  font-family: var(--font-family);
}

.month-grid__cell:active {
  background: var(--chip);
}

.month-grid__cell--selected {
  background: var(--chip);
}

.month-grid__cell--outside {
  opacity: 0.35;
}

/* ── Day Number ── */
.month-grid__num {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-full);
  line-height: 1;
}

.month-grid__num--today {
  background: var(--ink);
  color: var(--card);
  font-weight: var(--font-weight-semibold);
}

/* ── Dots ── */
.month-grid__dots {
  display: flex;
  gap: 2px;
  min-height: 6px;
  align-items: center;
}

.month-grid__dot {
  width: 4px;
  height: 4px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.month-grid__dot-extra {
  font-size: 10px;
  color: var(--sub);
  line-height: 1;
}

/* ── Expanded Day Detail ── */
.month-grid__detail {
  margin-top: var(--space-4);
  padding-top: var(--space-3);
  border-top: 1px solid var(--line-strong);
}

.month-grid__detail-header {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
  margin: 0 0 var(--space-3);
  font-family: var(--font-family);
}

.month-grid__detail-empty {
  margin-bottom: var(--space-3);
}

.month-grid__detail-cards {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  max-height: 50vh;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}

/* ── Event Card (reuses patterns from CalendarView) ── */
.month-event-card {
  position: relative;
  overflow: hidden;
  cursor: pointer;
  transition: transform var(--transition-fast);
}

.month-event-card:active {
  transform: scale(0.98);
}

.month-event-card__bar {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: 3px 0 0 3px;
}

.month-event-card__body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-left: var(--space-3);
}

.month-event-card__content {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
}

.month-event-card__time {
  font-size: var(--text-xs);
  color: var(--sub);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.month-event-card__title {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.month-event-card__meta {
  font-size: var(--text-xs);
  color: var(--sub);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.month-event-card__span-badge {
  font-size: var(--text-xs);
  color: var(--acc);
  background: var(--acc-soft);
  padding: 1px 6px;
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

/* ── Add Button ── */
.month-grid__add-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: var(--space-2) var(--space-3);
  background: var(--chip);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-full);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  font-family: var(--font-family);
  color: var(--ink);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.month-grid__add-btn:active {
  background: var(--line-strong);
}

/* ── Avatar Stack ── */
.month-event-card__avatars {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  margin-left: var(--space-3);
}

.month-event-card__avatars > *:not(:first-child) {
  margin-left: -4px;
}

.month-event-card__everyone-chip {
  font-size: var(--text-xs);
  color: var(--sub);
  background: var(--chip);
  padding: 2px 8px;
  border-radius: var(--radius-full);
  white-space: nowrap;
}

.month-event-card__extra {
  font-size: var(--text-xs);
  color: var(--sub);
  margin-left: var(--space-1);
}
</style>
