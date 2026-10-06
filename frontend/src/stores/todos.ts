import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineTodosRepository } from '../repositories/todosRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type { TodoItem, HouseholdMemberInfo } from '../types'
import { upsertVersioned } from '../utils/syncVersion'

export const useTodosStore = defineStore('todos', () => {
  // Repositories — einmal im Store-Setup erstellen
  const repo = createOnlineTodosRepository()
  const householdRepo = createOnlineHouseholdsRepository()

  // State
  const items = ref<TodoItem[]>([])
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)

  // Interner State für Race-Condition-Schutz
  const pendingToggles = new Set<string>()

  // Actions
  async function fetchTodos() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    loading.value = true
    try {
      items.value = await repo.fetchAll(householdId)
    } finally {
      loading.value = false
    }
  }

  async function fetchMembers() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    members.value = await householdRepo.fetchMembers(householdId)
  }

  async function addTodo(
    title: string,
    description?: string,
    assignedToUserId?: string,
    dueDate?: string,
    tags?: string[],
  ) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // 1. Optimistic: Sofort lokalen Eintrag mit endgültiger Client-ID erzeugen.
    //    Der Server übernimmt die ID → kein Temp-ID-Swap nötig.
    const todoId = crypto.randomUUID()
    const now = new Date().toISOString()
    const optimisticItem: TodoItem = {
      id: todoId,
      household_id: householdId,
      title,
      description: description ?? null,
      assigned_to_user_id: assignedToUserId ?? null,
      due_date: dueDate ?? null,
      is_done: false,
      created_by_user_id: authStore.user?.id ?? null,
      created_at: now,
      done_at: null,
      tags: tags ?? [],
      updated_at: now,
      version: 0, // noch nicht vom Server bestätigt
      reminders: [],
    }
    items.value.push(optimisticItem)

    try {
      // 2. Server-Call via Repository
      const serverItem = await repo.create(householdId, {
        id: todoId,
        title,
        description,
        assigned_to_user_id: assignedToUserId,
        due_date: dueDate,
        tags,
      })

      // 3. Optimistischen Eintrag durch Server-Stand ersetzen. Gleiche ID wie das
      //    Socket-Event → egal wer zuerst kommt, es entsteht kein Duplikat.
      //    Kein Insert, falls das Todo inzwischen gelöscht wurde.
      upsertVersioned(items.value, serverItem, false)
    } catch (error) {
      // 4. Rollback bei Fehler
      items.value = items.value.filter(i => i.id !== todoId)
      throw error
    }
  }

  async function toggleDone(todoId: string) {
    if (pendingToggles.has(todoId)) return // Bereits in Flight → ignorieren
    pendingToggles.add(todoId)

    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) {
      pendingToggles.delete(todoId)
      return
    }

    const item = items.value.find(i => i.id === todoId)
    if (!item) {
      pendingToggles.delete(todoId)
      return
    }

    // 1. Optimistic Toggle
    const previousIsDone = item.is_done
    const previousDoneAt = item.done_at
    item.is_done = !item.is_done
    item.done_at = item.is_done ? new Date().toISOString() : null

    try {
      // 2. Server-Call
      await repo.update(householdId, todoId, { is_done: item.is_done })
    } catch (error) {
      // 3. Rollback — frisch nachschlagen, da Socket-Events das Objekt ersetzt haben könnten
      const currentItem = items.value.find(i => i.id === todoId)
      if (currentItem) {
        currentItem.is_done = previousIsDone
        currentItem.done_at = previousDoneAt
      }
      throw error
    } finally {
      pendingToggles.delete(todoId)
    }
  }

  async function updateTodo(todoId: string, data: Partial<TodoItem>) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const item = items.value.find(i => i.id === todoId)
    if (!item) return

    // 1. Snapshot für Rollback
    const snapshot = { ...item }

    // 2. Optimistic: Sofort aktualisieren
    Object.assign(item, data)

    try {
      // 3. Server-Call
      await repo.update(householdId, todoId, data)
    } catch (error) {
      // 4. Rollback auf Snapshot
      Object.assign(item, snapshot)
      throw error
    }
  }

  async function deleteTodo(todoId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // 1. Snapshot für Rollback
    const itemIndex = items.value.findIndex(i => i.id === todoId)
    if (itemIndex === -1) return
    const removedItem = items.value[itemIndex]

    // 2. Optimistic: Sofort entfernen
    items.value.splice(itemIndex, 1)

    try {
      // 3. Server-Call
      await repo.remove(householdId, todoId)
    } catch (error) {
      // 4. Rollback: Item wieder einfügen an gleicher Position
      items.value.splice(itemIndex, 0, removedItem)
      throw error
    }
  }

  // Socket-Handler — Idempotente Merges (neuere Server-Version gewinnt)
  function handleTodoCreated(serverItem: TodoItem) {
    // Idempotenter Merge per ID: eigene Todos tragen bereits die Client-ID,
    // das Event ersetzt den optimistischen Eintrag statt ein Duplikat anzulegen.
    // (Früher wurden hier Events anderer User verworfen, solange ein eigener
    // Create lief.)
    upsertVersioned(items.value, serverItem, true)
  }

  function handleTodoUpdated(serverItem: TodoItem) {
    // Veraltete Events (niedrigere version) werden verworfen
    upsertVersioned(items.value, serverItem, false)
  }

  function handleTodoDeleted(data: { id: string }) {
    items.value = items.value.filter(i => i.id !== data.id)
  }

  async function addReminder(todoId: string, remindAt: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const item = items.value.find(i => i.id === todoId)
    if (!item) return

    // Optimistic: Temp-Reminder einfügen
    const tempId = crypto.randomUUID()
    const tempReminder = {
      id: tempId,
      todo_id: todoId,
      remind_at: remindAt,
      notified_at: null,
      created_at: new Date().toISOString(),
    }
    item.reminders = [...item.reminders, tempReminder].sort(
      (a, b) => new Date(a.remind_at).getTime() - new Date(b.remind_at).getTime(),
    )

    try {
      const serverReminder = await repo.addReminder(householdId, todoId, remindAt)
      // Server-Reminder ersetzt Temp
      const currentItem = items.value.find(i => i.id === todoId)
      if (currentItem) {
        currentItem.reminders = currentItem.reminders
          .map(r => (r.id === tempId ? serverReminder : r))
          .sort((a, b) => new Date(a.remind_at).getTime() - new Date(b.remind_at).getTime())
      }
    } catch (error) {
      // Rollback
      const currentItem = items.value.find(i => i.id === todoId)
      if (currentItem) {
        currentItem.reminders = currentItem.reminders.filter(r => r.id !== tempId)
      }
      throw error
    }
  }

  async function deleteReminder(todoId: string, reminderId: string) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    const item = items.value.find(i => i.id === todoId)
    if (!item) return

    // Snapshot für Rollback
    const snapshot = [...item.reminders]

    // Optimistic: sofort entfernen
    item.reminders = item.reminders.filter(r => r.id !== reminderId)

    try {
      await repo.deleteReminder(householdId, todoId, reminderId)
    } catch (error) {
      // Rollback
      const currentItem = items.value.find(i => i.id === todoId)
      if (currentItem) {
        currentItem.reminders = snapshot
      }
      throw error
    }
  }

  return {
    // State
    items,
    members,
    loading,
    // Actions
    fetchTodos,
    fetchMembers,
    addTodo,
    toggleDone,
    updateTodo,
    deleteTodo,
    addReminder,
    deleteReminder,
    // Socket-Handlers
    handleTodoCreated,
    handleTodoUpdated,
    handleTodoDeleted,
  }
})
