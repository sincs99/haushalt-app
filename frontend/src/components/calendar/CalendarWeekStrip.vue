<script setup lang="ts">
/**
 * Wochen-Navigation der Kalender-Ansicht: Wochenbereich mit Pfeilen und
 * Tagesstreifen (Punkte in Kalenderfarbe für Tage mit Terminen).
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhCaretLeft, PhCaretRight } from '@phosphor-icons/vue'
import { useCalendarStore } from '../../stores/calendar'
import { expandEventToDays } from '../../utils/dates'
import type { ExpandedEventDay } from '../../utils/dates'
import type { CalendarEvent } from '../../types'
import type { WeekDay } from './types'

const props = defineProps<{
  weekDays: WeekDay[]
  selectedDay: string
  /** Termine der aktiven Kalender (Filter) */
  events: CalendarEvent[]
}>()

const emit = defineEmits<{
  'navigate': [offset: number]
  'select-day': [date: string]
}>()

const { t, locale } = useI18n()
const store = useCalendarStore()

// ── Week Header ──
const weekLabel = computed(() => {
  if (props.weekDays.length === 0) return ''
  const first = props.weekDays[0]
  const last = props.weekDays[6]
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
  const dayEvents = props.events.filter((e: CalendarEvent) => {
    const days = expandEventToDays(e.starts_at, e.ends_at)
    return days.some((d: ExpandedEventDay) => d.date === dateStr)
  })
  const uniqueCalendarIds = [...new Set(dayEvents.map((e: CalendarEvent) => e.calendar_id))]
  return uniqueCalendarIds.slice(0, 3).map((calId: string) => store.getCalendarColor(calId))
}
</script>

<template>
  <div class="week-nav">
    <div class="week-nav__header">
      <button class="week-nav__arrow tap-target" @click="emit('navigate', -1)" :aria-label="t('calendar.prevWeek')">
        <PhCaretLeft :size="20" />
      </button>
      <span class="week-nav__label">{{ weekLabel }}</span>
      <button class="week-nav__arrow tap-target" @click="emit('navigate', 1)" :aria-label="t('calendar.nextWeek')">
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
        @click="emit('select-day', day.date)"
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
</template>

<style scoped>
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
  gap: var(--space-0-5);
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
  gap: var(--space-0-5);
  min-height: 6px;
  align-items: center;
}

.week-strip__dot {
  width: 4px;
  height: 4px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}
</style>
