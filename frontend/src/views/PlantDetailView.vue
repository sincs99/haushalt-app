<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { usePlantsStore } from '../stores/plants'
import { useAuthStore } from '../stores/auth'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useLoader } from '../composables/useLoader'
import { imageUploadErrorReason } from '../utils/imageUpload'
import { useProtectedImage } from '../composables/useProtectedImage'
import { usePhotoUpload } from '../composables/usePhotoUpload'
import { formatDate } from '../utils/dates'
import { careTaskName, daysUntil, dueText } from '../utils/plantCare'
import type { AiPlantCareAdvice, Plant, PlantCareLog, PlantCareTask, PlantCareType } from '../types'
import {
  PhArrowLeft, PhPencilSimple, PhPlus, PhCheck, PhTrash, PhCamera, PhPlant,
} from '@phosphor-icons/vue'
import AiPlantCareCard from '../components/AiPlantCareCard.vue'
import BaseCard from '../components/ui/BaseCard.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import BaseErrorState from '../components/ui/BaseErrorState.vue'

const route = useRoute()
const router = useRouter()
const plantsStore = usePlantsStore()
const authStore = useAuthStore()
const { on, off, onReconnect, offReconnect } = useSocket()
const { showToast, notifyError } = useToast()
const { run, isPending } = useAsyncAction()
const { t } = useI18n()

const plantId = computed(() => route.params.id as string)
// Erst nach dem ersten Ladeversuch „nicht gefunden“ oder Fehler zeigen
const loaded = ref(false)

const plant = computed<Plant | undefined>(() =>
  plantsStore.plants.find(p => p.id === plantId.value),
)

const sortedCareTasks = computed(() =>
  [...plantsStore.careTasks].sort((a, b) => a.next_due_at.localeCompare(b.next_due_at)),
)

// ── Foto ──

const fileInputRef = ref<HTMLInputElement | null>(null)


const householdId = computed(() => authStore.currentHouseholdId)
const photoFileId = computed(() => plant.value?.photo_file_id ?? null)
const { objectUrl: photoObjectUrl } = useProtectedImage(householdId, photoFileId)

const { uploading: photoUploading, upload: uploadPhoto } = usePhotoUpload({
  householdId,
  entityId: plantId,
  fileId: photoFileId,
  update: (hid, id, fileId) => plantsStore.updatePlant(id, { photo_file_id: fileId }, hid),
})

async function handlePhotoUpload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    if (await uploadPhoto(file)) showToast(t('plants.photoUploadSuccess'), 'success')
  } catch (error) {
    notifyError(t('plants.photoUploadErrorReason', { reason: imageUploadErrorReason(error) }))
  }
}

// ── Lifecycle ──

async function loadAll() {
  await Promise.all([
    plantsStore.fetchPlants(),
    plantsStore.fetchCareStatus(),
    plantsStore.fetchMembers(),
    plantsStore.fetchCareTasks(plantId.value),
    plantsStore.fetchCareLog(plantId.value),
  ])
}

// Ladefehler → Fehlerzustand mit „Erneut versuchen“ (statt „Pflanze nicht gefunden“)
const { loadError, reloading, reload } = useLoader(loadAll)

onMounted(async () => {
  await reload()
  loaded.value = true

  on('plant_updated', handleSocketPlantUpdated)
  on('plant_deleted', handleSocketPlantDeleted)
  on('plant_care_logged', handleSocketCareLogged)
  onReconnect(handleReconnect)
})

onUnmounted(() => {
  off('plant_updated', handleSocketPlantUpdated)
  off('plant_deleted', handleSocketPlantDeleted)
  off('plant_care_logged', handleSocketCareLogged)
  offReconnect(handleReconnect)
})

// Navigation zwischen zwei Pflanzen (z.B. über Push-Link) lädt neu
watch([plantId, householdId], () => {
  reload()
})

// ── Socket Handlers ──
// (Pflegeaufgaben-Events werden global in App.vue verarbeitet)

function handleSocketPlantUpdated(data: Plant) {
  plantsStore.handlePlantUpdated(data)
}

function handleSocketPlantDeleted(data: { id: string }) {
  plantsStore.handlePlantDeleted(data)
  if (data.id === plantId.value) {
    router.replace('/plants')
  }
}

function handleSocketCareLogged(data: PlantCareLog) {
  plantsStore.handleCareLogged(data)
}

function handleReconnect() {
  reload()
}

// ── Helpers ──

function isOverdue(task: PlantCareTask): boolean {
  return daysUntil(task.next_due_at) < 0
}

function getMemberName(userId: string | null): string {
  if (!userId) return t('common.unknown')
  const member = plantsStore.members.find(m => m.id === userId)
  return member?.display_name ?? t('common.formerMember')
}

function formatLogTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('de-CH', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
  })
}

// ── Edit Plant Dialog ──

const showEditDialog = ref(false)
const editName = ref('')
const editSpecies = ref('')
const editLocation = ref('')
const editNotes = ref('')
const editCareNotes = ref('')
const editSaving = computed(() => isPending('edit'))

function openEditDialog() {
  if (!plant.value) return
  editName.value = plant.value.name
  editSpecies.value = plant.value.species ?? ''
  editLocation.value = plant.value.location ?? ''
  editNotes.value = plant.value.notes ?? ''
  editCareNotes.value = plant.value.care_notes ?? ''
  showEditDialog.value = true
}

async function handleSaveEdit() {
  const name = editName.value.trim()
  if (!name) return

  const ok = await run(() => plantsStore.updatePlant(plantId.value, {
    name,
    species: editSpecies.value.trim() || null,
    location: editLocation.value.trim() || null,
    notes: editNotes.value.trim() || null,
    care_notes: editCareNotes.value.trim() || null,
  }), { key: 'edit', success: t('plants.updated'), error: t('plants.updateError') })
  if (ok) showEditDialog.value = false
}

// ── KI-Pflegehinweise ──

const adviceApplying = ref(false)
const adviceApplied = ref(false)

// Neue Pflanze (Navigation) → Zustand zurücksetzen
watch(plantId, () => { adviceApplied.value = false })

async function handleApplyAdvice(advice: AiPlantCareAdvice) {
  if (!plant.value || adviceApplying.value) return
  adviceApplying.value = true
  try {
    await plantsStore.applyCareAdvice(plant.value, advice)
    adviceApplied.value = true
    showToast(t('ai.plant.applied'), 'success')
  } catch (err) {
    notifyError(t('ai.plant.applyError'), err)
  } finally {
    adviceApplying.value = false
  }
}

// ── Add Care Task Dialog ──

const CARE_TYPES: PlantCareType[] = ['water', 'fertilize', 'repot', 'mist', 'other']
const DEFAULT_INTERVALS: Record<PlantCareType, number> = {
  water: 7, fertilize: 30, repot: 365, mist: 3, other: 30,
}

const showTaskDialog = ref(false)
const taskType = ref<PlantCareType>('water')
const taskLabel = ref('')
const taskInterval = ref('7')
const taskDueDate = ref('')
const taskSaving = computed(() => isPending('task'))
// Inline-Fehler am Intervall-Feld (statt nur Toast)
const taskIntervalError = ref('')

watch(taskInterval, () => { taskIntervalError.value = '' })

function openAddTaskDialog() {
  taskType.value = 'water'
  taskLabel.value = ''
  taskInterval.value = String(DEFAULT_INTERVALS.water)
  taskDueDate.value = ''
  taskIntervalError.value = ''
  showTaskDialog.value = true
}

function selectTaskType(type: PlantCareType) {
  taskType.value = type
  taskInterval.value = String(DEFAULT_INTERVALS[type])
}

async function handleSaveTask() {
  const raw = taskInterval.value.trim()
  const interval = Number(raw)
  if (!/^\d+$/.test(raw) || interval < 1 || interval > 3650) {
    taskIntervalError.value = t('plants.invalidInterval')
    return
  }

  const ok = await run(() => plantsStore.createCareTask(plantId.value, {
    care_type: taskType.value,
    label: taskLabel.value.trim() || undefined,
    interval_days: interval,
    next_due_at: taskDueDate.value || undefined,
  }), { key: 'task', success: t('plants.taskCreated'), error: t('plants.taskCreateError') })
  if (ok) showTaskDialog.value = false
}

// ── Complete / Delete Care Task ──

// Kein Undo: das Backend kann Pflege-Log-Einträge nicht löschen.
function handleComplete(taskId: string) {
  return run(() => plantsStore.completeCareTask(plantId.value, taskId), {
    key: `complete-${taskId}`,
    success: (log) => {
      // null: heute schon erledigt (auch von jemand anderem) → kein zweiter Eintrag (CASA-29)
      if (log === null) return t('plants.alreadyDoneToday')
      const task = plantsStore.careTasks.find(c => c.id === taskId)
      return task ? t('plants.completed', { date: formatDate(task.next_due_at) }) : undefined
    },
    error: t('plants.careError'),
  })
}

const deletingTaskId = ref<string | null>(null)

async function handleDeleteTask() {
  const taskId = deletingTaskId.value
  if (!taskId) return
  const ok = await run(() => plantsStore.removeCareTask(plantId.value, taskId), {
    key: 'delete-task',
    success: t('plants.taskDeleted'),
    error: t('plants.taskDeleteError'),
  })
  if (ok) deletingTaskId.value = null
}
</script>

<template>
  <div class="view-page">
    <!-- ═══ Loading State ═══ -->
    <div v-if="!loaded || (reloading && !plant)" class="skeleton-list">
      <BaseSkeleton width="120px" height="28px" />
      <BaseSkeleton width="100%" height="120px" />
      <BaseSkeleton width="100%" height="180px" />
    </div>

    <!-- ═══ Ladefehler ═══ -->
    <div v-else-if="loadError && !plant">
      <BaseErrorState :retrying="reloading" @retry="reload" />
      <div class="not-found__back">
        <BaseButton variant="ghost" size="sm" @click="router.push('/plants')">
          {{ $t('common.back') }}
        </BaseButton>
      </div>
    </div>

    <!-- ═══ Not found ═══ -->
    <div v-else-if="!plant" class="not-found">
      <p>{{ $t('plants.notFound') }}</p>
      <BaseButton variant="secondary" size="sm" @click="router.push('/plants')">
        {{ $t('common.back') }}
      </BaseButton>
    </div>

    <template v-else>
      <!-- ═══ Foto ═══ -->
      <div class="plant-photo-section">
        <div class="plant-photo-wrapper">
          <div class="plant-photo" :class="{ 'plant-photo--placeholder': !photoObjectUrl }">
            <img v-if="photoObjectUrl" :src="photoObjectUrl" :alt="plant.name" class="plant-photo__img" />
            <PhPlant v-else :size="48" class="plant-photo__placeholder-icon" />
          </div>
          <button
            class="plant-photo__camera-btn tap-target"
            :disabled="photoUploading"
            :aria-label="$t('plants.changePhoto')"
            @click="fileInputRef?.click()"
          >
            <PhCamera :size="16" />
          </button>
        </div>
        <span v-if="photoUploading" class="plant-photo__upload-status">
          {{ $t('plants.photoUploading') }}
        </span>
      </div>
      <input
        ref="fileInputRef"
        type="file"
        accept="image/*"
        class="plant-photo__input"
        @change="handlePhotoUpload"
      />

      <!-- ═══ Header ═══ -->
      <div class="detail-header">
        <button class="back-btn tap-target" :aria-label="$t('common.back')" @click="router.back()">
          <PhArrowLeft :size="24" weight="bold" />
        </button>
        <div class="detail-header__info">
          <h1 class="detail-header__name">{{ plant.name }}</h1>
          <span v-if="plant.species || plant.location" class="detail-header__sub">
            {{ [plant.species, plant.location].filter(Boolean).join(' · ') }}
          </span>
        </div>
        <button class="edit-btn tap-target" :aria-label="$t('common.edit')" @click="openEditDialog">
          <PhPencilSimple :size="20" weight="bold" />
        </button>
      </div>

      <!-- Teilweise nicht geladen (z. B. Aufgaben/Verlauf): Hinweis statt leerer Listen -->
      <BaseErrorState v-if="loadError" :retrying="reloading" @retry="reload" />

      <!-- ═══ Notizen / Pflegehinweise ═══ -->
      <BaseCard v-if="plant.notes || plant.care_notes" class="info-card">
        <div v-if="plant.care_notes" class="info-block">
          <span class="info-block__label">{{ $t('plants.careNotes') }}</span>
          <p class="info-block__text">{{ plant.care_notes }}</p>
        </div>
        <div v-if="plant.notes" class="info-block">
          <span class="info-block__label">{{ $t('plants.notes') }}</span>
          <p class="info-block__text">{{ plant.notes }}</p>
        </div>
      </BaseCard>

      <!-- ═══ KI-Pflegehinweise (nur mit Server-Schlüssel + Haushalts-Opt-in) ═══ -->
      <AiPlantCareCard
        :key="plant.id"
        class="ai-care"
        :plant-name="plant.species || plant.name"
        :location="plant.location ?? undefined"
        :apply-label="$t('ai.plant.applyToPlant')"
        :existing-tasks="plantsStore.careTasks"
        :busy="adviceApplying"
        :done="adviceApplied"
        @apply="handleApplyAdvice"
      />

      <!-- ═══ Pflege ═══ -->
      <section class="section">
        <div class="section-header">
          <h2 class="section-title">{{ $t('plants.careTasks') }}</h2>
          <BaseButton variant="secondary" size="sm" @click="openAddTaskDialog">
            <PhPlus :size="16" weight="bold" />
            {{ $t('plants.addTask') }}
          </BaseButton>
        </div>

        <div v-if="sortedCareTasks.length === 0" class="empty-hint">
          {{ $t('plants.noTasks') }}
        </div>

        <BaseCard v-for="task in sortedCareTasks" :key="task.id" class="care-task-card">
          <div class="care-task-card__content">
            <div class="care-task-card__info">
              <span class="care-task-card__name">{{ careTaskName(task, t) }}</span>
              <span class="care-task-card__meta">
                {{ $t('plants.every', { days: task.interval_days }) }}
              </span>
              <span
                class="care-task-card__due"
                :class="{ 'care-task-card__due--overdue': isOverdue(task) }"
              >
                {{ $t('plants.dueAt', { date: formatDate(task.next_due_at) }) }}
                <span v-if="daysUntil(task.next_due_at) <= 0" class="due-badge"
                  :class="isOverdue(task) ? 'due-badge--overdue' : 'due-badge--today'">
                  {{ dueText(task.next_due_at, t) }}
                </span>
              </span>
            </div>
            <div class="care-task-card__actions">
              <BaseButton
                variant="primary"
                size="sm"
                :loading="isPending(`complete-${task.id}`)"
                @click="handleComplete(task.id)"
              >
                <PhCheck :size="20" weight="bold" />
                {{ $t('plants.complete') }}
              </BaseButton>
              <button
                class="icon-btn icon-btn--danger tap-target"
                :aria-label="$t('common.delete')"
                @click="deletingTaskId = task.id"
              >
                <PhTrash :size="20" />
              </button>
            </div>
          </div>
        </BaseCard>
      </section>

      <!-- ═══ Pflege-Verlauf ═══ -->
      <section class="section">
        <h2 class="section-title">{{ $t('plants.careLog') }}</h2>
        <div v-if="plantsStore.careLog.length === 0" class="empty-hint">
          {{ $t('plants.noLog') }}
        </div>
        <BaseCard v-else>
          <ul class="log-list">
            <li v-for="entry in plantsStore.careLog" :key="entry.id" class="log-row">
              <span class="log-row__title">{{ careTaskName(entry, t) }}</span>
              <span class="log-row__meta">
                {{ $t('plants.loggedBy', { name: getMemberName(entry.done_by_user_id), date: formatLogTime(entry.done_at) }) }}
              </span>
              <span v-if="entry.note" class="log-row__note">{{ entry.note }}</span>
            </li>
          </ul>
        </BaseCard>
      </section>
    </template>

    <!-- ═══ Edit Plant Dialog ═══ -->
    <BaseDialog :open="showEditDialog" :title="$t('plants.editPlant')" @close="showEditDialog = false">
      <form id="plant-edit-form" class="dialog-form" @submit.prevent="handleSaveEdit">
        <BaseInput v-model="editName" :label="$t('plants.name')" :placeholder="$t('plants.name')" />
        <BaseInput v-model="editSpecies" :label="$t('plants.species')" :placeholder="$t('plants.speciesPlaceholder')" />
        <BaseInput v-model="editLocation" :label="$t('plants.location')" :placeholder="$t('plants.locationPlaceholder')" />
        <BaseInput v-model="editNotes" :label="$t('plants.notes')" :placeholder="$t('plants.notes')" />
        <div class="textarea-field">
          <label for="plant-edit-care-notes" class="textarea-field__label">{{ $t('plants.careNotes') }}</label>
          <textarea
            id="plant-edit-care-notes"
            v-model="editCareNotes"
            class="textarea-field__input"
            rows="4"
            maxlength="2000"
            :placeholder="$t('plants.careNotes')"
          />
        </div>
      </form>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="showEditDialog = false">{{ $t('common.cancel') }}</BaseButton>
          <BaseButton
            variant="primary"
            type="submit"
            form="plant-edit-form"
            :disabled="!editName.trim() || editSaving"
            :loading="editSaving"
          >
            {{ $t('common.save') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- ═══ Add Care Task Dialog ═══ -->
    <BaseDialog :open="showTaskDialog" :title="$t('plants.addTask')" @close="showTaskDialog = false">
      <form id="plant-task-form" class="dialog-form" @submit.prevent="handleSaveTask">
        <div class="type-picker">
          <span class="type-picker__label">{{ $t('plants.careType') }}</span>
          <div class="type-picker__chips">
            <button
              v-for="type in CARE_TYPES"
              :key="type"
              type="button"
              class="type-chip tap-target"
              :class="{ 'type-chip--active': taskType === type }"
              @click="selectTaskType(type)"
            >
              {{ $t(`plants.careTypes.${type}`) }}
            </button>
          </div>
        </div>
        <BaseInput v-model="taskLabel" :label="$t('plants.taskLabel')" :placeholder="$t('plants.taskLabel')" />
        <BaseInput
          v-model="taskInterval"
          :label="$t('plants.intervalDays')"
          :error="taskIntervalError || undefined"
          inputmode="numeric"
        />
        <BaseInput v-model="taskDueDate" :label="$t('plants.nextDueDate')" type="date" />
      </form>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="showTaskDialog = false">{{ $t('common.cancel') }}</BaseButton>
          <BaseButton
            variant="primary"
            type="submit"
            form="plant-task-form"
            :disabled="!taskInterval || taskSaving"
            :loading="taskSaving"
          >
            {{ $t('common.save') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>

    <!-- ═══ Delete Care Task Confirm ═══ -->
    <BaseDialog :open="!!deletingTaskId" :title="$t('plants.deleteTaskConfirm')" danger @close="deletingTaskId = null">
      <p class="delete-hint">{{ $t('plants.deleteTaskHint') }}</p>
      <template #footer>
        <div class="dialog-actions">
          <BaseButton variant="ghost" @click="deletingTaskId = null">{{ $t('common.cancel') }}</BaseButton>
          <BaseButton
            variant="danger"
            :loading="isPending('delete-task')"
            @click="handleDeleteTask"
          >
            {{ $t('common.delete') }}
          </BaseButton>
        </div>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.not-found {
  text-align: center;
  padding: var(--space-8) 0;
  color: var(--sub);
}

.not-found__back {
  display: flex;
  justify-content: center;
}

.delete-hint {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--sub);
}

/* ── Mehrzeiliges Feld (Pflegehinweise) ── */
.textarea-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.textarea-field__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
}

.textarea-field__input {
  width: 100%;
  padding: var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
  font-family: var(--font-family);
  font-size: var(--text-base); /* 16px — verhindert iOS-Zoom */
  line-height: var(--line-height-normal);
  color: var(--ink);
  background-color: var(--card);
  resize: vertical;
}

.textarea-field__input::placeholder {
  color: var(--sub);
}

.textarea-field__input:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}

/* ── Photo ── */
.plant-photo-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: var(--space-4);
}

.plant-photo-wrapper {
  position: relative;
}

.plant-photo {
  width: 112px;
  height: 112px;
  border-radius: 50%;
  overflow: hidden;
  border: 2px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
}

.plant-photo--placeholder {
  background: var(--chip);
}

.plant-photo__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.plant-photo__placeholder-icon {
  color: var(--sub);
}

.plant-photo__camera-btn {
  position: absolute;
  bottom: 0;
  right: 0;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--color-primary);
  color: var(--color-on-primary);
  border: 2px solid var(--card);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: var(--shadow-card);
  transition: transform var(--transition-fast);
}

.plant-photo__camera-btn:active {
  transform: scale(0.92);
}

.plant-photo__camera-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.plant-photo__input {
  display: none;
}

.plant-photo__upload-status {
  font-size: var(--text-xs);
  color: var(--sub);
  margin-top: var(--space-1);
}

/* ── Header ── */
.detail-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.detail-header__info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.detail-header__name {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
  margin: 0;
}

.detail-header__sub {
  font-size: var(--text-sm);
  color: var(--sub);
}

.back-btn,
.edit-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--ink);
  padding: var(--space-2);
  border-radius: var(--radius-full);
  display: flex;
}

.back-btn:hover,
.edit-btn:hover {
  background: var(--chip);
}

/* ── Info ── */
.info-card {
  margin-bottom: var(--space-4);
}

.info-block + .info-block {
  margin-top: var(--space-3);
}

.info-block__label {
  font-size: var(--text-xs);
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.info-block__text {
  margin: var(--space-1) 0 0;
  font-size: var(--text-sm);
  color: var(--ink);
  white-space: pre-wrap;
}

/* ── Sections ── */
.section {
  margin-bottom: var(--space-5);
}

/* KI-Block steht frei zwischen Notizen und Pflege: eigener Abstand wie eine Section */
.ai-care {
  margin-bottom: var(--space-6);
}

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
  margin: 0 0 var(--space-3) 0;
}

.section-header .section-title {
  margin: 0;
}

.empty-hint {
  font-size: var(--text-sm);
  color: var(--sub);
  font-style: italic;
  padding: var(--space-2) 0;
}

/* ── Care Tasks ── */
.care-task-card {
  margin-bottom: var(--space-2);
}

.care-task-card__content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.care-task-card__info {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  min-width: 0;
}

.care-task-card__name {
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.care-task-card__meta {
  font-size: var(--text-xs);
  color: var(--sub);
}

.care-task-card__due {
  font-size: var(--text-sm);
  color: var(--sub);
}

.care-task-card__due--overdue {
  color: var(--color-danger);
}

.care-task-card__actions {
  display: flex;
  align-items: center;
  /* Abstand, damit sich die 44-px-Tap-Flächen (.tap-target) nicht überlappen */
  gap: var(--space-3);
  flex-shrink: 0;
}

.due-badge {
  margin-left: var(--space-1);
  font-size: var(--text-badge);
  font-weight: var(--font-weight-semibold);
  padding: var(--badge-padding);
  border-radius: var(--radius-full);
  color: var(--color-on-danger);
}

.due-badge--overdue {
  background: var(--color-danger);
}

.due-badge--today {
  background: var(--color-warning-soft);
  color: var(--color-warning-strong);
}

.icon-btn {
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--space-2);
  border-radius: var(--radius-full);
  display: flex;
  color: var(--sub);
}

.icon-btn--danger {
  color: var(--color-danger);
}

.icon-btn:hover {
  background: var(--chip);
}

/* ── Log ── */
.log-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
}

.log-row {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--line);
}

.log-row:last-child {
  border-bottom: none;
}

.log-row__title {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

.log-row__meta,
.log-row__note {
  font-size: var(--text-xs);
  color: var(--sub);
}

.log-row__note {
  font-style: italic;
}

/* ── Dialogs ── */
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

.type-picker__label {
  display: block;
  font-size: var(--text-sm);
  color: var(--sub);
  margin-bottom: var(--space-2);
}

.type-picker__chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.type-chip {
  border: none;
  cursor: pointer;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-full);
  background: var(--chip);
  color: var(--ink);
  font-size: var(--text-sm);
}

.type-chip--active {
  background: var(--acc);
  color: var(--color-on-accent);
}
</style>
