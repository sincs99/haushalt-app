<script setup lang="ts">
import { ref, computed } from 'vue'
import { useTodosStore } from '../stores/todos'
import { useToast } from '../composables/useToast'
import type { TodoItem } from '../types'
import BaseButton from './ui/BaseButton.vue'
import BaseSpinner from './ui/BaseSpinner.vue'
import BaseEmptyState from './ui/BaseEmptyState.vue'

const todosStore = useTodosStore()
const { showToast } = useToast()

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

// Datum formatieren
function formatDate(dateStr: string | null): string | null {
  if (!dateStr) return null
  const d = new Date(dateStr)
  const days = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa']
  return `${days[d.getDay()]} ${d.getDate().toString().padStart(2, '0')}.${(d.getMonth() + 1).toString().padStart(2, '0')}.`
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
    showToast('Aufgabe konnte nicht hinzugefügt werden. Bitte erneut versuchen.')
  }
  // Fokus bleibt im Feld — UX-Prinzip "Quick-Add in unter 3 Sekunden"
  inputRef.value?.focus()
}

async function handleToggle(todoId: string) {
  try {
    await todosStore.toggleDone(todoId)
  } catch {
    showToast('Änderung konnte nicht gespeichert werden.')
  }
}

async function handleDelete(todoId: string) {
  try {
    await todosStore.deleteTodo(todoId)
  } catch {
    showToast('Todo konnte nicht gelöscht werden.')
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
    showToast('Änderung konnte nicht gespeichert werden.')
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
        placeholder="Neue Aufgabe..."
        class="quick-add__input"
        autofocus
      />
    </form>

    <!-- Details Toggle -->
    <button type="button" class="details-toggle" @click="showAddDetails = !showAddDetails">
      {{ showAddDetails ? '▾ Details ausblenden' : '▸ Details hinzufügen' }}
    </button>

    <!-- Erweiterte Felder -->
    <div v-if="showAddDetails" class="add-details">
      <textarea
        v-model="newDescription"
        placeholder="Beschreibung (optional)"
        class="add-details__textarea"
        rows="2"
      />
      <input
        v-model="newDueDate"
        type="date"
        class="add-details__input"
        title="Fälligkeitsdatum"
      />
      <select v-model="newAssignedTo" class="add-details__input" title="Zuweisen an">
        <option value="">– Niemand zugewiesen –</option>
        <option v-for="member in todosStore.members" :key="member.id" :value="member.id">
          {{ member.display_name }}
        </option>
      </select>
    </div>

    <!-- Loading -->
    <div v-if="todosStore.loading" class="loading-center">
      <BaseSpinner />
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
            <span class="todo-row__check">
              <input
                type="checkbox"
                :checked="todo.is_done"
                @click.stop
                @change="handleToggle(todo.id)"
                class="todo-row__checkbox"
              />
            </span>
            <div class="todo-row__content">
              <div class="todo-row__title-line">
                <span class="todo-row__name">{{ todo.title }}</span>
                <span v-if="isOverdue(todo)" class="overdue-badge">Überfällig</span>
              </div>
              <div v-if="todo.description || todo.due_date || todo.assigned_to_user_id" class="todo-row__meta">
                <span v-if="todo.description" class="todo-row__desc">{{ todo.description }}</span>
                <span v-if="todo.due_date" class="todo-row__date" :class="{ 'todo-row__date--overdue': isOverdue(todo) }">
                  📅 {{ formatDate(todo.due_date) }}
                </span>
                <span v-if="getMemberName(todo.assigned_to_user_id)" class="initials-chip">
                  {{ getMemberName(todo.assigned_to_user_id)!.charAt(0).toUpperCase() }}
                </span>
              </div>
            </div>
          </div>
          <div class="todo-row__actions">
            <button class="action-btn" @click="startEdit(todo)" title="Bearbeiten" aria-label="Bearbeiten">✎</button>
            <button class="action-btn action-btn--danger" @click="handleDelete(todo.id)" title="Löschen" aria-label="Löschen">✕</button>
          </div>
        </template>

        <!-- Bearbeitungs-Modus -->
        <template v-else>
          <form class="edit-form" @submit.prevent="saveEdit(todo.id)">
            <input v-model="editTitle" type="text" class="add-details__input" placeholder="Titel" />
            <textarea v-model="editDescription" class="add-details__textarea" placeholder="Beschreibung (optional)" rows="2" />
            <input v-model="editDueDate" type="date" class="add-details__input" title="Fälligkeitsdatum" />
            <select v-model="editAssignedTo" class="add-details__input" title="Zuweisen an">
              <option value="">– Niemand zugewiesen –</option>
              <option v-for="member in todosStore.members" :key="member.id" :value="member.id">
                {{ member.display_name }}
              </option>
            </select>
            <div class="edit-form__actions">
              <BaseButton type="submit" variant="primary" size="sm">Speichern</BaseButton>
              <BaseButton type="button" variant="secondary" size="sm" @click="cancelEdit">Abbrechen</BaseButton>
            </div>
          </form>
        </template>
      </li>
    </ul>

    <!-- Empty State -->
    <BaseEmptyState
      v-if="!todosStore.loading && openTodos.length === 0"
      icon="🎉"
      title="Keine offenen Aufgaben"
      subtitle="Erstelle oben eine neue Aufgabe"
    />

    <!-- Erledigte Todos (eingeklappt) -->
    <div v-if="doneTodos.length > 0" class="done-section">
      <button type="button" class="done-section__toggle" @click="showDone = !showDone">
        {{ doneTodos.length }} erledigt {{ showDone ? '▾' : '▸' }}
      </button>
      <ul v-if="showDone" class="item-list">
        <li v-for="todo in doneTodos" :key="todo.id" class="todo-row todo-row--done">
          <div class="todo-row__main" @click="handleToggle(todo.id)">
            <span class="todo-row__check">
              <input
                type="checkbox"
                :checked="todo.is_done"
                @click.stop
                @change="handleToggle(todo.id)"
                class="todo-row__checkbox"
              />
            </span>
            <div class="todo-row__content">
              <span class="todo-row__name">{{ todo.title }}</span>
              <div v-if="todo.description || todo.due_date || todo.assigned_to_user_id" class="todo-row__meta">
                <span v-if="todo.description" class="todo-row__desc">{{ todo.description }}</span>
                <span v-if="todo.due_date" class="todo-row__date">📅 {{ formatDate(todo.due_date) }}</span>
                <span v-if="getMemberName(todo.assigned_to_user_id)" class="initials-chip">
                  {{ getMemberName(todo.assigned_to_user_id)!.charAt(0).toUpperCase() }}
                </span>
              </div>
            </div>
          </div>
          <button class="action-btn action-btn--danger" @click="handleDelete(todo.id)" title="Löschen" aria-label="Löschen">✕</button>
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
  background: var(--color-bg);
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
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);
  font-family: var(--font-family);
  background: var(--color-surface);
  color: var(--color-text);
  transition: border-color var(--transition-fast);
}

.quick-add__input::placeholder { color: var(--color-text-muted); }
.quick-add__input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

/* Details Toggle */
.details-toggle {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: var(--text-sm);
  padding: var(--space-2) var(--space-3);
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  text-align: left;
  font-family: var(--font-family);
}
.details-toggle:hover { color: var(--color-text); }

/* Add Details */
.add-details {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.add-details__input,
.add-details__textarea {
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-neutral-300);
  border-radius: var(--radius-sm);
  font-size: var(--text-base);  /* 16px verhindert iOS-Zoom */
  font-family: var(--font-family);
  background: var(--color-surface);
  color: var(--color-text);
}
.add-details__textarea { resize: vertical; }
.add-details__input:focus,
.add-details__textarea:focus {
  outline: none;
  border-color: var(--color-primary);
}

/* Loading */
.loading-center {
  display: flex;
  justify-content: center;
  padding: var(--space-8) 0;
}

/* Item-Liste */
.item-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

/* Todo-Zeile */
.todo-row {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-2);
  border-bottom: 1px solid var(--color-neutral-100);
}

.todo-row--overdue {
  border-left: 3px solid var(--color-danger);
  padding-left: var(--space-3);
}

.todo-row__main {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  flex: 1;
  cursor: pointer;
  min-height: 44px; /* Touch-Target */
  -webkit-user-select: none;
  user-select: none;
}

.todo-row__check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  margin-top: 2px;
}

.todo-row__checkbox {
  width: 20px;
  height: 20px;
  accent-color: var(--color-primary);
  cursor: pointer;
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
  flex-wrap: wrap;
}

.todo-row__name {
  font-size: var(--text-base);
  color: var(--color-text);
}

/* Überfällig-Badge */
.overdue-badge {
  display: inline-block;
  padding: 1px var(--space-2);
  background: #FEF2F2;
  color: var(--color-danger);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-semibold);
  border-radius: var(--radius-full);
}

/* Meta-Zeile */
.todo-row__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  margin-top: 2px;
}

.todo-row__desc {
  width: 100%;
  color: var(--color-text-secondary);
}

.todo-row__date { white-space: nowrap; }
.todo-row__date--overdue { color: var(--color-danger); }

/* Initialen-Chip */
.initials-chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: var(--radius-full);
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: var(--text-xs);
  font-weight: var(--font-weight-bold);
  flex-shrink: 0;
}

/* Actions */
.todo-row__actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}

.action-btn {
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  font-size: var(--text-base);
  padding: var(--space-2);
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast), color var(--transition-fast);
  min-width: 44px;
  min-height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.action-btn:hover { background: var(--color-neutral-100); color: var(--color-primary); }
.action-btn--danger:hover { background: #FEF2F2; color: var(--color-danger); }

/* Done-Todos */
.todo-row--done { opacity: 0.55; }
.todo-row--done .todo-row__name {
  text-decoration: line-through;
  color: var(--color-text-muted);
}

/* Erledigt-Toggle */
.done-section { margin-top: var(--space-2); }
.done-section__toggle {
  background: none;
  border: none;
  font-size: var(--text-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-muted);
  cursor: pointer;
  padding: var(--space-2) 0;
  font-family: var(--font-family);
}
.done-section__toggle:hover { color: var(--color-text-secondary); }

@media (hover: hover) {
  .todo-row__main:hover {
    background: var(--color-neutral-50);
    border-radius: var(--radius-sm);
  }
}

/* Edit-Form */
.edit-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  width: 100%;
}

.edit-form__actions {
  display: flex;
  gap: var(--space-2);
}
</style>
