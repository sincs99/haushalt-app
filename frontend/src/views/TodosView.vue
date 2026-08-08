<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useTasksStore } from '../stores/tasks'
import { useTodosStore } from '../stores/todos'
import { useSocket } from '../composables/useSocket'
import { useToast } from '../composables/useToast'
import { formatDateShort } from '../utils/dates'
import type { UnifiedTask } from '../types'

import PageHeader from '../components/ui/PageHeader.vue'
import BasePillTabs from '../components/ui/BasePillTabs.vue'
import BaseCheckCircle from '../components/ui/BaseCheckCircle.vue'
import BaseAvatar from '../components/ui/BaseAvatar.vue'
import BaseDialog from '../components/ui/BaseDialog.vue'
import BaseInput from '../components/ui/BaseInput.vue'
import BaseButton from '../components/ui/BaseButton.vue'
import BaseEmptyState from '../components/ui/BaseEmptyState.vue'
import BaseSkeleton from '../components/ui/BaseSkeleton.vue'
import { PhPlus, PhRepeat, PhListChecks } from '@phosphor-icons/vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const { showToast } = useToast()
const socket = useSocket()

const authStore = useAuthStore()
const tasksStore = useTasksStore()
const todosStore = useTodosStore()

// ── Filter State ──
const activeFilter = ref('all')

// ── Create Dialog State ──
const showCreateDialog = ref(false)
const createTitle = ref('')
const createDescription = ref('')
const createDueDate = ref('')
const createAssignee = ref('')
const createTags = ref('')
const createLoading = ref(false)

// ── Helpers ──
function todayStr(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function endOfWeekStr(): string {
  const d = new Date()
  const day = d.getDay() // 0=Sun, 1=Mon..6=Sat
  // Sonntag dieser Woche: wenn heute Sonntag → heute, sonst nächster Sonntag
  const diff = day === 0 ? 7 : 7 - day // Sonntag → nächster Sonntag
  const sunday = new Date(d)
  sunday.setDate(d.getDate() + diff)
  return `${sunday.getFullYear()}-${String(sunday.getMonth() + 1).padStart(2, '0')}-${String(sunday.getDate()).padStart(2, '0')}`
}

function dateOnly(d: string | null): string | null {
  if (!d) return null
  return d.substring(0, 10) // "YYYY-MM-DD"
}

// ── Filter Tabs ──
const filterTabs = computed(() => {
  const tabs: Array<{ key: string; label: string }> = [
    { key: 'all', label: t('tasks.filterAll') },
    { key: 'shared', label: t('tasks.filterShared') },
  ]

  for (const member of tasksStore.members) {
    const count = tasksStore.items.filter(
      (task) => task.assigned_to_user_id === member.id,
    ).length
    const name = member.display_name.split(' ')[0]
    tabs.push({
      key: member.id,
      label: count > 0 ? `${name} (${count})` : name,
    })
  }

  return tabs
})

// ── Filtered Tasks ──
const filteredTasks = computed(() => {
  let tasks = tasksStore.items

  if (activeFilter.value === 'shared') {
    tasks = tasks.filter((t) => t.assigned_to_user_id === null || t.type === 'chore')
  } else if (activeFilter.value !== 'all') {
    tasks = tasks.filter((t) => t.assigned_to_user_id === activeFilter.value)
  }

  return tasks
})

// ── Time Groups ──
interface TimeGroup {
  key: string
  label: string
  tasks: UnifiedTask[]
  isOverdue: boolean
}

const timeGroups = computed<TimeGroup[]>(() => {
  const today = todayStr()
  const endOfWeek = endOfWeekStr()

  const overdue: UnifiedTask[] = []
  const todayTasks: UnifiedTask[] = []
  const thisWeek: UnifiedTask[] = []
  const later: UnifiedTask[] = []

  for (const task of filteredTasks.value) {
    const due = dateOnly(task.due_date)
    if (!due) {
      later.push(task)
    } else if (due < today) {
      overdue.push(task)
    } else if (due === today) {
      todayTasks.push(task)
    } else if (due <= endOfWeek) {
      thisWeek.push(task)
    } else {
      later.push(task)
    }
  }

  const groups: TimeGroup[] = []
  if (overdue.length > 0) {
    groups.push({ key: 'overdue', label: t('tasks.groupOverdue'), tasks: overdue, isOverdue: true })
  }
  if (todayTasks.length > 0) {
    groups.push({ key: 'today', label: t('tasks.groupToday'), tasks: todayTasks, isOverdue: false })
  }
  if (thisWeek.length > 0) {
    groups.push({ key: 'thisWeek', label: t('tasks.groupThisWeek'), tasks: thisWeek, isOverdue: false })
  }
  if (later.length > 0) {
    groups.push({ key: 'later', label: t('tasks.groupLater'), tasks: later, isOverdue: false })
  }
  return groups
})

const openCount = computed(() => tasksStore.items.length)

// ── Member Name Lookup ──
function memberName(userId: string): string {
  const member = tasksStore.members.find((m) => m.id === userId)
  return member?.display_name ?? t('common.unknown')
}

// ── Task Handlers ──
async function handleToggle(task: UnifiedTask) {
  try {
    if (task.type === 'todo') {
      await todosStore.toggleDone(task.id)
    } else {
      await tasksStore.completeChoreAssignment(task.id)
    }
    tasksStore.invalidate()
  } catch {
    showToast(t('todos.toggleError'), 'error')
  }
}

async function handleClaim(task: UnifiedTask) {
  try {
    await tasksStore.claimTask(task.id)
  } catch (error: any) {
    const status = error?.response?.status
    const code = error?.response?.data?.detail?.code
    if (status === 409 || code === 'TODO_ALREADY_CLAIMED') {
      showToast(t('tasks.claimConflict'), 'error')
      tasksStore.invalidate()
    } else {
      showToast(t('tasks.claimError'), 'error')
    }
  }
}

// ── Create Todo ──
function openCreateDialog() {
  createTitle.value = ''
  createDescription.value = ''
  createDueDate.value = ''
  createAssignee.value = ''
  createTags.value = ''
  showCreateDialog.value = true
}

async function handleCreate() {
  if (!createTitle.value.trim()) return

  createLoading.value = true
  try {
    const tags = createTags.value
      .split(',')
      .map((t) => t.trim())
      .filter((t) => t.length > 0)

    await todosStore.addTodo(
      createTitle.value.trim(),
      createDescription.value.trim() || undefined,
      createAssignee.value || undefined,
      createDueDate.value || undefined,
      tags.length > 0 ? tags : undefined,
    )
    tasksStore.invalidate()
    showCreateDialog.value = false
  } catch {
    showToast(t('todos.addError'), 'error')
  } finally {
    createLoading.value = false
  }
}

// ── Socket Events ──
const socketEvents = [
  'todo_created',
  'todo_updated',
  'todo_deleted',
  'chore_assignment_created',
  'chore_assignment_updated',
] as const

function handleSocketEvent() {
  tasksStore.invalidate()
}

function handleReconnect() {
  tasksStore.fetchTasks()
}

// ── Lifecycle ──
onMounted(() => {
  tasksStore.fetchTasks()
  tasksStore.fetchMembers()
  todosStore.fetchMembers()

  // Open create dialog if ?new=1
  if (route.query.new === '1') {
    openCreateDialog()
    router.replace({ query: {} })
  }

  // Register socket events
  for (const event of socketEvents) {
    socket.on(event, handleSocketEvent)
  }
  socket.onReconnect(handleReconnect)
})

onUnmounted(() => {
  for (const event of socketEvents) {
    socket.off(event, handleSocketEvent)
  }
  socket.offReconnect(handleReconnect)
})
</script>

<template>
  <div class="view-page">
    <PageHeader
      :title="$t('tasks.title')"
      :subtitle="openCount > 0 ? $t('tasks.openCount', { n: openCount }) : undefined"
    >
      <template #action>
        <button class="fab-btn" @click="openCreateDialog" :aria-label="$t('tasks.createTitle')">
          <PhPlus :size="20" weight="bold" />
        </button>
      </template>
    </PageHeader>

    <!-- Person Filter Pills -->
    <BasePillTabs
      :tabs="filterTabs"
      v-model="activeFilter"
    />

    <!-- Loading -->
    <template v-if="tasksStore.loading && tasksStore.items.length === 0">
      <div class="skeleton-list">
        <BaseSkeleton v-for="i in 4" :key="i" width="100%" height="56px" />
      </div>
    </template>

    <!-- Empty State -->
    <BaseEmptyState
      v-else-if="tasksStore.items.length === 0 && !tasksStore.loading"
      :icon="PhListChecks"
      :title="$t('tasks.emptyTitle')"
      :subtitle="$t('tasks.emptySubtitle')"
    >
      <template #action>
        <BaseButton @click="openCreateDialog">
          <PhPlus :size="16" /> {{ $t('tasks.createTitle') }}
        </BaseButton>
      </template>
    </BaseEmptyState>

    <!-- Filtered empty (filter active but no results) -->
    <BaseEmptyState
      v-else-if="filteredTasks.length === 0 && tasksStore.items.length > 0"
      :icon="PhListChecks"
      :title="$t('tasks.emptyTitle')"
    />

    <!-- Task Groups -->
    <template v-else>
      <section
        v-for="group in timeGroups"
        :key="group.key"
        class="task-group"
      >
        <h3
          class="task-group__header"
          :class="{ 'task-group__header--overdue': group.isOverdue }"
        >
          {{ group.label }}
        </h3>

        <div class="task-list">
          <div
            v-for="task in group.tasks"
            :key="task.id"
            class="task-row"
          >
            <!-- Left: Check Circle -->
            <BaseCheckCircle
              :checked="false"
              @toggle="handleToggle(task)"
            />

            <!-- Center: Content -->
            <div class="task-row__content">
              <span class="task-row__title">{{ task.title }}</span>

              <div class="task-row__meta" v-if="task.due_date || task.recurring">
                <span v-if="task.due_date" class="task-row__due">
                  {{ formatDateShort(task.due_date) }}
                </span>
                <span v-if="task.due_date && task.recurring" class="task-row__sep">·</span>
                <span v-if="task.recurring" class="task-row__recurring">
                  <PhRepeat :size="12" />
                  {{ $t('tasks.recurring') }}
                </span>
              </div>

              <div class="task-row__tags" v-if="task.tags.length > 0">
                <span
                  v-for="tag in task.tags"
                  :key="tag"
                  class="tag-chip"
                >
                  {{ tag }}
                </span>
              </div>
            </div>

            <!-- Right: Avatar or Claim -->
            <div class="task-row__actions">
              <BaseAvatar
                v-if="task.assigned_to_user_id"
                :name="memberName(task.assigned_to_user_id)"
                :user-id="task.assigned_to_user_id"
                size="sm"
              />
              <button
                v-else-if="task.type === 'todo'"
                class="claim-btn"
                @click="handleClaim(task)"
              >
                {{ $t('tasks.claim') }}
              </button>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- Create Dialog -->
    <BaseDialog
      :open="showCreateDialog"
      :title="$t('tasks.createTitle')"
      @close="showCreateDialog = false"
    >
      <form class="create-form" @submit.prevent="handleCreate">
        <BaseInput
          v-model="createTitle"
          :label="$t('todos.titlePlaceholder')"
          :placeholder="$t('todos.addPlaceholder')"
          autocomplete="off"
        />

        <BaseInput
          v-model="createDescription"
          :label="$t('tasks.descriptionLabel')"
          :placeholder="$t('todos.descriptionPlaceholder')"
        />

        <BaseInput
          v-model="createDueDate"
          :label="$t('tasks.dueDateLabel')"
          type="date"
        />

        <div class="create-form__field">
          <label class="create-form__label">{{ $t('tasks.assignLabel') }}</label>
          <select v-model="createAssignee" class="create-form__select">
            <option value="">{{ $t('tasks.free') }}</option>
            <option
              v-for="member in tasksStore.members"
              :key="member.id"
              :value="member.id"
            >
              {{ member.display_name }}
            </option>
          </select>
        </div>

        <BaseInput
          v-model="createTags"
          :label="$t('tasks.tagsLabel')"
          :placeholder="$t('tasks.tagsPlaceholder')"
        />
      </form>

      <template #footer>
        <BaseButton variant="secondary" @click="showCreateDialog = false">
          {{ $t('common.cancel') }}
        </BaseButton>
        <BaseButton
          :loading="createLoading"
          :disabled="!createTitle.trim()"
          @click="handleCreate"
        >
          {{ $t('tasks.createButton') }}
        </BaseButton>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.view-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* ── FAB Button ── */
.fab-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-full);
  background: var(--acc);
  color: var(--card);
  border: none;
  cursor: pointer;
  transition: filter var(--transition-fast);
}

.fab-btn:hover {
  filter: brightness(1.08);
}

/* ── Skeleton ── */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

/* ── Task Groups ── */
.task-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.task-group__header {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--sub);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin: 0;
  padding: var(--space-1) 0;
}

.task-group__header--overdue {
  color: var(--acc);
}

/* ── Task List ── */
.task-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

/* ── Task Row ── */
.task-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--card);
  border-radius: var(--radius-sm);
}

.task-row__content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.task-row__title {
  font-size: var(--text-base);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
  word-break: break-word;
}

.task-row__meta {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: var(--text-xs);
  color: var(--sub);
}

.task-row__recurring {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

.task-row__sep {
  color: var(--sub);
}

/* ── Tags ── */
.task-row__tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-top: 2px;
}

.tag-chip {
  display: inline-block;
  padding: 1px 8px;
  background: var(--chip);
  color: var(--ink);
  border-radius: var(--radius-full);
  font-size: var(--text-xs);
  line-height: 1.6;
}

/* ── Actions ── */
.task-row__actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
}

.claim-btn {
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--acc);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--acc);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-medium);
  font-family: var(--font-family);
  cursor: pointer;
  white-space: nowrap;
  transition: all 150ms;
}

.claim-btn:hover {
  background: var(--acc);
  color: var(--card);
}

/* ── Create Form ── */
.create-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.create-form__field {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.create-form__label {
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--ink);
}

.create-form__select {
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

.create-form__select:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}
</style>
