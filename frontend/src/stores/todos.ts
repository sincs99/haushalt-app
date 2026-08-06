import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineTodosRepository } from '../repositories/todosRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type { TodoItem, HouseholdMemberInfo } from '../types'

export const useTodosStore = defineStore('todos', () => {
  // Repositories — einmal im Store-Setup erstellen
  const repo = createOnlineTodosRepository()
  const householdRepo = createOnlineHouseholdsRepository()

  // State
  const items = ref<TodoItem[]>([])
  const members = ref<HouseholdMemberInfo[]>([])
  const loading = ref(false)

  // Interner State für Race-Condition-Schutz
  const pendingTempIds = new Set<string>()
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
  ) {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // 1. Optimistic: Sofort lokalen Temp-Eintrag erzeugen
    const tempId = crypto.randomUUID()
    const tempItem: TodoItem = {
      id: tempId,
      household_id: householdId,
      title,
      description: description ?? null,
      assigned_to_user_id: assignedToUserId ?? null,
      due_date: dueDate ?? null,
      is_done: false,
      created_by_user_id: authStore.user?.id ?? null,
      created_at: new Date().toISOString(),
      done_at: null,
    }
    items.value.push(tempItem)
    pendingTempIds.add(tempId)

    try {
      // 2. Server-Call via Repository
      const serverItem = await repo.create(householdId, {
        title,
        description,
        assigned_to_user_id: assignedToUserId,
        due_date: dueDate,
      })
      pendingTempIds.delete(tempId)

      // 3. Defensive Duplikat-Prüfung: Socket könnte schneller gewesen sein
      const serverIdx = items.value.findIndex(i => i.id === serverItem.id)
      const tempIdx = items.value.findIndex(i => i.id === tempId)

      if (serverIdx !== -1 && tempIdx !== -1) {
        // Socket war schneller → Server-Item existiert bereits → Temp-Item entfernen
        items.value.splice(tempIdx, 1)
      } else if (tempIdx !== -1) {
        // Normaler Fall → Temp-Item durch Server-Item ersetzen
        items.value[tempIdx] = serverItem
      }
      // Falls weder server noch temp gefunden → nichts tun (edge case, harmlos)
    } catch (error) {
      pendingTempIds.delete(tempId)
      // 4. Rollback bei Fehler
      items.value = items.value.filter(i => i.id !== tempId)
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

  // Socket-Handler — Idempotente Merges (Server gewinnt immer)
  function handleTodoCreated(serverItem: TodoItem) {
    // Wenn wir gerade selbst ein Todo erstellt haben, könnte das Socket-Event
    // vor dem REST-Response kommen. In diesem Fall ignorieren — der REST-Response
    // erledigt den Temp→Server-Swap.
    if (pendingTempIds.size > 0) {
      const existingIdx = items.value.findIndex(i => i.id === serverItem.id)
      if (existingIdx !== -1) {
        items.value[existingIdx] = serverItem
      }
      // KEIN push — REST-Response-Handling macht den Swap
      return
    }
    // Normaler Fall (Event von anderem Haushaltsmitglied)
    const existingIdx = items.value.findIndex(i => i.id === serverItem.id)
    if (existingIdx !== -1) {
      items.value[existingIdx] = serverItem
    } else {
      items.value.push(serverItem)
    }
  }

  function handleTodoUpdated(serverItem: TodoItem) {
    const idx = items.value.findIndex(i => i.id === serverItem.id)
    if (idx !== -1) {
      items.value[idx] = serverItem // Server gewinnt immer
    }
  }

  function handleTodoDeleted(data: { id: string }) {
    items.value = items.value.filter(i => i.id !== data.id)
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
    // Socket-Handlers
    handleTodoCreated,
    handleTodoUpdated,
    handleTodoDeleted,
  }
})
