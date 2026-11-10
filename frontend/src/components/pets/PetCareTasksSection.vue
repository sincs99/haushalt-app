<script setup lang="ts">
/**
 * „Pflege & Termine“ auf der Tier-Detailseite: wiederkehrende Pflegeaufgaben nach
 * Fälligkeit, erledigen, anlegen und löschen.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { usePetsStore } from '../../stores/pets'
import { useAsyncAction } from '../../composables/useAsyncAction'
import { localDateString } from '../../utils/dates'
import type { PetCareTask } from '../../types'
import { PhPlus, PhCheck, PhTrash } from '@phosphor-icons/vue'
import BaseCard from '../ui/BaseCard.vue'
import BaseButton from '../ui/BaseButton.vue'
import BaseDialog from '../ui/BaseDialog.vue'
import BaseInput from '../ui/BaseInput.vue'

const props = defineProps<{
  petId: string
}>()

const petsStore = usePetsStore()
const { run, isPending } = useAsyncAction()
const { t } = useI18n()

const sortedCareTasks = computed(() =>
  [...petsStore.careTasks].sort((a, b) => a.next_due_at.localeCompare(b.next_due_at)),
)

// ── Care Task Helpers ──

function isOverdue(task: PetCareTask): boolean {
  return task.next_due_at < localDateString()
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('de-CH', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

// ── Add Care Task Dialog ──

const showCareTaskDialog = ref(false)
const careTaskName = ref('')
const careTaskInterval = ref('')
const careTaskDueDate = ref('')
const careTaskSaving = computed(() => isPending('care-save'))
// Inline-Fehler am Intervall-Feld (statt still nichts zu tun)
const careTaskIntervalError = ref('')

watch(careTaskInterval, () => { careTaskIntervalError.value = '' })

function openAddCareTaskDialog() {
  careTaskName.value = ''
  careTaskInterval.value = ''
  careTaskDueDate.value = ''
  careTaskIntervalError.value = ''
  showCareTaskDialog.value = true
}

function closeCareTaskDialog() {
  showCareTaskDialog.value = false
}

async function handleSaveCareTask() {
  const name = careTaskName.value.trim()
  const raw = careTaskInterval.value.trim()
  const interval = Number(raw)
  if (!name || !careTaskDueDate.value) return
  if (!/^\d+$/.test(raw) || interval < 1 || interval > 3650) {
    careTaskIntervalError.value = t('petCare.invalidInterval')
    return
  }

  const ok = await run(() => petsStore.createCareTask(props.petId, {
    name,
    interval_days: interval,
    next_due_at: careTaskDueDate.value,
  }), { key: 'care-save', success: t('petCare.taskCreated'), error: t('petCare.saveError') })
  if (ok) showCareTaskDialog.value = false
}

// ── Complete Care Task ──

// Guard + Loading gegen Doppeltipp. Kein Undo: Backend kann „erledigt“ nicht zurücknehmen.
function handleCompleteCareTask(taskId: string) {
  return run(() => petsStore.completeCareTask(props.petId, taskId), {
    key: `complete-${taskId}`,
    success: () => {
      const task = petsStore.careTasks.find(c => c.id === taskId)
      return task ? t('petCare.completed', { date: formatDate(task.next_due_at) }) : undefined
    },
    error: t('petCare.completeError'),
  })
}

// ── Delete Care Task ──

const deletingCareTaskId = ref<string | null>(null)

function confirmDeleteCareTask(taskId: string) {
  deletingCareTaskId.value = taskId
}

function cancelDeleteCareTask() {
  deletingCareTaskId.value = null
}

async function handleDeleteCareTask() {
  const taskId = deletingCareTaskId.value
  if (!taskId) return
  const ok = await run(() => petsStore.removeCareTask(props.petId, taskId), {
    key: 'care-delete',
    success: t('petCare.taskDeleted'),
    error: t('petCare.deleteError'),
  })
  if (ok) deletingCareTaskId.value = null
}
</script>

<template>
  <!-- ═══ Pflege & Termine ═══ -->
  <section class="section">
    <div class="section-header">
      <h3 class="section-title">{{ $t('petCare.title') }}</h3>
      <button class="icon-btn tap-target" @click="openAddCareTaskDialog" :aria-label="$t('petCare.addTask')">
        <PhPlus :size="20" weight="bold" />
      </button>
    </div>

    <div v-if="sortedCareTasks.length === 0" class="empty-hint">
      {{ $t('petCare.noTasks') }}
    </div>

    <BaseCard v-for="task in sortedCareTasks" :key="task.id" class="care-task-card">
      <div class="care-task-card__content">
        <div class="care-task-card__info">
          <span class="care-task-card__name">{{ task.name }}</span>
          <span class="care-task-card__meta">
            {{ $t('petCare.interval', { days: task.interval_days }) }}
          </span>
          <span
            class="care-task-card__due"
            :class="{ 'care-task-card__due--overdue': isOverdue(task) }"
          >
            {{ $t('petCare.dueAt', { date: formatDate(task.next_due_at) }) }}
            <span v-if="isOverdue(task)" class="overdue-badge">
              {{ $t('petCare.overdue') }}
            </span>
          </span>
        </div>
        <div class="care-task-card__actions">
          <BaseButton
            variant="primary"
            size="sm"
            :loading="isPending(`complete-${task.id}`)"
            @click="handleCompleteCareTask(task.id)"
          >
            <PhCheck :size="20" weight="bold" />
            {{ $t('petCare.complete') }}
          </BaseButton>
          <button
            class="icon-btn icon-btn--danger tap-target"
            @click="confirmDeleteCareTask(task.id)"
            :aria-label="$t('common.delete')"
          >
            <PhTrash :size="20" />
          </button>
        </div>
      </div>
    </BaseCard>
  </section>

  <!-- ═══ Add Care Task Dialog ═══ -->
  <BaseDialog
    :open="showCareTaskDialog"
    :title="$t('petCare.addTask')"
    @close="closeCareTaskDialog"
  >
    <form id="pet-care-form" class="dialog-form" @submit.prevent="handleSaveCareTask">
      <BaseInput
        v-model="careTaskName"
        :label="$t('petCare.name')"
        :placeholder="$t('petCare.name')"
      />
      <BaseInput
        v-model="careTaskInterval"
        :label="$t('petCare.intervalDays')"
        :placeholder="$t('petCare.intervalDays')"
        :error="careTaskIntervalError || undefined"
        inputmode="numeric"
      />
      <BaseInput
        v-model="careTaskDueDate"
        :label="$t('petCare.nextDueDate')"
        type="date"
      />
    </form>
    <template #footer>
      <div class="dialog-actions">
        <BaseButton variant="ghost" @click="closeCareTaskDialog">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton
          variant="primary"
          type="submit"
          form="pet-care-form"
          :disabled="!careTaskName.trim() || !careTaskInterval || !careTaskDueDate || careTaskSaving"
          :loading="careTaskSaving"
        >
          {{ $t('common.save') }}
        </BaseButton>
      </div>
    </template>
  </BaseDialog>

  <!-- ═══ Delete Care Task Confirm ═══ -->
  <BaseDialog
    :open="!!deletingCareTaskId"
    :title="$t('petCare.deleteConfirm')"
    danger
    @close="cancelDeleteCareTask"
  >
    <template #footer>
      <div class="dialog-actions">
        <BaseButton variant="ghost" @click="cancelDeleteCareTask">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton variant="danger" :loading="isPending('care-delete')" @click="handleDeleteCareTask">
          {{ $t('common.delete') }}
        </BaseButton>
      </div>
    </template>
  </BaseDialog>
</template>

<style scoped>
/* ── Section ── */
.section {
  margin-bottom: var(--space-4);
}

/* ── Section Header (Care Tasks) ── */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}

.section-title {
  font-family: var(--font-display);
  font-size: var(--text-title-card);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  margin: 0;
}

.icon-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--sub);
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
}

.icon-btn:hover {
  color: var(--ink);
  background: var(--chip);
}

.icon-btn--danger:hover {
  color: var(--color-danger);
}

.empty-hint {
  text-align: center;
  font-size: var(--text-sm);
  color: var(--sub);
  padding: var(--space-4) 0;
  font-style: italic;
}

/* ── Care Task Cards ── */
.care-task-card {
  margin-bottom: var(--space-2);
}

.care-task-card__content {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-3);
}

.care-task-card__info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  min-width: 0;
}

.care-task-card__name {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.care-task-card__meta {
  font-size: var(--text-xs);
  color: var(--sub);
}

.care-task-card__due {
  font-size: var(--text-xs);
  color: var(--sub);
  display: flex;
  align-items: center;
  gap: var(--space-1);
  flex-wrap: wrap;
}

.care-task-card__due--overdue {
  color: var(--color-danger);
  font-weight: var(--font-weight-semibold);
}

.overdue-badge {
  background: var(--color-danger);
  color: var(--color-on-danger);
  border-radius: var(--radius-full);
  padding: var(--badge-padding);
  font-size: var(--text-badge);
  font-weight: var(--font-weight-medium);
}

.care-task-card__actions {
  display: flex;
  align-items: center;
  /* Abstand, damit sich die 44-px-Tap-Flächen (.tap-target) nicht überlappen */
  gap: var(--space-3);
  flex-shrink: 0;
}

/* ── Dialog Form ── */
.dialog-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
