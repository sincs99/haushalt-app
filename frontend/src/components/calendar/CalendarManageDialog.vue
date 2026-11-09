<script setup lang="ts">
/**
 * Kalender verwalten: umbenennen, Farbe ändern, anlegen, löschen (mit
 * Bestätigung). Geöffnet über `open()`; ein gelöschter Kalender wird über
 * `calendar-deleted` gemeldet, damit die Ansicht ihn aus dem Filter nimmt.
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhPlus, PhTrash } from '@phosphor-icons/vue'
import { useCalendarStore } from '../../stores/calendar'
import { useAsyncAction } from '../../composables/useAsyncAction'
import type { CalendarInfo } from '../../types'
import BaseDialog from '../ui/BaseDialog.vue'
import BaseButton from '../ui/BaseButton.vue'

const emit = defineEmits<{
  'calendar-deleted': [calendarId: string]
}>()

const { t } = useI18n()
const store = useCalendarStore()
const { run, isPending } = useAsyncAction()

// ── Manage Calendars Dialog ──
const manageDialogOpen = ref(false)
const newCalendarName = ref('')
const newCalendarColor = ref('#5B8DEF')

function open() {
  manageDialogOpen.value = true
}

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
    // Aus Filter entfernen (Filter gehört der Ansicht)
    emit('calendar-deleted', cal.id)
  }
  closeDeleteCalendar()
}

defineExpose({ open })
</script>

<template>
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
        <button @click="askDeleteCalendar(cal)" class="delete-btn tap-target" :aria-label="`${t('calendars.delete')}: ${cal.name}`">
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
</template>

<style scoped>
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
  width: var(--touch-target);
  height: var(--touch-target);
  padding: 0;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-md);
  cursor: pointer;
  background: none;
  flex-shrink: 0;
}

.color-picker::-webkit-color-swatch-wrapper {
  padding: var(--space-0-5);
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
