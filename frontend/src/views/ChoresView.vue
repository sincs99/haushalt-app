<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChoresStore } from '../stores/chores'
import { useAuthStore } from '../stores/auth'
import { useToast } from '../composables/useToast'
import { formatDateShort } from '../utils/dates'
import type { ChoreInfo, ChoreAssignmentInfo, ChoreCreatePayload, ChoreUpdatePayload } from '../types'
import { PhBroom, PhCalendarCheck, PhPencilSimple, PhX } from '@phosphor-icons/vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseAvatar from '../components/ui/BaseAvatar.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import BasePillTabs from '../components/ui/BasePillTabs.vue'
import PageHeader from '../components/ui/PageHeader.vue'

const choresStore = useChoresStore()
const authStore = useAuthStore()
const { showToast } = useToast()
const { t, locale } = useI18n()

// ── Lifecycle ──
onMounted(() => {
  choresStore.fetchChores()
  choresStore.fetchAssignments()
  choresStore.fetchMembers()
})

// ── Date Helpers ──
function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function formatWeekday(dateStr: string): string {
  return new Intl.DateTimeFormat(locale.value, { weekday: 'long' }).format(new Date(dateStr + 'T00:00:00'))
}


function isOverdue(assignment: ChoreAssignmentInfo): boolean {
  return !assignment.completed_at && assignment.due_date < todayStr()
}

function isToday(dateStr: string): boolean {
  return dateStr === todayStr()
}

// ── Member Helpers ──
function getMemberName(userId: string | null): string {
  if (!userId) return t('chores.unassigned')
  const member = choresStore.members.find(m => m.id === userId)
  return member?.display_name ?? t('common.unknown')
}

function getChoreName(choreId: string): string {
  const chore = choresStore.chores.find(c => c.id === choreId)
  return chore?.title ?? t('common.unknown')
}

// ── "Nur meine" Filter ──
const filterTab = ref('all')

const filteredAssignments = computed(() => {
  if (filterTab.value === 'all') return choresStore.assignments
  return choresStore.assignments.filter(a => a.assigned_user_id === authStore.user?.id)
})

const filterTabs = computed(() => [
  { key: 'all', label: t('chores.filterAll') },
  { key: 'mine', label: t('chores.filterMine') },
])

// ── Sektion A: Assignments gruppiert nach Tag ──
interface DayGroup {
  date: string
  label: string
  isToday: boolean
  isOverdue: boolean
  assignments: ChoreAssignmentInfo[]
}

const assignmentsByDay = computed<DayGroup[]>(() => {
  const today = todayStr()
  const grouped = new Map<string, ChoreAssignmentInfo[]>()

  for (const a of filteredAssignments.value) {
    const existing = grouped.get(a.due_date)
    if (existing) {
      existing.push(a)
    } else {
      grouped.set(a.due_date, [a])
    }
  }

  // Sortiert nach Datum
  const sorted = [...grouped.entries()].sort((a, b) => a[0].localeCompare(b[0]))

  return sorted.map(([date, items]) => ({
    date,
    label: date === today ? t('chores.today') : formatWeekday(date),
    isToday: date === today,
    isOverdue: date < today,
    assignments: items,
  }))
})

// ── Assignment Actions ──
async function handleToggleAssignment(assignment: ChoreAssignmentInfo) {
  try {
    if (assignment.completed_at) {
      await choresStore.uncompleteAssignment(assignment.id)
    } else {
      await choresStore.completeAssignment(assignment.id)
    }
  } catch {
    showToast(t('chores.completeError'))
  }
}

// Reassign-Dialog
const reassignDialogId = ref<string | null>(null)

function openReassignDialog(assignmentId: string) {
  reassignDialogId.value = assignmentId
}

function closeReassignDialog() {
  reassignDialogId.value = null
}

async function handleReassign(assignmentId: string, userId: string) {
  try {
    await choresStore.reassignAssignment(assignmentId, userId)
    closeReassignDialog()
  } catch {
    showToast(t('chores.updateError'))
  }
}

// ── Sektion B: Chores CRUD ──
const showChoreForm = ref(false)
const editingChoreId = ref<string | null>(null)

// Formular-Felder
const formTitle = ref('')
const formDescription = ref('')
const formRecurrence = ref<'weekly' | 'biweekly' | 'monthly'>('weekly')
const formWeekday = ref(0)
const formDayOfMonth = ref(1)
const formRotationOrder = ref<string[]>([])
const formActive = ref(true)
const formSaving = ref(false)

function resetForm() {
  formTitle.value = ''
  formDescription.value = ''
  formRecurrence.value = 'weekly'
  formWeekday.value = 0
  formDayOfMonth.value = 1
  formRotationOrder.value = choresStore.members.map(m => m.id)
  formActive.value = true
  editingChoreId.value = null
}

function openCreateForm() {
  resetForm()
  showChoreForm.value = true
}

function openEditForm(chore: ChoreInfo) {
  editingChoreId.value = chore.id
  formTitle.value = chore.title
  formDescription.value = chore.description ?? ''
  formRecurrence.value = chore.recurrence
  formWeekday.value = chore.weekday ?? 0
  formDayOfMonth.value = chore.day_of_month ?? 1
  formRotationOrder.value = [...chore.rotation_order]
  formActive.value = chore.active
  showChoreForm.value = true
}

function cancelForm() {
  showChoreForm.value = false
  editingChoreId.value = null
}

async function handleSaveChore() {
  const title = formTitle.value.trim()
  if (!title || formSaving.value) return

  formSaving.value = true
  try {
    if (editingChoreId.value) {
      // Update
      const payload: ChoreUpdatePayload = {
        title,
        description: formDescription.value.trim() || undefined,
        recurrence: formRecurrence.value,
        weekday: formRecurrence.value !== 'monthly' ? formWeekday.value : undefined,
        day_of_month: formRecurrence.value === 'monthly' ? formDayOfMonth.value : undefined,
        rotation_order: formRotationOrder.value,
        active: formActive.value,
      }
      await choresStore.updateChore(editingChoreId.value, payload)
    } else {
      // Create
      const payload: ChoreCreatePayload = {
        title,
        description: formDescription.value.trim() || undefined,
        recurrence: formRecurrence.value,
        weekday: formRecurrence.value !== 'monthly' ? formWeekday.value : undefined,
        day_of_month: formRecurrence.value === 'monthly' ? formDayOfMonth.value : undefined,
        rotation_order: formRotationOrder.value,
        active: formActive.value,
      }
      await choresStore.createChore(payload)
    }
    showChoreForm.value = false
    editingChoreId.value = null
  } catch {
    showToast(editingChoreId.value ? t('chores.updateError') : t('chores.createError'))
  } finally {
    formSaving.value = false
  }
}

// Delete mit Bestätigung
const deletingChoreId = ref<string | null>(null)

function confirmDelete(choreId: string) {
  deletingChoreId.value = choreId
}

function cancelDelete() {
  deletingChoreId.value = null
}

async function handleDelete() {
  if (!deletingChoreId.value) return
  try {
    await choresStore.removeChore(deletingChoreId.value)
    deletingChoreId.value = null
  } catch {
    showToast(t('chores.deleteError'))
  }
}

// ── Rotation-Order Umsortieren ──
function moveUp(index: number) {
  if (index <= 0) return
  const arr = formRotationOrder.value
  const temp = arr[index - 1]
  arr[index - 1] = arr[index]
  arr[index] = temp
}

function moveDown(index: number) {
  const arr = formRotationOrder.value
  if (index >= arr.length - 1) return
  const temp = arr[index + 1]
  arr[index + 1] = arr[index]
  arr[index] = temp
}

// ── Zusammenfassungs-Helfer ──
function rotationSummary(chore: ChoreInfo): string {
  return chore.rotation_order
    .map(uid => choresStore.members.find(m => m.id === uid)?.display_name ?? t('common.unknown'))
    .join(' → ')
}

function recurrenceSummary(chore: ChoreInfo): string {
  if (chore.recurrence === 'weekly') {
    const day = new Intl.DateTimeFormat(locale.value, { weekday: 'long' }).format(
      new Date(2024, 0, 1 + chore.weekday!) // 2024-01-01 ist Montag (weekday=0)
    )
    return `${t('chores.weekly')} ${day}`
  }
  if (chore.recurrence === 'biweekly') {
    const day = new Intl.DateTimeFormat(locale.value, { weekday: 'long' }).format(
      new Date(2024, 0, 1 + chore.weekday!)
    )
    return `${t('chores.biweekly')} ${day}`
  }
  if (chore.recurrence === 'monthly') {
    return `${t('chores.monthly')} ${t('chores.dayOfMonth', { day: chore.day_of_month })}`
  }
  return ''
}

// Weekday-Labels via Intl
const weekdayOptions = computed(() =>
  Array.from({ length: 7 }, (_, i) => ({
    value: i,
    label: new Intl.DateTimeFormat(locale.value, { weekday: 'long' }).format(new Date(2024, 0, 1 + i)),
  }))
)
</script>

<template>
  <div class="view-page">
    <PageHeader :title="$t('chores.title')" />

    <!-- Loading -->
    <div v-if="choresStore.loading" class="skeleton-list">
      <div class="skeleton-row" v-for="n in 3" :key="n">
        <BaseSkeleton width="22px" height="22px" rounded />
        <div style="flex: 1; display: flex; flex-direction: column; gap: 4px;">
          <BaseSkeleton :width="['75%', '60%', '85%'][n - 1]" height="16px" />
          <BaseSkeleton width="40%" height="12px" />
        </div>
      </div>
    </div>

    <!-- ═══ Sektion A: Diese Woche ═══ -->
    <section class="section">
      <h2 class="section__title">{{ $t('chores.thisWeek') }}</h2>

      <!-- Filter-Toggle -->
      <BasePillTabs
        v-model="filterTab"
        :tabs="filterTabs"
      />

      <BaseEmptyState
        v-if="!choresStore.loading && assignmentsByDay.length === 0"
        :icon="PhCalendarCheck"
        :title="$t('chores.noAssignments')"
      >
        <template #action>
          <BaseButton variant="primary" size="sm" @click="openCreateForm">
            {{ $t('chores.createFirst') }}
          </BaseButton>
        </template>
      </BaseEmptyState>

      <div v-else class="day-groups">
        <div
          v-for="group in assignmentsByDay"
          :key="group.date"
          class="day-group"
          :class="{
            'day-group--today': group.isToday,
            'day-group--overdue': group.isOverdue,
          }"
        >
          <div class="day-group__header">
            <span class="day-group__label">{{ group.label }}</span>
            <span class="day-group__date">{{ formatDateShort(group.date) }}</span>
            <span v-if="group.isOverdue" class="overdue-badge">{{ $t('chores.overdue') }}</span>
          </div>

          <ul class="assignment-list">
            <li
              v-for="assignment in group.assignments"
              :key="assignment.id"
              class="assignment-row"
              :class="{ 'assignment-row--done': !!assignment.completed_at }"
            >
              <div class="assignment-row__main" @click="handleToggleAssignment(assignment)">
                <span class="assignment-row__check">
                  <input
                    type="checkbox"
                    :checked="!!assignment.completed_at"
                    @click.stop
                    @change="handleToggleAssignment(assignment)"
                    class="assignment-row__checkbox"
                  />
                </span>
                <div class="assignment-row__content">
                  <span class="assignment-row__title">{{ getChoreName(assignment.chore_id) }}</span>
                  <span
                    v-if="assignment.completed_at && assignment.completed_by_user_id"
                    class="assignment-row__completed"
                  >
                    {{ $t('chores.completedBy', { name: getMemberName(assignment.completed_by_user_id) }) }}
                  </span>
                </div>
              </div>

              <div class="assignment-row__actions">
                <BaseAvatar
                  v-if="assignment.assigned_user_id"
                  :name="getMemberName(assignment.assigned_user_id)"
                  :userId="assignment.assigned_user_id"
                  size="sm"
                />
                <button
                  class="action-btn"
                  :title="$t('chores.reassignTo')"
                  :aria-label="$t('chores.reassignTo')"
                  @click="openReassignDialog(assignment.id)"
                >
                  👤
                </button>
              </div>

              <!-- Inline-Reassign-Dialog -->
              <div v-if="reassignDialogId === assignment.id" class="reassign-dropdown">
                <div class="reassign-dropdown__header">
                  <span>{{ $t('chores.reassignTo') }}</span>
                  <button class="action-btn" @click="closeReassignDialog"><PhX :size="16" /></button>
                </div>
                <button
                  v-for="member in choresStore.members"
                  :key="member.id"
                  class="reassign-dropdown__option"
                  :class="{ 'reassign-dropdown__option--active': member.id === assignment.assigned_user_id }"
                  @click="handleReassign(assignment.id, member.id)"
                >
                  <BaseAvatar :name="member.display_name" :userId="member.id" size="sm" />
                  {{ member.display_name }}
                </button>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </section>

    <!-- ═══ Sektion B: Ämtli verwalten ═══ -->
    <section class="section">
      <div class="section__header">
        <h2 class="section__title">{{ $t('chores.manageTitle') }}</h2>
        <BaseButton v-if="!showChoreForm" size="sm" @click="openCreateForm">
          {{ $t('chores.addChore') }}
        </BaseButton>
      </div>

      <!-- Erstellen/Bearbeiten-Formular -->
      <div v-if="showChoreForm" class="chore-form">
        <h3 class="chore-form__title">
          {{ editingChoreId ? $t('chores.editChore') : $t('chores.newChore') }}
        </h3>

        <form @submit.prevent="handleSaveChore" class="chore-form__fields">
          <!-- Titel -->
          <div class="form-field">
            <label class="form-label">{{ $t('chores.choreTitleLabel') }}</label>
            <input
              v-model="formTitle"
              type="text"
              class="form-input"
              :placeholder="$t('chores.choreTitlePlaceholder')"
              required
            />
          </div>

          <!-- Beschreibung -->
          <div class="form-field">
            <label class="form-label">{{ $t('chores.description') }}</label>
            <textarea
              v-model="formDescription"
              class="form-textarea"
              :placeholder="$t('chores.descriptionPlaceholder')"
              rows="2"
            />
          </div>

          <!-- Wiederholung -->
          <div class="form-field">
            <label class="form-label">{{ $t('chores.recurrence') }}</label>
            <select v-model="formRecurrence" class="form-input">
              <option value="weekly">{{ $t('chores.weekly') }}</option>
              <option value="biweekly">{{ $t('chores.biweekly') }}</option>
              <option value="monthly">{{ $t('chores.monthly') }}</option>
            </select>
          </div>

          <!-- Wochentag (bei weekly/biweekly) -->
          <div v-if="formRecurrence !== 'monthly'" class="form-field">
            <label class="form-label">{{ $t('chores.weekday') }}</label>
            <select v-model.number="formWeekday" class="form-input">
              <option v-for="opt in weekdayOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </option>
            </select>
          </div>

          <!-- Monatstag (bei monthly) -->
          <div v-if="formRecurrence === 'monthly'" class="form-field">
            <label class="form-label">{{ $t('chores.dayOfMonthLabel') }}</label>
            <input
              v-model.number="formDayOfMonth"
              type="number"
              min="1"
              max="31"
              class="form-input"
            />
          </div>

          <!-- Rotations-Reihenfolge -->
          <div class="form-field">
            <label class="form-label">{{ $t('chores.rotationOrder') }}</label>
            <p class="form-hint">{{ $t('chores.rotationHint') }}</p>
            <ul class="rotation-list">
              <li
                v-for="(uid, index) in formRotationOrder"
                :key="uid"
                class="rotation-item"
              >
                <BaseAvatar :name="getMemberName(uid)" :userId="uid" size="sm" />
                <span class="rotation-item__name">{{ getMemberName(uid) }}</span>
                <div class="rotation-item__actions">
                  <button
                    type="button"
                    class="action-btn"
                    :disabled="index === 0"
                    @click="moveUp(index)"
                    :aria-label="$t('chores.moveUp')"
                  >↑</button>
                  <button
                    type="button"
                    class="action-btn"
                    :disabled="index === formRotationOrder.length - 1"
                    @click="moveDown(index)"
                    :aria-label="$t('chores.moveDown')"
                  >↓</button>
                </div>
              </li>
            </ul>
          </div>

          <!-- Aktiv-Toggle -->
          <div class="form-field form-field--row">
            <label class="form-label">
              <input type="checkbox" v-model="formActive" class="form-checkbox" />
              {{ formActive ? $t('chores.active') : $t('chores.inactive') }}
            </label>
          </div>

          <!-- Actions -->
          <div class="chore-form__actions">
            <BaseButton type="submit" variant="primary" size="sm" :loading="formSaving">
              {{ $t('chores.saveChore') }}
            </BaseButton>
            <BaseButton type="button" variant="secondary" size="sm" @click="cancelForm">
              {{ $t('common.cancel') }}
            </BaseButton>
          </div>
        </form>
      </div>

      <!-- Chore-Liste -->
      <BaseEmptyState
        v-if="!choresStore.loading && choresStore.chores.length === 0 && !showChoreForm"
        :icon="PhBroom"
        :title="$t('chores.noChores')"
        :subtitle="$t('chores.noChoresSubtitle')"
      />

      <ul v-if="choresStore.chores.length > 0" class="chore-list">
        <li
          v-for="chore in choresStore.chores"
          :key="chore.id"
          class="chore-card"
          :class="{ 'chore-card--inactive': !chore.active }"
        >
          <div class="chore-card__main">
            <div class="chore-card__title-line">
              <span class="chore-card__title">{{ chore.title }}</span>
              <span v-if="!chore.active" class="inactive-badge">{{ $t('chores.inactive') }}</span>
            </div>
            <div class="chore-card__meta">
              <span class="chore-card__recurrence">{{ recurrenceSummary(chore) }}</span>
              <div class="chore-card__rotation">
                <BaseAvatar
                  v-for="uid in chore.rotation_order"
                  :key="uid"
                  :name="getMemberName(uid)"
                  :userId="uid"
                  size="sm"
                />
              </div>
            </div>
          </div>
          <div class="chore-card__actions">
            <button
              class="action-btn"
              @click="openEditForm(chore)"
              :title="$t('common.edit')"
              :aria-label="$t('common.edit')"
            ><PhPencilSimple :size="16" /></button>
            <button
              class="action-btn action-btn--danger"
              @click="confirmDelete(chore.id)"
              :title="$t('common.delete')"
              :aria-label="$t('common.delete')"
            ><PhX :size="16" /></button>
          </div>

          <!-- Delete-Bestätigung inline -->
          <div v-if="deletingChoreId === chore.id" class="delete-confirm">
            <p class="delete-confirm__text">{{ $t('chores.deleteConfirm') }}</p>
            <div class="delete-confirm__actions">
              <BaseButton variant="danger" size="sm" @click="handleDelete">
                {{ $t('common.delete') }}
              </BaseButton>
              <BaseButton variant="secondary" size="sm" @click="cancelDelete">
                {{ $t('common.cancel') }}
              </BaseButton>
            </div>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.view-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ── Skeleton Loading ── */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-2) 0;
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
}

/* ── Sektionen ── */
.section {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.section__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.section__title {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--ink);
}

/* ── Sektion A: Tag-Gruppen ── */
.day-groups {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.day-group {
  background: var(--color-surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  overflow: hidden;
}

.day-group--today {
  border-left: 3px solid var(--color-primary);
}

.day-group--overdue {
  border-left: 3px solid var(--color-danger);
}

.day-group__header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--color-neutral-50);
  border-bottom: 1px solid var(--color-neutral-200);
}

.day-group__label {
  font-weight: var(--font-weight-semibold);
  font-size: var(--text-base);
  color: var(--color-text);
  text-transform: capitalize;
}

.day-group__date {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.overdue-badge {
  font-size: var(--text-xs);
  color: var(--color-danger);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

/* ── Assignments ── */
.assignment-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.assignment-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--color-neutral-200);
  position: relative;
}

.assignment-row:last-child {
  border-bottom: none;
}

.assignment-row--done {
  opacity: 0.6;
}

.assignment-row__main {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
  min-width: 0;
  cursor: pointer;
  min-height: 44px;
  -webkit-user-select: none;
  user-select: none;
}

.assignment-row__check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}

.assignment-row__checkbox {
  width: 20px;
  height: 20px;
  accent-color: var(--color-primary);
  cursor: pointer;
}

.assignment-row__content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.assignment-row__title {
  font-size: var(--text-base);
  color: var(--color-text);
}

.assignment-row--done .assignment-row__title {
  text-decoration: line-through;
  color: var(--color-text-muted);
}

.assignment-row__completed {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.assignment-row__actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
}

/* ── Reassign-Dropdown ── */
.reassign-dropdown {
  width: 100%;
  background: var(--color-surface);
  border: 1px solid var(--color-neutral-200);
  border-radius: var(--radius-md);
  padding: var(--space-2);
  margin-top: var(--space-1);
  box-shadow: var(--shadow-overlay);
}

.reassign-dropdown__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-1) var(--space-2);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-neutral-200);
  margin-bottom: var(--space-1);
}

.reassign-dropdown__option {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2);
  border: none;
  border-radius: var(--radius-sm);
  background: none;
  font-size: var(--text-sm);
  font-family: var(--font-family);
  color: var(--color-text);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.reassign-dropdown__option:hover {
  background: var(--color-neutral-100);
}

.reassign-dropdown__option--active {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: var(--font-weight-medium);
}


/* ── Action Buttons ── */
.action-btn {
  background: none;
  border: none;
  padding: var(--space-1);
  cursor: pointer;
  font-size: var(--text-base);
  color: var(--color-text-muted);
  border-radius: var(--radius-sm);
  min-width: 32px;
  min-height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background var(--transition-fast), color var(--transition-fast);
}

.action-btn:hover {
  background: var(--color-neutral-100);
  color: var(--color-text);
}

.action-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.action-btn--danger:hover {
  background: #FFF5F5;
  color: var(--color-danger);
}

/* ── Sektion B: Chore-Formular ── */
.chore-form {
  background: var(--color-surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: var(--space-4);
}

.chore-form__title {
  margin: 0 0 var(--space-3) 0;
  font-size: var(--text-base);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text);
}

.chore-form__fields {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.chore-form__actions {
  display: flex;
  gap: var(--space-2);
  padding-top: var(--space-2);
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.form-field--row {
  flex-direction: row;
  align-items: center;
  gap: var(--space-2);
}

.form-label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.form-hint {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.form-input {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-family: var(--font-family);
  background: var(--color-surface);
  color: var(--color-text);
  transition: border-color var(--transition-fast);
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.form-textarea {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-family: var(--font-family);
  background: var(--color-surface);
  color: var(--color-text);
  resize: vertical;
  transition: border-color var(--transition-fast);
}

.form-textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.form-checkbox {
  width: 18px;
  height: 18px;
  accent-color: var(--color-primary);
  cursor: pointer;
}

/* ── Rotation-Liste ── */
.rotation-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.rotation-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2);
  background: var(--color-neutral-50);
  border-radius: var(--radius-sm);
}

.rotation-item__name {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--color-text);
}

.rotation-item__actions {
  display: flex;
  gap: var(--space-1);
}

/* ── Chore-Liste ── */
.chore-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.chore-card {
  background: var(--color-surface);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  padding: var(--space-3) var(--space-4);
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: var(--space-2);
}

.chore-card--inactive {
  opacity: 0.6;
}

.chore-card__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.chore-card__title-line {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.chore-card__title {
  font-size: var(--text-base);
  font-weight: var(--font-weight-medium);
  color: var(--color-text);
}

.inactive-badge {
  font-size: var(--text-xs);
  padding: 2px var(--space-2);
  border-radius: var(--radius-full);
  background: var(--color-neutral-200);
  color: var(--color-text-muted);
}

.chore-card__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.chore-card__recurrence {
  color: var(--color-text-secondary);
}

.chore-card__rotation {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.chore-card__actions {
  display: flex;
  gap: var(--space-1);
  flex-shrink: 0;
}

/* ── Delete-Bestätigung ── */
.delete-confirm {
  width: 100%;
  padding: var(--space-3);
  margin-top: var(--space-2);
  background: #FFF5F5;
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-danger);
}

.delete-confirm__text {
  margin: 0 0 var(--space-2) 0;
  font-size: var(--text-sm);
  color: var(--color-danger);
}

.delete-confirm__actions {
  display: flex;
  gap: var(--space-2);
}
/* ── Filter-Toggle ── */
.filter-toggle {
  display: flex;
  gap: var(--space-1);
  background: var(--color-neutral-100);
  border-radius: var(--radius-md);
  padding: var(--space-1);
  margin-bottom: var(--space-3);
}

.filter-chip {
  flex: 1;
  padding: var(--space-2) var(--space-3);
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-family: var(--font-family);
  transition: all 0.15s ease;
}

.filter-chip--active {
  background: var(--color-surface);
  color: var(--color-text);
  box-shadow: var(--shadow-sm);
}
</style>
