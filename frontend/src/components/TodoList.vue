<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useTodosStore } from '../stores/todos'
import { useToast } from '../composables/useToast'
import { useAsyncAction } from '../composables/useAsyncAction'
import { useI18n } from 'vue-i18n'
import { formatDateShort, householdDateString, todoDueDay } from '../utils/dates'
import { useAuthStore } from '../stores/auth'
import { nextPendingReminder } from '../utils/todoReminders'
import type { TodoItem } from '../types'
import { PhPencilSimple, PhX, PhListChecks, PhBell, PhPlus } from '@phosphor-icons/vue'
import BaseButton from './ui/BaseButton.vue'
import BaseAvatar from './ui/BaseAvatar.vue'
import BaseSkeleton from './ui/BaseSkeleton.vue'
import BaseEmptyState from './ui/BaseEmptyState.vue'
import BaseCheckCircle from './ui/BaseCheckCircle.vue'
import BaseErrorState from './ui/BaseErrorState.vue'

const todosStore = useTodosStore()
const authStore = useAuthStore()
const { notifyError, notifyInfo } = useToast()
const { run } = useAsyncAction()
const { t } = useI18n()

const props = withDefaults(defineProps<{
  autoFocus?: boolean
  filterUserId?: string
  /** Vorname der gefilterten Person (für Hinweise) */
  filterUserName?: string
  /** Laden ist gescheitert → Fehlerzustand statt „Keine offenen Aufgaben“ */
  loadError?: boolean
  retrying?: boolean
}>(), {
  autoFocus: false,
  filterUserId: undefined,
  filterUserName: undefined,
  loadError: false,
  retrying: false,
})

const emit = defineEmits<{ retry: [] }>()

// Quick-Add
const newTodoTitle = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

// Erweiterte Felder (Detail-Bereich)
const showAddDetails = ref(false)
const newDescription = ref('')
const newDueDate = ref('')
const newAssignedTo = ref('')
const newReminders = ref<string[]>([])

// Mit aktivem Personen-Filter die neue Aufgabe dieser Person vorbelegen —
// sonst verschwände sie nach dem Erfassen sofort aus der gefilterten Ansicht
watch(() => props.filterUserId, (id, oldId) => {
  if (!newAssignedTo.value || newAssignedTo.value === oldId) {
    newAssignedTo.value = id ?? ''
  }
}, { immediate: true })

// Bearbeitungs-Toggle pro Todo
const editingId = ref<string | null>(null)
const editTitle = ref('')
const editDescription = ref('')
const editDueDate = ref('')
const editAssignedTo = ref('')
const editNewReminders = ref<string[]>([])
const editTitleError = ref('')
const editSaving = ref(false)

// Eingeklappte Erledigt-Sektion
const showDone = ref(false)

onMounted(() => {
  if (props.autoFocus) {
    nextTick(() => inputRef.value?.focus())
  }
})

// Getrennte Listen: offen vs. erledigt (mit optionalem Member-Filter)
const openTodos = computed(() => {
  let list = todosStore.items.filter((t) => !t.is_done)
  if (props.filterUserId !== undefined) {
    list = list.filter((t) => t.assigned_to_user_id === props.filterUserId)
  }
  return list
})
const doneTodos = computed(() => {
  let list = todosStore.items.filter((t) => t.is_done)
  if (props.filterUserId !== undefined) {
    list = list.filter((t) => t.assigned_to_user_id === props.filterUserId)
  }
  return list
})

// Überfällig-Check: Fälligkeit ist ein Kalendertag (gespeichert 00:00 UTC) und wird
// mit „heute“ im Haushalt verglichen — nicht über new Date(), sonst wäre die Aufgabe
// westlich von UTC schon am Fälligkeitstag überfällig (CASA-39)
function isOverdue(todo: TodoItem): boolean {
  const due = todoDueDay(todo.due_date)
  if (!due || todo.is_done) return false
  return due < householdDateString(authStore.currentHousehold?.timezone)
}

// Mitglied-Name auflösen
function getMemberName(userId: string | null): string | null {
  if (!userId) return null
  const member = todosStore.members.find((m) => m.id === userId)
  return member?.display_name ?? null
}


// Reminder-Datum formatieren
function formatReminderDate(isoString: string): string {
  const d = new Date(isoString)
  return d.toLocaleString(undefined, {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

// Nächste ausstehende Erinnerung (zukünftig und noch nicht gesendet)
function getNextReminder(todo: TodoItem): string | null {
  return nextPendingReminder(todo.reminders)
}

// Reminder löschen
async function handleDeleteReminder(todoId: string, reminderId: string) {
  await run(() => todosStore.deleteReminder(todoId, reminderId), {
    key: `reminder:${reminderId}`,
    error: t('todos.deleteReminderError'),
  })
}

// Erinnerungen an eine Aufgabe hängen; Fehler einmal melden
async function addReminders(todoId: string, reminders: string[]) {
  for (const remindAt of reminders) {
    try {
      await todosStore.addReminder(todoId, new Date(remindAt).toISOString())
    } catch (err) {
      notifyError(t('todos.reminderError'), err)
    }
  }
}

// Quick-Add Handler
async function handleAddTodo() {
  const title = newTodoTitle.value.trim()
  if (!title) return

  const description = newDescription.value.trim() || undefined
  const dueDate = newDueDate.value || undefined
  const assignedTo = newAssignedTo.value || undefined
  const remindersToAdd = newReminders.value.filter(r => r.trim() !== '')

  // Eingaben für die Wiederherstellung bei Fehler merken
  const saved = {
    title: newTodoTitle.value,
    description: newDescription.value,
    dueDate: newDueDate.value,
    assignedTo: newAssignedTo.value,
    reminders: [...newReminders.value],
    showDetails: showAddDetails.value,
  }

  // Offline blockiert run() vor dem Zurücksetzen → nichts geht verloren
  await run(async () => {
    // Felder sofort leeren (schnelles Erfassen) …
    newTodoTitle.value = ''
    newDescription.value = ''
    newDueDate.value = ''
    newAssignedTo.value = props.filterUserId ?? ''
    newReminders.value = []
    showAddDetails.value = false

    let todoId: string | undefined
    try {
      todoId = await todosStore.addTodo(title, description, assignedTo, dueDate)
    } catch (err) {
      // … und bei Fehler wiederherstellen, falls inzwischen nichts Neues getippt wurde
      if (!newTodoTitle.value) {
        newTodoTitle.value = saved.title
        newDescription.value = saved.description
        newDueDate.value = saved.dueDate
        newAssignedTo.value = saved.assignedTo
        newReminders.value = saved.reminders
        showAddDetails.value = saved.showDetails
      }
      throw err
    }

    // Erinnerungen an die neue Aufgabe hängen (ID aus addTodo, nicht „letzter Eintrag“)
    if (todoId && remindersToAdd.length > 0) {
      await addReminders(todoId, remindersToAdd)
    }

    // Bewusst jemand anderem (oder niemandem) zugewiesen → durch den Filter ausgeblendet
    if (props.filterUserId !== undefined && assignedTo !== props.filterUserId) {
      notifyInfo(t('todos.createdHidden', { name: props.filterUserName ?? '' }))
    }
  }, { key: `add:${title}`, error: t('todos.addError') })
  inputRef.value?.focus()
}

async function handleToggle(todo: TodoItem) {
  const todoId = todo.id
  if (todo.is_done) {
    // Wieder öffnen: in der Liste sichtbar, kein Toast
    await run(() => todosStore.setDone(todoId, false), {
      key: `toggle:${todoId}`,
      error: t('todos.toggleError'),
    })
    return
  }
  // Erledigen: Eintrag wandert in den eingeklappten Bereich → Toast mit Rückgängig
  await run(() => todosStore.setDone(todoId, true), {
    key: `toggle:${todoId}`,
    success: t('todos.done'),
    undo: () => todosStore.setDone(todoId, false),
    error: t('todos.toggleError'),
  })
}

async function handleDelete(todoId: string) {
  const todo = todosStore.items.find(t => t.id === todoId)
  if (!todo) return
  // Vollständiger Snapshot (Tags, Erinnerungen, Status) fürs Undo
  const snapshot: TodoItem = { ...todo, tags: [...todo.tags], reminders: [...todo.reminders] }

  await run(() => todosStore.deleteTodo(todoId), {
    key: `delete:${todoId}`,
    success: t('common.deleted'),
    undo: () => todosStore.restoreTodo(snapshot),
    error: t('todos.deleteError'),
  })
}

// Bearbeitung starten
function startEdit(todo: TodoItem) {
  editingId.value = todo.id
  editTitle.value = todo.title
  editDescription.value = todo.description ?? ''
  editDueDate.value = todoDueDay(todo.due_date) ?? ''
  editAssignedTo.value = todo.assigned_to_user_id ?? ''
  editNewReminders.value = []
  editTitleError.value = ''
  // Fokus aufs Titelfeld
  nextTick(() => editTitleRef.value?.focus())
}

const editTitleRef = ref<HTMLInputElement | null>(null)

function setEditTitleRef(el: unknown) {
  editTitleRef.value = (el as HTMLInputElement | null) ?? null
}

function cancelEdit() {
  editingId.value = null
  editTitleError.value = ''
}

async function saveEdit(todoId: string) {
  const title = editTitle.value.trim()
  if (!title) {
    editTitleError.value = t('todos.titleRequired')
    editTitleRef.value?.focus()
    return
  }
  if (editSaving.value) return
  editTitleError.value = ''

  editSaving.value = true
  try {
    const ok = await run(() => todosStore.updateTodo(todoId, {
      title,
      description: editDescription.value.trim() || null,
      due_date: editDueDate.value || null,
      assigned_to_user_id: editAssignedTo.value || null,
    }), { key: `save:${todoId}`, error: t('todos.saveError') })
    if (!ok) return

    // Neue Reminders hinzufügen
    await addReminders(todoId, editNewReminders.value.filter(r => r.trim() !== ''))

    editingId.value = null
  } finally {
    editSaving.value = false
  }
}
</script>

<template>
  <div class="todo-list">
    <!-- Quick-Add -->
    <form @submit.prevent="handleAddTodo" class="quick-add">
      <input
        ref="inputRef"
        v-model="newTodoTitle"
        type="text"
        :placeholder="$t('todos.addPlaceholder')"
        class="quick-add__input"
        :aria-label="$t('todos.addPlaceholder')"
      />
      <button
        type="submit"
        class="quick-add__btn tap-target"
        :disabled="!newTodoTitle.trim()"
        :aria-label="$t('common.add')"
      >
        <PhPlus :size="20" weight="bold" />
      </button>
    </form>

    <!-- Details Toggle -->
    <button
      type="button"
      class="details-toggle tap-target"
      :aria-expanded="showAddDetails"
      @click="showAddDetails = !showAddDetails"
    >
      <span aria-hidden="true">{{ showAddDetails ? '▾' : '▸' }}</span>
      {{ showAddDetails ? $t('todos.detailsHide') : $t('todos.detailsShow') }}
    </button>

    <!-- Erweiterte Felder -->
    <div v-if="showAddDetails" class="add-details">
      <textarea
        v-model="newDescription"
        :placeholder="$t('todos.descriptionPlaceholder')"
        class="add-details__textarea"
        :aria-label="$t('todos.descriptionPlaceholder')"
        rows="2"
      />
      <input
        v-model="newDueDate"
        type="date"
        class="add-details__input"
        :title="$t('todos.dueDate')"
        :aria-label="$t('todos.dueDate')"
      />
      <select
        v-model="newAssignedTo"
        class="add-details__input"
        :title="$t('todos.assignTo')"
        :aria-label="$t('todos.assignTo')"
      >
        <option value="">{{ $t('todos.noneAssigned') }}</option>
        <option v-for="member in todosStore.members" :key="member.id" :value="member.id">
          {{ member.display_name }}
        </option>
      </select>
      <!-- Erinnerungen -->
      <div class="reminder-section">
        <label class="reminder-section__label">{{ $t('todos.reminders') }}</label>
        <div v-for="(rem, idx) in newReminders" :key="idx" class="reminder-row">
          <input
            v-model="newReminders[idx]"
            type="datetime-local"
            class="add-details__input reminder-row__input"
          />
          <button
            type="button"
            class="action-btn action-btn--danger tap-target"
            :aria-label="$t('todos.removeReminder')"
            :title="$t('todos.removeReminder')"
            @click="newReminders.splice(idx, 1)"
          >
            <PhX :size="16" />
          </button>
        </div>
        <button
          v-if="newReminders.length < 5"
          type="button"
          class="reminder-add-btn tap-target"
          @click="newReminders.push('')"
        >
          + {{ $t('todos.addReminder') }}
        </button>
        <span v-else class="reminder-max-hint">{{ $t('todos.maxReminders') }}</span>
      </div>
    </div>

    <!-- Skeleton Loading -->
    <div v-if="todosStore.loading && todosStore.items.length === 0" class="skeleton-list">
      <div class="skeleton-row" v-for="n in 3" :key="n">
        <BaseSkeleton width="20px" height="20px" rounded />
        <div style="flex: 1; display: flex; flex-direction: column; gap: var(--space-1);">
          <BaseSkeleton :width="['75%', '60%', '85%'][n - 1]" height="16px" />
          <BaseSkeleton width="40%" height="12px" />
        </div>
      </div>
    </div>

    <!-- Fehlerzustand: Laden gescheitert -->
    <BaseErrorState
      v-if="loadError && !todosStore.loading && todosStore.items.length === 0"
      :retrying="retrying"
      @retry="emit('retry')"
    />

    <!-- Offene Todos -->
    <ul v-if="openTodos.length > 0" class="item-list">
      <li
        v-for="todo in openTodos"
        :key="todo.id"
        class="todo-row"
        :class="{ 'todo-row--overdue': isOverdue(todo) }"
      >
        <!-- Anzeige-Modus -->
        <template v-if="editingId !== todo.id">
          <div class="todo-row__main" @click="handleToggle(todo)">
            <BaseCheckCircle :checked="todo.is_done" :label="todo.title" @toggle="handleToggle(todo)" />
            <div class="todo-row__content">
              <div class="todo-row__title-line">
                <span class="todo-row__name">{{ todo.title }}</span>
                <span v-if="isOverdue(todo)" class="overdue-badge">{{ $t('todos.overdue') }}</span>
              </div>
              <div v-if="todo.description || todo.due_date || todo.assigned_to_user_id" class="todo-row__meta">
                <span v-if="todo.description" class="todo-row__desc">{{ todo.description }}</span>
                <span v-if="todo.due_date" class="todo-row__date" :class="{ 'todo-row__date--overdue': isOverdue(todo) }">
                  {{ formatDateShort(todoDueDay(todo.due_date)!) }}
                </span>
                <BaseAvatar
                  v-if="todo.assigned_to_user_id && getMemberName(todo.assigned_to_user_id)"
                  :name="getMemberName(todo.assigned_to_user_id)!"
                  :user-id="todo.assigned_to_user_id"
                  size="sm"
                />
                <!-- Nächste Erinnerung Badge -->
                <span v-if="getNextReminder(todo)" class="reminder-badge">
                  <PhBell :size="12" weight="fill" />
                  {{ formatReminderDate(getNextReminder(todo)!) }}
                </span>
              </div>
            </div>
          </div>
          <div class="todo-row__actions">
            <button class="action-btn tap-target" @click="startEdit(todo)" :title="$t('common.edit')" :aria-label="$t('common.edit')"><PhPencilSimple :size="16" /></button>
            <button class="action-btn action-btn--danger tap-target" @click="handleDelete(todo.id)" :title="$t('common.delete')" :aria-label="$t('common.delete')"><PhX :size="16" /></button>
          </div>
        </template>

        <!-- Bearbeitungs-Modus -->
        <template v-else>
          <form class="edit-form" @submit.prevent="saveEdit(todo.id)" @keydown.esc.stop="cancelEdit">
            <input
              :ref="setEditTitleRef"
              v-model="editTitle"
              type="text"
              class="add-details__input"
              :class="{ 'add-details__input--error': editTitleError }"
              :placeholder="$t('todos.titlePlaceholder')"
              :aria-label="$t('todos.titlePlaceholder')"
              :aria-invalid="!!editTitleError"
              @input="editTitleError = ''"
            />
            <p v-if="editTitleError" class="field-error" role="alert">{{ editTitleError }}</p>
            <textarea v-model="editDescription" class="add-details__textarea" :placeholder="$t('todos.descriptionPlaceholder')" rows="2" />
            <input v-model="editDueDate" type="date" class="add-details__input" :title="$t('todos.dueDate')" />
            <select v-model="editAssignedTo" class="add-details__input" :title="$t('todos.assignTo')">
              <option value="">{{ $t('todos.noneAssigned') }}</option>
              <option v-for="member in todosStore.members" :key="member.id" :value="member.id">
                {{ member.display_name }}
              </option>
            </select>
            <!-- Bestehende Reminders anzeigen/löschen -->
            <div class="reminder-section">
              <label class="reminder-section__label">{{ $t('todos.reminders') }}</label>
              <div v-for="rem in todo.reminders" :key="rem.id" class="reminder-row">
                <span class="reminder-row__text">{{ formatReminderDate(rem.remind_at) }}</span>
                <button
                  type="button"
                  class="action-btn action-btn--danger tap-target"
                  :aria-label="$t('todos.removeReminder')"
                  :title="$t('todos.removeReminder')"
                  @click="handleDeleteReminder(todo.id, rem.id)"
                >
                  <PhX :size="16" />
                </button>
              </div>
              <!-- Neue Reminders hinzufügen -->
              <div v-for="(rem, idx) in editNewReminders" :key="'new-' + idx" class="reminder-row">
                <input
                  v-model="editNewReminders[idx]"
                  type="datetime-local"
                  class="add-details__input reminder-row__input"
                />
                <button
                  type="button"
                  class="action-btn action-btn--danger tap-target"
                  :aria-label="$t('todos.removeReminder')"
                  :title="$t('todos.removeReminder')"
                  @click="editNewReminders.splice(idx, 1)"
                >
                  <PhX :size="16" />
                </button>
              </div>
              <button
                v-if="(todo.reminders.length + editNewReminders.length) < 5"
                type="button"
                class="reminder-add-btn tap-target"
                @click="editNewReminders.push('')"
              >
                + {{ $t('todos.addReminder') }}
              </button>
              <span v-else class="reminder-max-hint">{{ $t('todos.maxReminders') }}</span>
            </div>
            <div class="edit-form__actions">
              <BaseButton type="submit" variant="primary" size="sm" :loading="editSaving">{{ $t('common.save') }}</BaseButton>
              <BaseButton type="button" variant="secondary" size="sm" @click="cancelEdit">{{ $t('common.cancel') }}</BaseButton>
            </div>
          </form>
        </template>
      </li>
    </ul>

    <!-- Empty State -->
    <BaseEmptyState
      v-if="!todosStore.loading && openTodos.length === 0 && !(loadError && todosStore.items.length === 0)"
      :icon="PhListChecks"
      :title="$t('todos.emptyOpenTitle')"
      :subtitle="$t('todos.emptySubtitle')"
    />

    <!-- Erledigte Todos (eingeklappt) -->
    <div v-if="doneTodos.length > 0" class="done-section">
      <button
        type="button"
        class="done-section__toggle"
        :aria-expanded="showDone"
        @click="showDone = !showDone"
      >
        {{ $t('todos.doneToggle', { count: doneTodos.length }) }}
        <span aria-hidden="true">{{ showDone ? '▾' : '▸' }}</span>
      </button>
      <ul v-if="showDone" class="item-list">
        <li v-for="todo in doneTodos" :key="todo.id" class="todo-row todo-row--done">
          <div class="todo-row__main" @click="handleToggle(todo)">
            <BaseCheckCircle :checked="todo.is_done" :label="todo.title" @toggle="handleToggle(todo)" />
            <div class="todo-row__content">
              <span class="todo-row__name">{{ todo.title }}</span>
              <div v-if="todo.description || todo.due_date || todo.assigned_to_user_id" class="todo-row__meta">
                <span v-if="todo.description" class="todo-row__desc">{{ todo.description }}</span>
                <span v-if="todo.due_date" class="todo-row__date">{{ formatDateShort(todoDueDay(todo.due_date)!) }}</span>
                <BaseAvatar
                  v-if="todo.assigned_to_user_id && getMemberName(todo.assigned_to_user_id)"
                  :name="getMemberName(todo.assigned_to_user_id)!"
                  :user-id="todo.assigned_to_user_id"
                  size="sm"
                />
                <!-- Nächste Erinnerung Badge -->
                <span v-if="getNextReminder(todo)" class="reminder-badge">
                  <PhBell :size="12" weight="fill" />
                  {{ formatReminderDate(getNextReminder(todo)!) }}
                </span>
              </div>
            </div>
          </div>
          <button class="action-btn action-btn--danger tap-target" @click="handleDelete(todo.id)" :title="$t('common.delete')" :aria-label="$t('common.delete')"><PhX :size="16" /></button>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.todo-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

/* Quick-Add: sticky */
.quick-add {
  display: flex;
  gap: var(--space-2);
  align-items: center;
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
  background: var(--bg);
  padding-bottom: var(--space-2);
}

@media (min-width: 768px) {
  .quick-add {
    position: static;
  }
}

.quick-add__input {
  flex: 1;
  min-width: 0;
  padding: var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
  font-size: var(--text-base);
  font-family: var(--font-family);
  background: var(--card);
  color: var(--ink);
  transition: border-color var(--transition-fast);
}

.quick-add__input::placeholder {
  color: var(--sub);
}

.quick-add__input:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}

.quick-add__btn {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-full);
  border: none;
  background: var(--acc);
  color: var(--color-on-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: opacity var(--transition-fast), transform var(--transition-fast);
}
.quick-add__btn:active {
  transform: scale(0.92);
}
.quick-add__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* Details-Toggle */
.details-toggle {
  background: none;
  border: none;
  color: var(--sub);
  font-size: var(--text-sm);
  cursor: pointer;
  padding: var(--space-1) 0;
  text-align: left;
}

.details-toggle:hover {
  color: var(--ink);
}

/* Erweiterte Felder */
.add-details {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.add-details__textarea {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
  font-size: var(--text-base); /* 16px — iOS-Zoom-Prevention */
  font-family: var(--font-family);
  background: var(--card);
  color: var(--ink);
  resize: vertical;
}

.add-details__input {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-btn);
  font-size: var(--text-base); /* 16px — iOS-Zoom-Prevention */
  font-family: var(--font-family);
  background: var(--card);
  color: var(--ink);
}

.add-details__input--error {
  border-color: var(--color-danger);
}

.field-error {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--color-danger);
}

.add-details__textarea:focus,
.add-details__input:focus {
  outline: none;
  border-color: var(--acc);
  box-shadow: 0 0 0 3px var(--acc-soft);
}

/* Skeleton Loading */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-2);
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

/* Item-Liste */
.item-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
}

/* Todo-Zeile */
.todo-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-2);
  border-bottom: 1px solid var(--line);
}

.todo-row--overdue {
  background: var(--color-danger-soft);
}

.todo-row__main {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  flex: 1;
  cursor: pointer;
  min-height: 44px;
  -webkit-user-select: none;
  user-select: none;
}

.todo-row__content {
  display: flex;
  flex-direction: column;
  gap: var(--space-0-5);
  flex: 1;
  min-width: 0;
}

.todo-row__title-line {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0 var(--space-2);
}

.todo-row__name {
  min-width: 0;
  font-size: var(--text-base);
  color: var(--ink);
  overflow-wrap: anywhere;
}

.overdue-badge {
  font-size: var(--text-xs);
  color: var(--color-danger);
  font-weight: var(--font-weight-semibold);
  white-space: nowrap;
}

.todo-row__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--sub);
  margin-top: var(--space-0-5);
}

.todo-row__desc {
  color: var(--sub);
}

.todo-row__date {
  white-space: nowrap;
}

.todo-row__date--overdue {
  color: var(--color-danger);
  font-weight: var(--font-weight-medium);
}

/* Aktions-Buttons */
.todo-row__actions {
  display: flex;
  /* Abstand, damit sich die 44-px-Tap-Flächen (.tap-target) nicht überlappen */
  gap: var(--space-3);
  flex-shrink: 0;
}

.action-btn {
  background: none;
  border: none;
  color: var(--sub);
  cursor: pointer;
  font-size: var(--text-sm);
  padding: var(--space-1);
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast), color var(--transition-fast);
  min-width: 32px;
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-btn:hover {
  background: var(--chip);
  color: var(--acc);
}

.action-btn--danger:hover {
  background: var(--color-danger-light);
  color: var(--color-danger);
}

/* Bearbeitungs-Form */
.edit-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  flex: 1;
  padding: var(--space-2) 0;
}

.edit-form__actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-1);
}

/* Erledigte Todos: durchgestrichen + sub-Farbe (NICHT opacity) */
.todo-row--done .todo-row__name {
  text-decoration: line-through;
  color: var(--sub);
}

/* Erledigt-Sektion */
.done-section {
  margin-top: var(--space-2);
}

.done-section__toggle {
  background: none;
  border: none;
  color: var(--sub);
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  cursor: pointer;
  padding: var(--space-2) 0;
}

.done-section__toggle:hover {
  color: var(--ink);
}

/* Reminder Section */
.reminder-section {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.reminder-section__label {
  font-size: var(--text-sm);
  color: var(--sub);
  font-weight: var(--font-weight-medium);
}

.reminder-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.reminder-row__input {
  flex: 1;
}

.reminder-row__text {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--ink);
}

.reminder-add-btn {
  background: none;
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius-btn);
  padding: var(--space-2) var(--space-3);
  color: var(--acc);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.reminder-add-btn:hover {
  background: var(--acc-soft);
  border-color: var(--acc);
}

.reminder-max-hint {
  font-size: var(--text-xs);
  color: var(--sub);
  font-style: italic;
}

/* Bell Badge in Todo Row */
.reminder-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: var(--text-xs);
  color: var(--acc);
  white-space: nowrap;
}
</style>
