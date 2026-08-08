<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useTodosStore } from '../stores/todos'
import { useToast } from '../composables/useToast'
import { useI18n } from 'vue-i18n'
import { formatDateShort } from '../utils/dates'
import type { TodoItem } from '../types'
import { PhPencilSimple, PhX, PhListChecks } from '@phosphor-icons/vue'
import BaseButton from './ui/BaseButton.vue'
import BaseAvatar from './ui/BaseAvatar.vue'
import BaseSkeleton from './ui/BaseSkeleton.vue'
import BaseEmptyState from './ui/BaseEmptyState.vue'
import BaseCheckCircle from './ui/BaseCheckCircle.vue'

const todosStore = useTodosStore()
const { showToast } = useToast()
const { t } = useI18n()

const props = withDefaults(defineProps<{
  autoFocus?: boolean
}>(), {
  autoFocus: false,
})

// Quick-Add
const newTodoTitle = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

// Erweiterte Felder (Detail-Bereich)
const showAddDetails = ref(false)
const newDescription = ref('')
const newDueDate = ref('')
const newAssignedTo = ref('')

// Bearbeitungs-Toggle pro Todo
const editingId = ref<string | null>(null)
const editTitle = ref('')
const editDescription = ref('')
const editDueDate = ref('')
const editAssignedTo = ref('')

// Eingeklappte Erledigt-Sektion
const showDone = ref(false)

onMounted(() => {
  if (props.autoFocus) {
    nextTick(() => inputRef.value?.focus())
  }
})

// Getrennte Listen: offen vs. erledigt
const openTodos = computed(() =>
  todosStore.items.filter((t) => !t.is_done),
)
const doneTodos = computed(() =>
  todosStore.items.filter((t) => t.is_done),
)

// Überfällig-Check
function isOverdue(todo: TodoItem): boolean {
  if (!todo.due_date || todo.is_done) return false
  return new Date(todo.due_date) < new Date(new Date().toDateString())
}

// Mitglied-Name auflösen
function getMemberName(userId: string | null): string | null {
  if (!userId) return null
  const member = todosStore.members.find((m) => m.id === userId)
  return member?.display_name ?? null
}


// Quick-Add Handler
async function handleAddTodo() {
  const title = newTodoTitle.value.trim()
  if (!title) return

  newTodoTitle.value = ''
  const description = newDescription.value.trim() || undefined
  const dueDate = newDueDate.value || undefined
  const assignedTo = newAssignedTo.value || undefined

  // Details zurücksetzen
  newDescription.value = ''
  newDueDate.value = ''
  newAssignedTo.value = ''
  showAddDetails.value = false

  try {
    await todosStore.addTodo(title, description, assignedTo, dueDate)
  } catch {
    showToast(t('todos.addError'))
  }
  // Fokus bleibt im Feld — UX-Prinzip "Quick-Add in unter 3 Sekunden"
  inputRef.value?.focus()
}

async function handleToggle(todoId: string) {
  try {
    await todosStore.toggleDone(todoId)
  } catch {
    showToast(t('todos.toggleError'))
  }
}

async function handleDelete(todoId: string) {
  const todo = todosStore.items.find(t => t.id === todoId)
  if (!todo) return

  try {
    await todosStore.deleteTodo(todoId)
    showToast(t('common.deleted'), 'success', undefined, {
      label: t('common.undo'),
      onAction: () => {
        todosStore.addTodo(
          todo.title,
          todo.description ?? undefined,
          todo.assigned_to_user_id ?? undefined,
          todo.due_date ?? undefined,
        ).catch(() => {
          showToast(t('todos.addError'), 'error')
        })
      },
    })
  } catch {
    showToast(t('todos.deleteError'))
  }
}

// Bearbeitung starten
function startEdit(todo: TodoItem) {
  editingId.value = todo.id
  editTitle.value = todo.title
  editDescription.value = todo.description ?? ''
  editDueDate.value = todo.due_date ?? ''
  editAssignedTo.value = todo.assigned_to_user_id ?? ''
}

function cancelEdit() {
  editingId.value = null
}

async function saveEdit(todoId: string) {
  const title = editTitle.value.trim()
  if (!title) return

  try {
    await todosStore.updateTodo(todoId, {
      title,
      description: editDescription.value.trim() || null,
      due_date: editDueDate.value || null,
      assigned_to_user_id: editAssignedTo.value || null,
    })
    editingId.value = null
  } catch {
    showToast(t('todos.saveError'))
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
        autofocus
      />
    </form>

    <!-- Details Toggle -->
    <button type="button" class="details-toggle" @click="showAddDetails = !showAddDetails">
      {{ showAddDetails ? '▾ ' + $t('todos.detailsHide') : '▸ ' + $t('todos.detailsShow') }}
    </button>

    <!-- Erweiterte Felder -->
    <div v-if="showAddDetails" class="add-details">
      <textarea
        v-model="newDescription"
        :placeholder="$t('todos.descriptionPlaceholder')"
        class="add-details__textarea"
        rows="2"
      />
      <input
        v-model="newDueDate"
        type="date"
        class="add-details__input"
        :title="$t('todos.dueDate')"
      />
      <select v-model="newAssignedTo" class="add-details__input" :title="$t('todos.assignTo')">
        <option value="">{{ $t('todos.noneAssigned') }}</option>
        <option v-for="member in todosStore.members" :key="member.id" :value="member.id">
          {{ member.display_name }}
        </option>
      </select>
    </div>

    <!-- Skeleton Loading -->
    <div v-if="todosStore.loading && todosStore.items.length === 0" class="skeleton-list">
      <div class="skeleton-row" v-for="n in 3" :key="n">
        <BaseSkeleton width="20px" height="20px" rounded />
        <div style="flex: 1; display: flex; flex-direction: column; gap: 4px;">
          <BaseSkeleton :width="['75%', '60%', '85%'][n - 1]" height="16px" />
          <BaseSkeleton width="40%" height="12px" />
        </div>
      </div>
    </div>

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
          <div class="todo-row__main" @click="handleToggle(todo.id)">
            <BaseCheckCircle :checked="todo.is_done" @toggle="handleToggle(todo.id)" />
            <div class="todo-row__content">
              <div class="todo-row__title-line">
                <span class="todo-row__name">{{ todo.title }}</span>
                <span v-if="isOverdue(todo)" class="overdue-badge">{{ $t('todos.overdue') }}</span>
              </div>
              <div v-if="todo.description || todo.due_date || todo.assigned_to_user_id" class="todo-row__meta">
                <span v-if="todo.description" class="todo-row__desc">{{ todo.description }}</span>
                <span v-if="todo.due_date" class="todo-row__date" :class="{ 'todo-row__date--overdue': isOverdue(todo) }">
                  {{ formatDateShort(todo.due_date) }}
                </span>
                <BaseAvatar
                  v-if="todo.assigned_to_user_id && getMemberName(todo.assigned_to_user_id)"
                  :name="getMemberName(todo.assigned_to_user_id)!"
                  :user-id="todo.assigned_to_user_id"
                  size="sm"
                />
              </div>
            </div>
          </div>
          <div class="todo-row__actions">
            <button class="action-btn" @click="startEdit(todo)" :title="$t('common.edit')" :aria-label="$t('common.edit')"><PhPencilSimple :size="16" /></button>
            <button class="action-btn action-btn--danger" @click="handleDelete(todo.id)" :title="$t('common.delete')" :aria-label="$t('common.delete')"><PhX :size="16" /></button>
          </div>
        </template>

        <!-- Bearbeitungs-Modus -->
        <template v-else>
          <form class="edit-form" @submit.prevent="saveEdit(todo.id)">
            <input v-model="editTitle" type="text" class="add-details__input" :placeholder="$t('todos.titlePlaceholder')" />
            <textarea v-model="editDescription" class="add-details__textarea" :placeholder="$t('todos.descriptionPlaceholder')" rows="2" />
            <input v-model="editDueDate" type="date" class="add-details__input" :title="$t('todos.dueDate')" />
            <select v-model="editAssignedTo" class="add-details__input" :title="$t('todos.assignTo')">
              <option value="">{{ $t('todos.noneAssigned') }}</option>
              <option v-for="member in todosStore.members" :key="member.id" :value="member.id">
                {{ member.display_name }}
              </option>
            </select>
            <div class="edit-form__actions">
              <BaseButton type="submit" variant="primary" size="sm">{{ $t('common.save') }}</BaseButton>
              <BaseButton type="button" variant="secondary" size="sm" @click="cancelEdit">{{ $t('common.cancel') }}</BaseButton>
            </div>
          </form>
        </template>
      </li>
    </ul>

    <!-- Empty State -->
    <BaseEmptyState
      v-if="!todosStore.loading && openTodos.length === 0"
      :icon="PhListChecks"
      :title="$t('todos.emptyOpenTitle')"
      :subtitle="$t('todos.emptySubtitle')"
    />

    <!-- Erledigte Todos (eingeklappt) -->
    <div v-if="doneTodos.length > 0" class="done-section">
      <button type="button" class="done-section__toggle" @click="showDone = !showDone">
        {{ $t('todos.doneToggle', { count: doneTodos.length }) }} {{ showDone ? '▾' : '▸' }}
      </button>
      <ul v-if="showDone" class="item-list">
        <li v-for="todo in doneTodos" :key="todo.id" class="todo-row todo-row--done">
          <div class="todo-row__main" @click="handleToggle(todo.id)">
            <BaseCheckCircle :checked="todo.is_done" @toggle="handleToggle(todo.id)" />
            <div class="todo-row__content">
              <span class="todo-row__name">{{ todo.title }}</span>
              <div v-if="todo.description || todo.due_date || todo.assigned_to_user_id" class="todo-row__meta">
                <span v-if="todo.description" class="todo-row__desc">{{ todo.description }}</span>
                <span v-if="todo.due_date" class="todo-row__date">{{ formatDateShort(todo.due_date) }}</span>
                <BaseAvatar
                  v-if="todo.assigned_to_user_id && getMemberName(todo.assigned_to_user_id)"
                  :name="getMemberName(todo.assigned_to_user_id)!"
                  :user-id="todo.assigned_to_user_id"
                  size="sm"
                />
              </div>
            </div>
          </div>
          <button class="action-btn action-btn--danger" @click="handleDelete(todo.id)" :title="$t('common.delete')" :aria-label="$t('common.delete')"><PhX :size="16" /></button>
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
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg);
  padding-bottom: var(--space-2);
}

@media (min-width: 768px) {
  .quick-add {
    position: static;
  }
}

.quick-add__input {
  width: 100%;
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
  font-size: var(--text-sm);
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
  font-size: var(--text-sm);
  font-family: var(--font-family);
  background: var(--card);
  color: var(--ink);
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
  background: #FFF5F5;
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
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.todo-row__title-line {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.todo-row__name {
  font-size: var(--text-base);
  color: var(--ink);
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
  margin-top: 2px;
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
  gap: var(--space-1);
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
</style>
