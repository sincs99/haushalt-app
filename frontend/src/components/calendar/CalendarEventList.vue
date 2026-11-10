<script setup lang="ts">
/**
 * Terminliste der Kalender-Ansicht: in der Woche nach Tag gruppiert, in der
 * Liste chronologisch (geladener Bereich). Mehrtägige Termine tragen ein
 * „Tag x/y“-Badge. Klick öffnet den Bearbeiten-Dialog (Event `edit`).
 */
import { ref, computed, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhCalendarBlank } from '@phosphor-icons/vue'
import { useCalendarStore } from '../../stores/calendar'
import { expandEventToDays, eventTime, eventDate, localDateString } from '../../utils/dates'
import type { ExpandedEventDay } from '../../utils/dates'
import { addDaysToDate, formatDayHeader as formatDayHeaderIn, formatWeekdayShort as formatWeekdayShortIn } from '../../utils/calendarView'
import type { CalendarEvent } from '../../types'
import type { WeekDay } from './types'
import BaseCard from '../ui/BaseCard.vue'
import BaseButton from '../ui/BaseButton.vue'
import BaseAvatar from '../ui/BaseAvatar.vue'
import BaseEmptyState from '../ui/BaseEmptyState.vue'
import BaseSkeleton from '../ui/BaseSkeleton.vue'

interface DisplayEvent extends CalendarEvent {
  /** Nur gesetzt bei mehrtägigen Events: "Tag 2/3" */
  spanBadge?: string
}

const props = defineProps<{
  mode: 'week' | 'list'
  /** Termine der aktiven Kalender (Filter) */
  events: CalendarEvent[]
  weekDays: WeekDay[]
  loadError: boolean
}>()

const emit = defineEmits<{
  'edit': [event: CalendarEvent]
  'create': []
}>()

const { t, locale } = useI18n()
const store = useCalendarStore()

// ── Events grouped by date (for week view) ──
const eventsGroupedByDate = computed(() => {
  const groups: { date: string; label: string; events: DisplayEvent[] }[] = []
  const todayStr = localDateString(new Date())
  const tomorrowStr = addDaysToDate(todayStr, 1)

  for (const day of props.weekDays) {
    const dayEvents: DisplayEvent[] = []

    for (const event of props.events) {
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
  for (const event of props.events) {
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
function formatDayHeader(dateStr: string): string {
  return formatDayHeaderIn(dateStr, locale.value)
}

function formatWeekdayShort(dateStr: string): string {
  return formatWeekdayShortIn(dateStr, locale.value)
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

/** Zum Tag in der Wochenliste scrollen (Klick im Wochenstreifen) */
function scrollToDay(date: string) {
  nextTick(() => {
    const el = dayRefs.value[date]
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  })
}

defineExpose({ scrollToDay })
</script>

<template>
  <!-- Event List — Woche (gruppiert nach Tag) -->
  <div v-if="mode === 'week'" class="event-list">
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
          <BaseButton size="sm" variant="secondary" @click="emit('create')">
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
          @click="emit('edit', event)"
          @keydown.enter.prevent="emit('edit', event)"
          @keydown.space.prevent="emit('edit', event)"
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
  <div v-if="mode === 'list'" class="event-list">
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
          <BaseButton size="sm" variant="secondary" @click="emit('create')">
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
        @click="emit('edit', event)"
        @keydown.enter.prevent="emit('edit', event)"
        @keydown.space.prevent="emit('edit', event)"
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
</template>

<style scoped>
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
  font-size: var(--text-badge);
  color: var(--sub);
  background: var(--chip);
  padding: var(--badge-padding);
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
  font-size: var(--text-badge);
  color: var(--sub);
  background: var(--chip);
  padding: var(--badge-padding);
  border-radius: var(--radius-full);
  white-space: nowrap;
}

.event-card__extra {
  font-size: var(--text-xs);
  color: var(--sub);
  margin-left: var(--space-1);
}

/* ── Span Badge ── */
.event-card__span-badge {
  font-size: var(--text-badge);
  color: var(--acc);
  background: var(--acc-soft);
  padding: var(--badge-padding);
  border-radius: var(--radius-full);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}
</style>
