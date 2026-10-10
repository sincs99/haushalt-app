import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuthStore } from './auth'
import { createOnlineTodosRepository } from '../repositories/todosRepository'
import { createOnlineHouseholdsRepository } from '../repositories/householdsRepository'
import type { TodoItem, HouseholdMemberInfo } from '../types'
import { upsertVersioned } from '../utils/syncVersion'
import { createRequestGuard } from '../utils/householdGuard'
import { createRetryIds } from '../utils/clientIds'

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
  // Verspätete Antworten eines anderen Haushalts/einer alten Sitzung verwerfen (CASA-12)
  const captureRequest = createRequestGuard()
  // Manueller Retry eines gescheiterten Creates nutzt dieselbe Client-ID (CASA-45)
  const retryIds = createRetryIds()

  // Actions
  async function fetchTodos() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'todos')

    loading.value = true
    try {
      const result = await repo.fetchAll(householdId)
      if (active()) items.value = result
    } finally {
      if (active.latest()) loading.value = false
    }
  }

  async function fetchMembers() {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return
    const active = captureRequest(householdId, 'members')

    const result = await householdRepo.fetchMembers(householdId)
    if (active()) members.value = result
  }

  async function addTodo(
    title: string,
    description?: string,
    assignedToUserId?: string,
    dueDate?: string,
    tags?: string[],
  ): Promise<string | undefined> {
    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    // 1. Optimistic: Sofort lokalen Eintrag mit endgültiger Client-ID erzeugen.
    //    Der Server übernimmt die ID → kein Temp-ID-Swap nötig.
    const retryKey = JSON.stringify([householdId, title, description, assignedToUserId, dueDate, tags])
    const todoId = retryIds.idFor(retryKey)
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
      retryIds.settled(retryKey)
      // ID zurückgeben, damit Aufrufer (z. B. Erinnerungen) nicht raten müssen
      return todoId
    } catch (error) {
      // 4a. Antwort verloren, Socket-Echo schon da → Server hat angelegt, behalten
      if (items.value.some(i => i.id === todoId && i.version > 0)) {
        retryIds.settled(retryKey)
        return todoId
      }
      // 4b. Rollback bei Fehler; bei Netzwerkfehler nutzt ein Retry dieselbe ID
      items.value = items.value.filter(i => i.id !== todoId)
      retryIds.failed(retryKey, todoId, error)
      throw error
    }
  }

  async function toggleDone(todoId: string) {
    const item = items.value.find(i => i.id === todoId)
    if (!item) return
    await setDone(todoId, !item.is_done)
  }

  /**
   * Setzt den Erledigt-Status explizit (statt zu kippen) — ein Doppeltipp öffnet
   * die Aufgabe so nicht wieder. Funktioniert auch, wenn die Aufgabe (noch) nicht
   * lokal geladen ist (z. B. Abhaken im Dashboard).
   */
  async function setDone(todoId: string, isDone: boolean) {
    if (pendingToggles.has(todoId)) return // Bereits in Flight → ignorieren

    const authStore = useAuthStore()
    const householdId = authStore.currentHouseholdId
    if (!householdId) return

    pendingToggles.add(todoId)

    // 1. Optimistic (nur falls lokal vorhanden)
    const item = items.value.find(i => i.id === todoId)
    const previousIsDone = item?.is_done
    const previousDoneAt = item?.done_at ?? null
    if (item) {
      item.is_done = isDone
      item.done_at = isDone ? new Date().toISOString() : null
    }

    try {
      // 2. Server-Call
      const serverItem = await repo.update(householdId, todoId, { is_done: isDone })
      if (serverItem) upsertVersioned(items.value, serverItem, false)
    } catch (error) {
      // 3. Rollback — frisch nachschlagen, da Socket-Events das Objekt ersetzt haben könnten
      const currentItem = items.value.find(i => i.id === todoId)
      if (currentItem && previousIsDone !== undefined) {
        currentItem.is_done = previousIsDone
        currentItem.done_at = previousDoneAt
      }
      throw error
    } finally {
      pendingToggles.delete(todoId)
    }
  }

  /**
   * Stellt eine gelöschte Aufgabe vollständig wieder her (Undo): Titel, Details,
   * Tags, Erledigt-Status und noch ausstehende Erinnerungen. Neue ID, damit ein
   * verspätetes Lösch-Event der alten ID die Wiederherstellung nicht entfernt.
   */
  async function restoreTodo(snapshot: TodoItem): Promise<string | undefined> {
    const newId = await addTodo(
      snapshot.title,
      snapshot.description ?? undefined,
      snapshot.assigned_to_user_id ?? undefined,
      snapshot.due_date ?? undefined,
      snapshot.tags?.length ? [...snapshot.tags] : undefined,
    )
    if (!newId) return newId
    if (snapshot.is_done) {
      await setDone(newId, true)
    }
    // Erinnerungen: nur zukünftige, best effort (Aufgabe ist bereits zurück)
    const now = Date.now()
    const future = (snapshot.reminders ?? []).filter(r => new Date(r.remind_at).getTime() > now)
    await Promise.allSettled(future.map(r => addReminder(newId, r.remind_at)))
    return newId
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
    setDone,
    restoreTodo,
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
