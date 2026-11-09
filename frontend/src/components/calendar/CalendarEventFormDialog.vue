<script setup lang="ts">
/**
 * Termin anlegen / bearbeiten / löschen (Dialog der Kalender-Ansicht).
 * Zeiten sind Wanduhrzeiten in Haushaltszeit (ohne Offset); Bearbeiten sendet
 * nur geänderte Felder (CASA-09). Geöffnet wird über `openCreate` / `openEdit`.
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhTrash } from '@phosphor-icons/vue'
import { useCalendarStore } from '../../stores/calendar'
import { useAuthStore } from '../../stores/auth'
import { useAsyncAction } from '../../composables/useAsyncAction'
import { eventTime, eventDate, localDateString } from '../../utils/dates'
import { formatDayHeader as formatDayHeaderIn } from '../../utils/calendarView'
import { changedEventFields } from '../../utils/eventEdit'
import type { CalendarEvent, CalendarEventCreatePayload, EventReminder } from '../../types'
import BaseDialog from '../ui/BaseDialog.vue'
import BaseButton from '../ui/BaseButton.vue'
import BaseInput from '../ui/BaseInput.vue'
import BaseAvatar from '../ui/BaseAvatar.vue'

const props = defineProps<{
  /** Liegt ein Termin (Startdatum, Kalender) in der aktuell sichtbaren Ansicht? */
  isVisibleInView: (dateStr: string, calendarId: string) => boolean
}>()

const { t, locale } = useI18n()
const store = useCalendarStore()
const authStore = useAuthStore()
const { run, isPending } = useAsyncAction()

function formatDayHeader(dateStr: string): string {
  return formatDayHeaderIn(dateStr, locale.value)
}

function formatTime(isoStr: string): string {
  // Haushaltszeit direkt aus dem String (siehe utils/dates eventTime)
  return eventTime(isoStr)
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
const formReminder = ref<EventReminder>('none')
const REMINDER_OPTIONS: EventReminder[] = ['none', '15m', '1h', '1d']
const formEndDate = ref('')
const formEndDateError = ref('')
const EVENT_FORM_ID = 'calendar-event-form'

/** Neuer Termin; `defaultDate` = ausgewählter Tag (leer → heute) */
function openCreate(defaultDate: string) {
  editingEvent.value = null
  formTitle.value = ''
  // Default: heute oder selectedDay
  formDate.value = defaultDate || localDateString(new Date())
  formEndDate.value = formDate.value  // Default: Enddatum = Startdatum
  formEndDateError.value = ''
  formAllDay.value = false
  formStartTime.value = '09:00'
  formEndTime.value = '10:00'
  formCalendarId.value = localStorage.getItem('last-calendar-' + authStore.currentHouseholdId) || store.calendars[0]?.id || ''
  formParticipants.value = []
  formNote.value = ''
  formReminder.value = 'none'
  dialogOpen.value = true
}

function openEdit(event: CalendarEvent) {
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
  formReminder.value = event.reminder ?? 'none'
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
    reminder: formReminder.value,
  }
  const editing = editingEvent.value
  // Bearbeiten: nur geänderte Felder senden (CASA-09); nichts geändert → kein Request
  const changes = editing ? changedEventFields(editing, payload) : null
  if (changes && Object.keys(changes).length === 0) {
    closeDialog()
    return
  }
  const ok = await run(
    () => editing && changes ? store.updateEvent(editing.id, changes) : store.addEvent(payload),
    {
      key: 'event-form',
      // Termin ausserhalb der sichtbaren Woche/des Monats (oder im ausgeblendeten
      // Kalender): sonst passiert sichtbar nichts
      success: () => props.isVisibleInView(formDate.value, payload.calendar_id)
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
      reminder: event.reminder ?? 'none',
    }),
    error: t('calendar.deleteError'),
  })
}

defineExpose({ openCreate, openEdit })
</script>

<template>
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
            class="category-chip tap-target"
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
            class="participant-chip tap-target"
            :class="{ 'participant-chip--active': formParticipants.includes(member.id) }"
            @click="toggleParticipant(member.id)"
          >
            <BaseAvatar :name="member.display_name" :user-id="member.id" size="sm" />
            <span>{{ member.display_name }}</span>
          </button>
        </div>
      </div>

      <!-- Erinnerung (Push an Teilnehmer, sonst an alle) -->
      <div class="form-field">
        <label class="form-label" for="event-reminder">{{ t('calendar.reminderLabel') }}</label>
        <select id="event-reminder" v-model="formReminder" class="form-input">
          <option v-for="r in REMINDER_OPTIONS" :key="r" :value="r">
            {{ t(`calendar.reminder.${r}`) }}
          </option>
        </select>
        <p v-if="formAllDay && formReminder !== 'none'" class="form-hint">
          {{ formReminder === '1d' ? t('calendar.reminderAllDayBefore') : t('calendar.reminderAllDay') }}
        </p>
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
</template>

<style scoped>
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
  padding: var(--space-1) var(--space-3) var(--space-1) var(--space-1);
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

/* ── Form Error ── */
.form-input--error {
  border-color: var(--color-danger);
}

.form-error {
  margin: var(--space-0-5) 0 0;
  font-size: var(--text-sm);
  color: var(--color-danger);
}
</style>
