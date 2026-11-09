<script setup lang="ts">
/**
 * Offene Termin-Abstimmungen der Kalender-Ansicht: abstimmen und „Übernehmen“
 * (Entscheiden-Dialog legt den Termin an). Optionszeiten in Haushaltszeit (CASA-60).
 * Nach dem Entscheiden meldet `decided`, damit die Ansicht Termine nachlädt.
 */
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCalendarStore } from '../../stores/calendar'
import { usePollsStore } from '../../stores/polls'
import { useAuthStore } from '../../stores/auth'
import { useAsyncAction } from '../../composables/useAsyncAction'
import { eventTime, eventDate, localDateString } from '../../utils/dates'
import { formatDayHeader as formatDayHeaderIn } from '../../utils/calendarView'
import type { EventPoll, PollOption } from '../../types'
import BaseCard from '../ui/BaseCard.vue'
import BaseDialog from '../ui/BaseDialog.vue'
import BaseButton from '../ui/BaseButton.vue'
import BaseInput from '../ui/BaseInput.vue'
import BaseAvatar from '../ui/BaseAvatar.vue'

const emit = defineEmits<{
  'decided': []
}>()

const { t, locale } = useI18n()
const store = useCalendarStore()
const pollsStore = usePollsStore()
const authStore = useAuthStore()
const { run, isPending } = useAsyncAction()

const DECIDE_FORM_ID = 'calendar-decide-form'

function formatDayHeader(dateStr: string): string {
  return formatDayHeaderIn(dateStr, locale.value)
}

function formatTime(isoStr: string): string {
  // Haushaltszeit direkt aus dem String (siehe utils/dates eventTime)
  return eventTime(isoStr)
}

// ── Poll Helpers ──
function isMyVote(poll: EventPoll, optionId: string): boolean {
  const userId = authStore.user?.id
  if (!userId) return false
  return poll.options
    .find(o => o.id === optionId)
    ?.votes.some(v => v.user_id === userId) ?? false
}

/** Termin einer Abstimmungsoption (Haushaltszeit aus dem String, CASA-60) */
function formatOptionTime(option: PollOption): string {
  if (!option.starts_at) return ''
  return `${formatDayHeader(eventDate(option.starts_at))} · ${formatTime(option.starts_at)}`
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
  const date = option?.starts_at ? eventDate(option.starts_at) : localDateString(new Date())
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
  // Neuer Termin → die Ansicht lädt passend zur aktiven Ansicht nach (Monat bleibt Monat)
  emit('decided')
}
</script>

<template>
  <!-- Offene Abstimmungen (nur Termin-Abstimmungen) -->
  <div v-if="openEventPolls.length > 0" class="poll-section">
    <BaseCard v-for="poll in openEventPolls" :key="poll.id" class="poll-card">
      <h3 class="poll-question">{{ poll.question }}</h3>
      <div class="poll-options">
        <button
          v-for="option in poll.options"
          :key="option.id"
          class="poll-option tap-target"
          :class="{ 'poll-option--selected': isMyVote(poll, option.id) }"
          :aria-pressed="isMyVote(poll, option.id)"
          :disabled="isPending(`poll-${poll.id}`)"
          @click="handleVote(poll, option.id)"
        >
          <span class="poll-option__label">
            {{ option.label }}
            <small v-if="option.starts_at" class="poll-option__time">{{ formatOptionTime(option) }}</small>
          </span>
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
            class="poll-option tap-target"
            :class="{ 'poll-option--selected': decideOptionId === option.id }"
            @click="decideOptionId = option.id"
          >
            <span class="poll-option__label">
              {{ option.label }}
              <small v-if="option.starts_at" class="poll-option__time">{{ formatOptionTime(option) }}</small>
            </span>
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
            class="category-chip tap-target"
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
</template>

<style scoped>
/* ── Decide-Formular (gleiche Formular-Stile wie der Termin-Dialog) ── */
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

.form-label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
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
  padding: var(--chip-padding-sm);
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

/* ── Dialog Footer Actions ── */
.dialog-actions {
  display: flex;
  flex-wrap: wrap;
  min-width: 0;
  gap: var(--space-2);
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.dialog-actions__spacer {
  flex: 1;
}

.dialog-actions__right {
  display: flex;
  flex-wrap: wrap;
  min-width: 0;
  max-width: 100%;
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

.poll-option__time {
  display: block;
  font-size: var(--text-xs);
  font-weight: var(--font-weight-regular, 400);
  color: var(--sub);
}

.poll-option__votes {
  display: flex;
  align-items: center;
  gap: var(--space-0-5);
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
</style>
